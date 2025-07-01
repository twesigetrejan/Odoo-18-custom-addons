from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging
from ..config import (get_config, GET_FILTERED_SAVINGS_PRODUCTS_COLLECTION_ENDPOINT)
import requests
from datetime import datetime

_logger = logging.getLogger(__name__)

class ResConfigSettings(models.TransientModel):
    _name = 'res.config.settings'
    _inherit = ['res.config.settings', 'api.token.mixin']

    sync_interval = fields.Integer(string='Sync Interval (minutes)', default=1, config_parameter='savings_management.sync_interval')

    @api.constrains('sync_interval')
    def _check_sync_interval(self):
        for record in self:
            if record.sync_interval < 1:
                raise ValidationError("Sync interval must be at least 1 minute.")
            
    
    def set_values(self):
        super(ResConfigSettings, self).set_values()
        self.env['ir.cron'].sudo().search([('name', '=', 'Sync Savings Deposits')]).write({
            'interval_number': self.sync_interval,
            'interval_type': 'minutes',
        })

    def _get_latest_local_savings_product_date(self):
        """Get the write_date of the most recently updated local savings product."""
        SavingsProduct = self.env['sacco.savings.product']
        latest_product = SavingsProduct.search([
            ('mongo_db_id', '!=', False),
            ('mongo_db_id', '!=', ''),
        ], order='write_date desc', limit=1)
        
        return latest_product.write_date if latest_product else None

    def _fetch_filtered_savings_products(self, token, last_updated_date=None):
        """Fetch savings products updated since the given date."""
        config = get_config(self.env)
        api_url = f"{config['BASE_URL']}/{GET_FILTERED_SAVINGS_PRODUCTS_COLLECTION_ENDPOINT}"
        headers = self._get_request_headers()
        
        body = {}
        if last_updated_date:
            date_str = last_updated_date.isoformat()
            body = {
                "lastUpdated": f"$date_filter:gt {date_str}"
            }

        page = 1
        limit = 1000
        all_products = []

        while True:
            try:
                params = {
                    'page': page,
                    'limit': limit
                }
                _logger.debug(f"Fetching page {page} with params {params} and body {body}")
                response = requests.post(api_url, headers=headers, json=body, params=params)
                response.raise_for_status()
                
                data = response.json()
                current_products = data.get('rows', [])
                
                if not current_products:
                    break

                all_products.extend(current_products)

                if len(current_products) < limit:
                    break

                page += 1

            except requests.RequestException as e:
                _logger.error(f"API request failed: {e}")
                _logger.error(f"Response content: {response.text}")
                raise UserError(f"API error: {response.text}")

        return {'rows': all_products}

    def _fetch_all_savings_products(self, token):
        """Fetch all savings products using pagination."""
        all_products = []
        page = 1
        limit = 1000
        
        while True:
            data = self._fetch_products_page(token, page, limit)
            if not data or not data.get('rows'):
                break
                
            current_products = data.get('rows', [])
            all_products.extend(current_products)
            
            if len(current_products) < limit:
                break
                
            page += 1
            
        return {'rows': all_products}

    def _fetch_products_page(self, token, page=1, limit=1000):
        """Fetch savings products page from API."""
        config = get_config(self.env)
        api_url = f"{config['BASE_URL']}/{GET_FILTERED_SAVINGS_PRODUCTS_COLLECTION_ENDPOINT}"
        headers = self._get_request_headers()
        
        params = {
            'page': page,
            'limit': limit
        }
        
        body = {}

        try:
            response = requests.post(api_url, headers=headers, params=params, json=body)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            _logger.error(f"Failed to fetch savings products page: {str(e)}")
            return None

    def action_sync_savings_products(self):
        """Modified main sync method using pagination."""
        _logger.info("Starting savings products synchronization")
        token = self._get_authentication_token()
        if not token:
            return self._show_notification('Error', 'Failed to login into external system', 'danger')

        # Get latest local record date
        last_updated_date = self._get_latest_local_savings_product_date()
        
        # Fetch data using appropriate method
        if last_updated_date:
            data = self._fetch_filtered_savings_products(token, last_updated_date)
        else:
            data = self._fetch_all_savings_products(token)

        if not data:
            return self._show_notification('Error', 'Failed to fetch savings products', 'danger')

        success_count = skip_count = error_count = 0
        
        for savings_product in data.get('rows', []):
            try:
                result = self._create_or_update_savings_product(savings_product)
                if result == 'created':
                    success_count += 1
                elif result == 'skipped':
                    skip_count += 1
                else:
                    error_count += 1
            except Exception as e:
                _logger.exception(f"Error processing savings product: {str(e)}")
                error_count += 1

        return self._show_notification('Sync Complete', 
                                f'Processed {success_count} products. Skipped {skip_count}. Errors: {error_count}',
                                'success' if error_count == 0 else 'warning')

    def _get_unique_code(self):
        """
        Generates a unique account code using Odoo's sequence mechanism.
        """
        sequence = self.env['ir.sequence'].next_by_code('sacco.savings.product.code')
        if not sequence:
            _logger.error("Failed to generate unique account code. Sequence not found.")
            return 'SP000'  
        return sequence
    
    def _get_currency(self, currency_code):
        """Get currency record from currency code"""
        currency = self.env['res.currency'].search([('name', '=', currency_code)], limit=1)
        if not currency:
            raise ValidationError(_(f"Currency {currency_code} not found in the system"))
        return currency


    def _create_or_update_savings_product(self, savings_product_data):
        """
        Processes savings products using Odoo sequence for code generation.
        """
        SavingsProduct = self.env['sacco.savings.product']
        AccountAccount = self.env['account.account']
        AccountJournal = self.env['account.journal']

        _logger.info(f"Processing savings products from refID: {savings_product_data.get('refID', 'Unknown')}")

        try:
            # Validate input data
            if not savings_product_data or 'productDetails' not in savings_product_data:
                _logger.error("Invalid savings product data: missing productDetails")
                return None

            created_products = []

            for product_detail in savings_product_data.get('productDetails', []):
                try:
                    product_name = product_detail.get('product', '').strip()
                    if not product_name:
                        _logger.warning("Skipping product with empty name")
                        continue

                    # Check for existing product
                    existing_product = SavingsProduct.search([
                        ('name', '=', product_name),
                        ('ref_id', '=', savings_product_data.get('refID', ''))
                    ], limit=1)

                    if existing_product:
                        _logger.info(f"Product {product_name} already exists. Skipping creation.")
                        continue

                    # Generate unique code using sequence
                    account_code_prefix = self._get_unique_code()
                    _logger.info(f"Generated unique account code prefix: {account_code_prefix}")

                    # Create accounts if they don't exist
                    savings_product_account = AccountAccount.search([('code', '=', f"{account_code_prefix}1")], limit=1)
                    if savings_product_account:
                        _logger.info(f"Account for savings product already exists: {savings_product_account.name}")
                    else:
                        savings_product_account = AccountAccount.create({
                            'name': f"{product_name} Savings Deposits",
                            'code': f"{account_code_prefix}1",
                            'account_type': 'asset_current',
                            'reconcile': True,
                        })
                        _logger.info(f"Created savings product account: {savings_product_account.name}")

                    withdrawal_account = AccountAccount.search([('code', '=', f"{account_code_prefix}2")], limit=1)
                    if withdrawal_account:
                        _logger.info(f"Account for withdrawals already exists: {withdrawal_account.name}")
                    else:
                        withdrawal_account = AccountAccount.create({
                            'name': f"{product_name} Savings Withdrawals",
                            'code': f"{account_code_prefix}2",
                            'account_type': 'asset_current',
                            'reconcile': True,
                        })
                        _logger.info(f"Created withdrawal account: {withdrawal_account.name}")

                    interest_account = AccountAccount.search([('code', '=', f"{account_code_prefix}3")], limit=1)
                    if interest_account:
                        _logger.info(f"Account for interest already exists: {interest_account.name}")
                    else:
                        interest_account = AccountAccount.create({
                            'name': f"Interest Expense for {product_name} Savings",
                            'code': f"{account_code_prefix}3",
                            'account_type': 'expense',
                            'reconcile': True,
                        })
                        _logger.info(f"Created interest account: {interest_account.name}")

                    # Create journals if they don't exist
                    savings_product_journal = AccountJournal.search([('code', '=', f"{account_code_prefix}SP")], limit=1)
                    if savings_product_journal:
                        _logger.info(f"Journal for savings product already exists: {savings_product_journal.name}")
                    else:
                        savings_product_journal = AccountJournal.create({
                            'name': f"{product_name} Savings Journal",
                            'code': f"{account_code_prefix}SP",
                            'type': 'general',
                        })
                        _logger.info(f"Created savings product journal: {savings_product_journal.name}")

                    disburse_journal = AccountJournal.search([('code', '=', f"{account_code_prefix}WD")], limit=1)
                    if disburse_journal:
                        _logger.info(f"Journal for disbursements already exists: {disburse_journal.name}")
                    else:
                        disburse_journal = AccountJournal.create({
                            'name': f"{product_name} Disburse Journal",
                            'code': f"{account_code_prefix}WD",
                            'type': 'general',
                        })
                        _logger.info(f"Created disburse journal: {disburse_journal.name}")

                    # Create savings product record
                    minimum_amount = float(product_detail['minimumAmount']) if product_detail.get('minimumAmount') is not None else 0.0
                    interest_rate = float(product_detail.get('interestRate', 0.0)) or 0.0
                    interest_period = 'monthly' if product_detail.get('interestCalculationPreriod') == 'monthly' else 'annually'
                    currency = self._get_currency(product_detail.get('currency'))
                    
                    product_vals = {
                        'name': product_name,
                        'interest_rate': interest_rate,
                        'period': interest_period,
                        'currency_id': currency.id,
                        'createdBy': savings_product_data.get('createdBy', ''),
                        'mongo_db_id': savings_product_data.get('_id', ''),
                        'ref_id': savings_product_data.get('refID', ''),
                        'withdrawal_account_id': withdrawal_account.id,
                        'interest_account_id': interest_account.id,
                        'savings_product_account_id': savings_product_account.id,
                        'savings_product_journal_id': savings_product_journal.id,
                        'disburse_journal_id': disburse_journal.id
                    }

                    new_product = SavingsProduct.create(product_vals)
                    created_products.append(new_product)
                    _logger.info(f"Created new savings product: {product_name}")

                except Exception as ex:
                    _logger.error(f"Error processing product detail {product_detail}: {str(ex)}")
                    continue

            return 'created' if created_products else 'skipped'

        except Exception as e:
            _logger.error(f"Error creating or updating savings product: {str(e)}")
            return 'error'

    
    def _show_notification(self, title, message, category):
        """Helper function to display notification"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': category,
                'sticky': False,
            }
        }
