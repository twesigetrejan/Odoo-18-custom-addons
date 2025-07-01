# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import pandas as pd
import base64
import logging
import os

# Configure custom error logger
log_file_path = os.path.join(os.path.dirname(__file__), 'OdooLogs', 'product_accounts_import_errors.log')
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
error_logger = logging.getLogger('product_accounts_import_errors')
error_logger.setLevel(logging.ERROR)
if not error_logger.handlers:
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    error_logger.addHandler(file_handler)

_logger = logging.getLogger(__name__)

class ProductAccountsImportWizard(models.TransientModel):
    _name = 'product.accounts.import.wizard'
    _description = 'Wizard to Import Product Accounts from Excel'

    file = fields.Binary(string='Excel File', required=True)
    file_name = fields.Char(string='File Name')

    def action_import_accounts(self):
        """Import product accounts from the uploaded Excel file."""
        if not self.file:
            raise UserError(_("Please upload an Excel file."))

        try:
            file_data = base64.b64decode(self.file)
            df = pd.read_excel(file_data, engine='openpyxl')
            create_count, skip_count, error_count = self._process_accounts(df)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Product Accounts Import Complete'),
                    'message': _(f'Added: {create_count}, Skipped: {skip_count}, Errors: {error_count}'),
                    'sticky': True,
                    'type': 'success' if error_count == 0 else 'warning',
                }
            }
        except Exception as e:
            error_logger.error(f"Failed to import product accounts: {str(e)}")
            raise UserError(_(f"Failed to import product accounts: {str(e)}"))


    def _process_accounts(self, df):
        """Process each account in the Excel file."""
        def safe_get(value, default='', to_lower=False):
            if pd.isna(value) or value is None:
                return default
            result = str(value)
            return result.lower() if to_lower else result
        
        Account = self.env['account.account'].with_context(
            tracking_disable=True,
        )
        create_count = 0
        skip_count = 0
        error_count = 0

        for index, row in df.iterrows():
            try:
                _logger.info(f"Row {index} columns: ProductID={row.get('ProductID')}, ProductDetails={row.get('ProductDetails')}, Category={row.get('Category')}, IntRate={row.get('IntRate')}, ATYPECD={row.get('ATYPECD')}")
                with self.env.cr.savepoint():
                    product_id = safe_get(row.get('ProductID'), '').strip()
                    if not product_id:
                        error_count += 1
                        error_logger.error(f"Skipping row {index}: ProductID is empty")
                        continue
                    existing_account = Account.search([('code', '=', product_id)], limit=1)
                    if existing_account:
                        _logger.info(f"Skipped account with ProductID: {product_id} at index {index} (already exists)")
                        skip_count += 1
                        continue
                    account_vals = self._prepare_account_vals(row)
                    Account.create(account_vals)
                    create_count += 1
                    _logger.info(f"Created account: {product_id} at index {index}")
            except Exception as e:
                error_count += 1
                error_logger.error(f"Processing account {row.get('ProductID', 'Unknown')} at index {index}: {str(e)}")
                continue

        return create_count, skip_count, error_count

    def _prepare_account_vals(self, row):
        """Prepare account values from Excel row."""
        def safe_get(value, default=None, to_lower=False):
            if pd.isna(value):
                return default
            return str(value).lower() if isinstance(value, str) and to_lower else str(value) if isinstance(value, str) else value

        product_id = safe_get(row.get('ProductID')).strip()
        atypecd = safe_get(row.get('ATYPECD'), to_lower=True).strip()
        category = safe_get(row.get('Category'), to_lower=True)
        int_rate = float(safe_get(row.get('IntRate'), 0.0))

        # Map ATYPECD to account_type
        type_mapping = {
            'aca': 'asset_cash',
            'acu': 'asset_current',
            'afi': 'asset_non_current',
            'cpt': 'equity',
            'lic': 'liability_current',
            'lio': 'liability_non_current',
            'psn': 'liability_current',
            'nml': 'income',  # Default to income (no INCEXP)
        }
        account_type = type_mapping.get(atypecd, 'asset_current')  # Default to asset_current

        # Map Category to account_product_type
        category_mapping = {
            'loan': 'loans',
            'loanint': 'loans_interest',
            'savings': 'savings',
            'saveint': 'savings_interest',
            'share': 'shares',
        }
        account_product_type = category_mapping.get(category, False)

        account_vals = {
            'code': product_id,
            'name': safe_get(row.get('ProductDetails'), 'Unnamed Account'),
            'account_type': account_type,
            'account_product_type': account_product_type,
            'company_id': self.env.company.id,  # Set to current company
        }

        # Set interest_rate for loans and savings
        if account_product_type in ('loans', 'savings') and int_rate > 0:
            account_vals['interest_rate'] = int_rate
            
        # Set shares for shares
        if account_product_type in ('shares', 'savings'):
            account_vals['original_shares_amount'] = 10000  # Default value for shares

        return {k: v for k, v in account_vals.items() if v is not None}