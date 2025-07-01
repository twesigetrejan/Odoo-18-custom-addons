# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import pandas as pd
import base64
import logging
import os
import re
from datetime import datetime

# Configure custom error logger
log_file_path = os.path.join(os.path.dirname(__file__), 'OdooLogs', 'chart_accounts_import_errors.log')
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
error_logger = logging.getLogger('chart_accounts_import_errors')
error_logger.setLevel(logging.ERROR)
if not error_logger.handlers:
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    error_logger.addHandler(file_handler)

_logger = logging.getLogger(__name__)

class ChartAccountsImportWizard(models.TransientModel):
    _name = 'chart.accounts.import.wizard'
    _description = 'Wizard to Import Chart of Accounts from Excel'

    file = fields.Binary(string='Excel File', required=True)
    file_name = fields.Char(string='File Name')

    def action_import_accounts(self):
        """Import chart of accounts from the uploaded Excel file."""
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
                    'title': _('Chart of Accounts Import Complete'),
                    'message': _(f'Added: {create_count}, Skipped: {skip_count}, Errors: {error_count}'),
                    'sticky': True,
                    'type': 'success' if error_count == 0 else 'warning',
                }
            }
        except Exception as e:
            error_logger.error(f"Failed to import chart of accounts: {str(e)}")
            raise UserError(_(f"Failed to import chart of accounts: {str(e)}"))

    def _process_accounts(self, df):
        """Process each account in the Excel file."""
        Account = self.env['account.account'].with_context(
            tracking_disable=True,
        )
        create_count = 0
        skip_count = 0
        error_count = 0

        for index, row in df.iterrows():
            try:
                with self.env.cr.savepoint():
                    acode = str(row.get('ACODE')).strip()
                    existing_account = Account.search([('code', '=', acode)], limit=1)
                    if existing_account:
                        _logger.info(f"Skipped account with code: {acode} at index {index} (already exists)")
                        skip_count += 1
                        continue
                    account_vals = self._prepare_account_vals(row)
                    Account.create(account_vals)
                    create_count += 1
                    _logger.info(f"Created account: {acode} at index {index}")
            except Exception as e:
                error_count += 1
                error_logger.error(f"Processing account {row.get('ACODE', 'Unknown')} at index {index}: {str(e)}")
                continue

        return create_count, skip_count, error_count

    def _prepare_account_vals(self, row):
        """Prepare account values from Excel row."""
        def safe_get(value, default=None, to_lower=False):
            if pd.isna(value):
                return default
            return str(value).lower() if isinstance(value, str) and to_lower else str(value) if isinstance(value, str) else value

        atypecd = safe_get(row.get('ATYPECD'), to_lower=True)
        incexp = safe_get(row.get('INCEXP'), to_lower=True)
        currency_cd = safe_get(row.get('CurrencyCd'), to_lower=True)

        # Map ATYPECD to account_type
        type_mapping = {
            'aca': 'asset_cash',
            'acu': 'asset_current',
            'afi': 'asset_non_current',
            'cpt': 'equity',
            'lic': 'liability_current',
            'lio': 'liability_non_current',
            'psn': 'liability_current',
        }
        account_type = type_mapping.get(atypecd, 'asset_current')  # Default to asset_current
        if atypecd == 'nml':
            account_type = 'income' if incexp == 'i' else 'expense' if incexp == 'e' else 'income'  # Default to income

        # Map CurrencyCd to currency_id
        currency_mapping = {
            'ugs': 'UGX',
            'usd': 'USD',
        }
        currency_code = currency_mapping.get(currency_cd, 'UGX')  # Default to UGX
        currency_id = self.env['res.currency'].search([('name', '=', currency_code)], limit=1).id

        account_vals = {
            'code': str(row.get('ACODE')).strip(),
            'name': safe_get(row.get('ANAME'), 'Unnamed Account'),
            'account_type': account_type,
            'company_id': self.env.company.id,  # Set to current company
        }
        if currency_id:
            account_vals['currency_id'] = currency_id

        return {k: v for k, v in account_vals.items() if v is not None}