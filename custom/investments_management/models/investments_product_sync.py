from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging
import requests
from datetime import datetime
from ..config import (BASE_URL, get_config, GET_INVESTMENTS_PRODUCTS_COLLECTION_ENDPOINT)

_logger = logging.getLogger(__name__)

class InvestmentProductSync(models.TransientModel):
    _name = 'sacco.investments.product.sync'
    _description = 'Investments Product Sync Model'
    _inherit = ['api.token.mixin']

    def _get_investment_unique_code(self):
        """
        Generates a unique account code using Odoo's sequence mechanism for investments.
        """
        sequence = self.env['ir.sequence'].next_by_code('sacco.investment.product.code')
        if not sequence:
            _logger.error("Failed to generate unique investment code. Sequence not found.")
            return 'IP000'
        return sequence

    def action_sync_investment_products(self):
        _logger.info("================= Starting investment products synchronization ==================")
        token = self._get_authentication_token()
        if not token:
            _logger.error("Failed to obtain auth token. Aborting synchronization.")
            return self._show_notification('Error', 'Failed to login into external system', 'danger')
        
        SACCO_NAME = self.env.user.company_id.name
        _logger.info(f"Syncing investment products for SACCO: {SACCO_NAME}")
        
        config = get_config(self.env)
        api_url = f"{config['BASE_URL']}/{GET_INVESTMENTS_PRODUCTS_COLLECTION_ENDPOINT}"
        headers = self._get_request_headers()
        
        try:
            _logger.info(f"Fetching data from API: {api_url}")
            response = requests.get(api_url, headers=headers)
            response.raise_for_status()
            data = response.json()
            _logger.info(f"Successfully fetched data from API. Received {len(data.get('rows', []))} investment product records.")
        except requests.RequestException as e:
            _logger.error(f"Failed to fetch data from API: {str(e)}")
            return self._show_notification('Error', f'Failed to sync investment products: {str(e)}', 'danger')

        success_count = 0
        skip_count = 0
        error_count = 0
        
        if 'rows' in data:
            for investment_product in data['rows']:
                try:
                    _logger.info(f"Processing investment product: {investment_product.get('refID')}")
                    result = self._create_or_update_investment_product(investment_product)
                    if result == 'created':
                        success_count += 1
                        _logger.info(f"Successfully processed and saved investment product: {investment_product.get('refID')}")
                    elif result == 'skipped':
                        skip_count += 1
                        _logger.info(f"Skipped existing investment product: {investment_product.get('refID')}")
                    else:
                        error_count += 1
                        _logger.error(f"Failed to save investment product: {investment_product.get('refID')}")
                except Exception as e:
                    _logger.exception(f"Error processing investment product {investment_product.get('refID')}: {str(e)}")
                    error_count += 1

        _logger.info(f"Sync complete. Processed {success_count} products successfully. Skipped {skip_count} existing products. Encountered {error_count} errors.")
        return self._show_notification('Sync Complete', 
                                     f'Successfully processed {success_count} products. '
                                     f'Skipped {skip_count} existing products. '
                                     f'Errors encountered: {error_count}',
                                     'success' if error_count == 0 else 'warning')

    def _create_or_update_investment_product(self, investment_product_data):
        """
        Processes investment products using Odoo sequence for code generation.
        Includes checks for existing accounts and journals.
        """
        InvestmentProduct = self.env['sacco.investments.product']
        AccountAccount = self.env['account.account']
        AccountJournal = self.env['account.journal']

        _logger.info(f"Processing investment products from refID: {investment_product_data.get('refID', 'Unknown')}")

        try:
            # Validate input data
            if not investment_product_data or 'productDetails' not in investment_product_data:
                _logger.error("Invalid investment product data: missing productDetails")
                return None

            created_products = []

            for product_detail in investment_product_data.get('productDetails', []):
                try:
                    product_name = product_detail.get('product', '').strip()
                    if not product_name:
                        _logger.warning("Skipping product with empty name")
                        continue

                    # Check for existing product
                    existing_product = InvestmentProduct.search([
                        ('name', '=', product_name),
                        ('ref_id', '=', investment_product_data.get('refID', ''))
                    ], limit=1)

                    if existing_product:
                        _logger.info(f"Product {product_name} already exists. Skipping creation.")
                        continue

                    # Generate unique code using sequence
                    account_code_prefix = self._get_investment_unique_code()
                    _logger.info(f"Generated unique account code prefix: {account_code_prefix}")

                    # Check and create cash account if it doesn't exist
                    cash_account = AccountAccount.search([('code', '=', f"{account_code_prefix}1")], limit=1)
                    if cash_account:
                        _logger.info(f"Cash account already exists: {cash_account.name}")
                    else:
                        cash_account = AccountAccount.create({
                            'name': f"{product_name} Investment Cash Account",
                            'code': f"{account_code_prefix}1",
                            'account_type': 'asset_current',
                            'reconcile': True,
                        })
                        _logger.info(f"Created investment cash account: {cash_account.name}")

                    # Check and create investment account if it doesn't exist
                    investment_account = AccountAccount.search([('code', '=', f"{account_code_prefix}2")], limit=1)
                    if investment_account:
                        _logger.info(f"Investment account already exists: {investment_account.name}")
                    else:
                        investment_account = AccountAccount.create({
                            'name': f"{product_name} Investment Fund Account",
                            'code': f"{account_code_prefix}2",
                            'account_type': 'liability_current',
                            'reconcile': True,
                        })
                        _logger.info(f"Created investment fund account: {investment_account.name}")

                    # Check and create cash journal if it doesn't exist
                    cash_journal = AccountJournal.search([('code', '=', f"{account_code_prefix}C")], limit=1)
                    if cash_journal:
                        _logger.info(f"Cash journal already exists: {cash_journal.name}")
                    else:
                        cash_journal = AccountJournal.create({
                            'name': f"{product_name} Investment Cash Journal",
                            'code': f"{account_code_prefix}C",
                            'type': 'cash',
                        })
                        _logger.info(f"Created investment cash journal: {cash_journal.name}")

                    # Check and create investment journal if it doesn't exist
                    investment_journal = AccountJournal.search([('code', '=', f"{account_code_prefix}I")], limit=1)
                    if investment_journal:
                        _logger.info(f"Investment journal already exists: {investment_journal.name}")
                    else:
                        investment_journal = AccountJournal.create({
                            'name': f"{product_name} Investment Fund Journal",
                            'code': f"{account_code_prefix}I",
                            'type': 'general',
                        })
                        _logger.info(f"Created investment fund journal: {investment_journal.name}")

                    # Prepare values for investment product creation
                    minimum_amount = float(product_detail['minimumAmount']) if product_detail.get('minimumAmount') is not None else 0.0
                    interest_rate = float(product_detail.get('interestRate', 0.0)) or 0.0
                    interest_period = product_detail.get('interestCalculationPreriod', 'monthly').lower()
                    if interest_period not in ['daily', 'weekly', 'monthly', 'annually']:
                        interest_period = 'monthly'  # Default to monthly if invalid period received

                    product_vals = {
                        'name': product_name,
                        'interest_rate': interest_rate,
                        'minimum_balance': minimum_amount,
                        'period': interest_period,
                        'investment_risk': 'low',
                        'maturity_period': 12,  
                        'is_pooled_investment': False,  
                        'minimum_pool_amount': 0.0,  
                        'createdBy': investment_product_data.get('createdBy', ''),
                        'mongo_db_id': investment_product_data.get('_id', ''),
                        'ref_id': investment_product_data.get('refID', ''),
                        'investments_product_cash_account_id': cash_account.id,
                        'investments_product_cash_journal_id': cash_journal.id,
                        'investments_product_account_id': investment_account.id,
                        'investments_product_journal_id': investment_journal.id,
                    }

                    new_product = InvestmentProduct.create(product_vals)
                    created_products.append(new_product)
                    _logger.info(f"Created new investment product: {product_name}")

                except Exception as ex:
                    _logger.error(f"Error processing product detail {product_detail}: {str(ex)}")
                    continue

            return 'created' if created_products else 'skipped'

        except Exception as e:
            _logger.error(f"Error creating or updating investment product: {str(e)}")
            return 'error'
        
    def _show_notification(self, title, message, type='info'):
        """Show notification in UI"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'sticky': True,
                'type': type,
            }
        }