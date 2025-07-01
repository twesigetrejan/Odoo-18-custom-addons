from odoo import models, api, fields, _
from odoo.exceptions import ValidationError
import requests
import logging
from datetime import datetime
from ..config import (get_config, GET_APPROVED_INVESTMENTS_DEPOSITS_COLLECTION_ENDPOINT)

_logger = logging.getLogger(__name__)

class InvestmentDepositSync(models.Model):
    _name = 'sacco.investments.deposit.sync'
    _description = 'Investments Deposit Sync Model'
    _inherit = ['api.token.mixin']

    def _get_api_endpoint(self):
        """Get API endpoint for investment deposits"""
        config = get_config(self.env)
        return f"{config['BASE_URL']}/{GET_APPROVED_INVESTMENTS_DEPOSITS_COLLECTION_ENDPOINT}"

    def _prepare_sync_domain(self):
        """Prepare domain for sync query"""
        return {
            "status": "$text_filter:equals Approved"
        }

    def _get_currency(self, currency_code):
        """Get currency record from currency code"""
        currency = self.env['res.currency'].search([('name', '=', currency_code)], limit=1)
        if not currency:
            raise ValidationError(_(f"Currency {currency_code} not found in the system"))
        return currency

    def _get_member(self, member_id):
        """Get member record from member ID"""
        member = self.env['res.partner'].search([('member_id', '=', member_id)], limit=1)
        if not member:
            raise ValidationError(_(f"Member with ID {member_id} not found"))
        return member

    def _get_investment_product(self, product_name):
        """Get investment product record from product name"""
        product = self.env['sacco.investments.product'].search([('name', '=', product_name)], limit=1)
        if not product:
            raise ValidationError(_(f"Investment product {product_name} not found"))
        return product

    def _find_or_create_account(self, member, investment_product, currency_id):
        """Find matching account or create new one with correct currency"""
        account = self.env['sacco.investments.account'].search([
            ('member_id', '=', member.id),
            ('product_id', '=', investment_product.id),
            ('currency_id', '=', currency_id),
            ('state', '=', 'active')
        ], limit=1)
        
        if not account:
            account = self._create_investment_account(member, investment_product, currency_id)
            
        return account

    def _create_investment_account(self, member, investment_product, currency_id):
        """Create a new investment account"""
        return self.env['sacco.investments.account'].create({
            'member_id': member.id,
            'product_id': investment_product.id,
            'currency_id': currency_id,
            'state': 'active'
        })

    def _create_transaction(self, account_id, amount, currency_id, transaction_date):
        """Create an investment transaction"""
        transaction = self.env['sacco.investments.transaction'].create({
            'investments_account_id': account_id,
            'transaction_type': 'deposit',
            'amount': amount,
            'currency_id': currency_id,
            'transaction_date': transaction_date,
            'status': 'pending'
        })
        return transaction

    def _process_deposit_record(self, row):
        """Process a single deposit record"""
        try:
            # Check if deposit already exists
            if self.env['sacco.investments.transaction'].search([('ref_id', '=', row.get('refID'))]):
                return True, "Deposit already exists"

            # Get required records
            currency = self._get_currency(row.get('currency'))
            member = self._get_member(row.get('memberId'))
            investment_product = self._get_investment_product(row.get('investmentProduct'))
            
            # Find or create investment account
            account = self._find_or_create_account(member, investment_product, currency.id)
            
            # Parse date
            deposit_date = datetime.strptime(row.get('dateCreated', ''), '%Y-%m-%dT%H:%M:%S.%f')

            # Create transaction
            transaction = self.env['sacco.investments.transaction'].create({
                'investments_account_id': account.id,
                'transaction_type': 'deposit',
                'amount': float(row.get('amountDeposited', 0)),
                'status': 'pending',
                'currency_id': currency.id,
                'transaction_date': deposit_date.date(),
                'ref_id': row.get('refID', ''),
                'mongo_db_id': row.get('_id', ''),
                'created_by': row.get('createdBy', '')
            })

            # Confirm transaction
            transaction.action_confirm_transaction()
            
            return True, None
            
        except Exception as e:
            return False, str(e)

    @api.model
    def sync_deposits(self):
        """Sync investment deposits from external API"""
        token = self._get_authentication_token()
        if not token:
            return self._show_notification('Error', 'Failed to obtain authentication token', 'danger')

        headers = self._get_request_headers()

        try:
            response = requests.post(
                self._get_api_endpoint(),
                headers=headers,
                json=self._prepare_sync_domain()
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            return self._show_notification('Error', f'Failed to fetch data from API: {str(e)}', 'danger')

        success_count = 0
        error_count = 0
        errors = []

        for row in data.get('rows', []):
            _logger.info(f'{row}')
            success, error = self._process_deposit_record(row)
            if success:
                success_count += 1
            else:
                error_count += 1
                errors.append(f"Error processing deposit {row.get('refID', 'Unknown')}: {error}")

        # Log errors
        for error in errors:
            _logger.error(error)

        return self._show_notification(
            'Sync Complete',
            f'Successfully processed {success_count} deposits. Errors encountered: {error_count}',
            'success' if error_count == 0 else 'warning'
        )

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