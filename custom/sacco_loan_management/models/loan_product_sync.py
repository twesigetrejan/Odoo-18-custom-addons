from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import logging
import requests
from datetime import datetime
from ..config import (get_config, GET_LOAN_PRODUCTS_COLLECTION_ENDPOINT)

_logger = logging.getLogger(__name__)

class LoanProductSync(models.TransientModel):
    _name = 'sacco.loan.product.sync'
    _description = 'Loan Product Sync Model'
    _inherit = ['api.token.mixin']

    def _get_loan_unique_code(self):
        """
        Generates a unique account code using Odoo's sequence mechanism for loans.
        """
        sequence = self.env['ir.sequence'].next_by_code('sacco.loan.product.code')
        if not sequence:
            _logger.error("Failed to generate unique loan code. Sequence not found.")
            return 'LP000'
        return sequence

    def action_sync_loan_products(self):
        _logger.info("================= Starting loan products synchronization ==================")
        config = get_config(self.env)
        token = self._get_authentication_token()
        if not token:
            _logger.error("Failed to obtain auth token. Aborting synchronization.")
            return self._show_notification('Error', 'Failed to login into external system', 'danger')
        
        SACCO_NAME = self.env.user.company_id.name
        _logger.info(f"Syncing loan products for SACCO: {SACCO_NAME}")

        api_url = f"{config['BASE_URL']}/{GET_LOAN_PRODUCTS_COLLECTION_ENDPOINT}"
        headers = self._get_request_headers()
        
        try:
            _logger.info(f"Fetching data from API: {api_url}")
            response = requests.get(api_url, headers=headers)
            response.raise_for_status()
            data = response.json()
            _logger.info(f"Successfully fetched data from API. Received {len(data.get('rows', []))} loan product records.")
        except requests.RequestException as e:
            _logger.error(f"Failed to fetch data from API: {str(e)}")
            return self._show_notification('Error', f'Failed to sync loan products: {str(e)}', 'danger')

        success_count = 0
        skip_count = 0
        error_count = 0
        
        if 'rows' in data:
            for loan_product in data['rows']:
                try:
                    _logger.info(f"Processing loan product: {loan_product.get('refID')}")
                    result = self._create_or_update_loan_product(loan_product)
                    if result == 'created':
                        success_count += 1
                        _logger.info(f"Successfully processed and saved loan product: {loan_product.get('refID')}")
                    elif result == 'skipped':
                        skip_count += 1
                        _logger.info(f"Skipped existing loan product: {loan_product.get('refID')}")
                    else:
                        error_count += 1
                        _logger.error(f"Failed to save loan product: {loan_product.get('refID')}")
                except Exception as e:
                    _logger.exception(f"Error processing loan product {loan_product.get('refID')}: {str(e)}")
                    error_count += 1

        _logger.info(f"Sync complete. Processed {success_count} products successfully. Skipped {skip_count} existing products. Encountered {error_count} errors.")
        return self._show_notification('Sync Complete', 
                                     f'Successfully processed {success_count} products. '
                                     f'Skipped {skip_count} existing products. '
                                     f'Errors encountered: {error_count}',
                                     'success' if error_count == 0 else 'warning')

    def _create_or_update_loan_product(self, loan_product_data):
        """
        Processes loan products using Odoo sequence for code generation.
        Creates necessary accounts and journals for each loan product.
        """
        LoanProduct = self.env['sacco.loan.type']
        AccountAccount = self.env['account.account']
        AccountJournal = self.env['account.journal']

        _logger.info(f"Processing loan products from refID: {loan_product_data.get('refID', 'Unknown')}")

        try:
            # Validate input data
            if not loan_product_data or 'productDetails' not in loan_product_data:
                _logger.error("Invalid loan product data: missing productDetails")
                return None

            created_products = []

            for product_detail in loan_product_data.get('productDetails', []):
                try:
                    product_name = product_detail.get('product', '').strip()
                    if not product_name:
                        _logger.warning("Skipping product with empty name")
                        continue

                    # Check for existing product
                    existing_product = LoanProduct.search([
                        ('name', '=', product_name),
                        ('ref_id', '=', loan_product_data.get('refID', ''))
                    ], limit=1)

                    if existing_product:
                        _logger.info(f"Product {product_name} already exists. Skipping creation.")
                        continue

                    # Generate unique code using sequence
                    account_code_prefix = self._get_loan_unique_code()
                    _logger.info(f"Generated unique account code prefix: {account_code_prefix}")

                    # Create required accounts with error handling and duplicate checking
                    accounts = self._create_loan_accounts(account_code_prefix, product_name)
                    journals = self._create_loan_journals(account_code_prefix, product_name)

                    if not accounts or not journals:
                        _logger.error(f"Failed to create necessary accounts or journals for {product_name}")
                        continue

                    # Prepare values for loan product creation with default values
                    interest_rate = float(product_detail.get('interestRate', 0.0)) or 0.0
                    minimum_amount = float(product_detail.get('minimumAmount', 0.0)) or 0.0
                    interest_period = product_detail.get('interestCalculationPreriod', 'monthly').lower()
                    amortization = product_detail.get('amortizationMethod', 'straightLine').lower()

                    product_vals = {
                        'name': product_name,
                        'is_interest_apply': interest_rate > 0,
                        'interest_mode': 'reducing' if amortization == 'reducing' else 'flat',
                        'rate': interest_rate,
                        'loan_amount': minimum_amount,
                        'loan_term_by_month': 12,  # Default value
                        'none_interest_month': 0,  # Default value
                        'createdBy': loan_product_data.get('createdBy', ''),
                        'mongo_db_id': loan_product_data.get('_id', ''),
                        'ref_id': loan_product_data.get('refID', ''),
                        'loan_account_id': accounts['disburse_account'].id,
                        'interest_account_id': accounts['interest_account'].id,
                        'installment_account_id': accounts['installment_account'].id,
                        'disburse_journal_id': journals['disburse_journal'].id,
                        'loan_payment_journal_id': journals['payment_journal'].id,
                    }

                    new_product = LoanProduct.create(product_vals)
                    created_products.append(new_product)
                    _logger.info(f"Created new loan product: {product_name}")

                except Exception as ex:
                    _logger.error(f"Error processing product detail {product_detail}: {str(ex)}")
                    continue

            return 'created' if created_products else 'skipped'

        except Exception as e:
            _logger.error(f"Error creating or updating loan product: {str(e)}")
            return 'error'

    def _create_loan_accounts(self, code_prefix, product_name):
        """Creates the necessary accounts for a loan product."""
        AccountAccount = self.env['account.account']
        accounts = {}
        
        try:
            # Disburse Account (Loan Account)
            disburse_account = AccountAccount.search([('code', '=', f"{code_prefix}1")], limit=1)
            if not disburse_account:
                disburse_account = AccountAccount.create({
                    'name': f"{product_name} - Disbursements",
                    'code': f"{code_prefix}1",
                    'account_type': 'asset_receivable',
                    'reconcile': True,
                })

            # Interest Account
            interest_account = AccountAccount.search([('code', '=', f"{code_prefix}2")], limit=1)
            if not interest_account:
                interest_account = AccountAccount.create({
                    'name': f"Interest Income from {product_name}",
                    'code': f"{code_prefix}2",
                    'account_type': 'income',
                    'reconcile': True,
                })

            # Installment Account
            installment_account = AccountAccount.search([('code', '=', f"{code_prefix}3")], limit=1)
            if not installment_account:
                installment_account = AccountAccount.create({
                    'name': f"Loan Installments - {product_name}",
                    'code': f"{code_prefix}3",
                    'account_type': 'asset_receivable',
                    'reconcile': True,
                })

            accounts = {
                'disburse_account': disburse_account,
                'interest_account': interest_account,
                'installment_account': installment_account,
            }

        except Exception as e:
            _logger.error(f"Error creating loan accounts: {str(e)}")
            return None

        return accounts

    def _create_loan_journals(self, code_prefix, product_name):
        """Creates the necessary journals for a loan product."""
        AccountJournal = self.env['account.journal']
        journals = {}
        
        try:
            # Disburse Journal
            disburse_journal = AccountJournal.search([('code', '=', f"{code_prefix}D")], limit=1)
            if not disburse_journal:
                disburse_journal = AccountJournal.create({
                    'name': f"{product_name} Disbursement Journal",
                    'code': f"{code_prefix}D",
                    'type': 'general',
                })

            # Payment Journal
            payment_journal = AccountJournal.search([('code', '=', f"{code_prefix}P")], limit=1)
            if not payment_journal:
                payment_journal = AccountJournal.create({
                    'name': f"{product_name} Payment Journal",
                    'code': f"{code_prefix}P",
                    'type': 'bank',
                })

            journals = {
                'disburse_journal': disburse_journal,
                'payment_journal': payment_journal,
            }

        except Exception as e:
            _logger.error(f"Error creating loan journals: {str(e)}")
            return None

        return journals

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