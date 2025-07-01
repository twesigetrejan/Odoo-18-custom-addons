from odoo import models, api, fields, _
from odoo.exceptions import ValidationError
import requests
import logging
from datetime import datetime
from ..config import (get_config, GET_APPROVED_SAVINGS_DEPOSITS_COLLECTION_ENDPOINT)

_logger = logging.getLogger(__name__)

class SavingsDepositSync(models.Model):
    _name = 'sacco.savings.deposit.sync'
    _description = 'Savings Deposit Sync Model'
    _inherit = ['api.token.mixin']

    def _get_api_endpoint(self):
        """Get API endpoint for savings deposits"""
        config = get_config(self.env)
        _logger.info(f"BASE URL===== {config['BASE_URL']}")
        return f"{config['BASE_URL']}/{GET_APPROVED_SAVINGS_DEPOSITS_COLLECTION_ENDPOINT}"
    

    def _get_latest_local_record_date(self):
        """Get the write_date of the most recently updated local record."""
        Deposit = self.env['savings.transaction']
        latest_record = Deposit.search([
            ('status', '=', 'confirmed'),
            ('transaction_type', '=', 'deposit'),
            ('mongo_db_id', '!=', False),
            ('mongo_db_id', '!=', ''),
        ], order='write_date desc', limit=1)
        
        if not latest_record:
            return None
            
        return latest_record.write_date 
    
    def _prepare_sync_domain(self):
        """Prepare domain for sync query"""
        domain = {"status": "$text_filter:equals Approved"}
        last_updated = self._get_latest_local_record_date()
        
        # Only process date if last_updated is not None
        if last_updated:
            _logger.info(f"Latest Record last updated {last_updated}")
            date_str = last_updated.isoformat()
            _logger.info(f"Latest Record last updated {date_str}")
            domain["lastUpdated"] = f"$date_filter:gt 2024-10-30T09:19:49.884"
            # domain["lastUpdated"] = f"$date_filter:gt {date_str}"
        else:
            _logger.info("No previous records found - will sync all approved deposits")
            
        return domain

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

    def _find_or_create_account(self, member, savings_product, currency_id):
        """Find matching account or create new one with correct currency"""
        account = self.env['sacco.savings.account'].search([
            ('member_id', '=', member.id),
            ('product_id', '=', savings_product.id),
            ('currency_id', '=', currency_id),
            ('state', '=', 'active')
        ], limit=1)

        if not account:
            account = self.env['sacco.savings.account'].create({
                'member_id': member.id,
                'product_id': savings_product.id,
                'currency_id': currency_id,
                'state': 'active'
            })

        return account

    def _process_deposit_record(self, row):
        """Process a single deposit record"""
        try:
            # Check if deposit already exists
            _logger.info("Checking if deposit already exists")
            if self.env['savings.transaction'].search([('ref_id', '=', row.get('refID'))]):
                return True, "Deposit already exists"

            _logger.info("Processing deposit record")
            # Get required records
            currency = self._get_currency(row.get('currency'))
            member = self._get_member(row.get('memberId'))
            savings_product = self.env['sacco.savings.product'].search([('name', '=', row.get('savingsProduct'))], limit=1)

            if not savings_product:
                raise ValidationError(_(f"Savings product {row.get('savingsProduct')} not found"))

            # Find or create savings account
            account = self._find_or_create_account(member, savings_product, currency.id)

            # Parse date
            deposit_date = datetime.strptime(row.get('dateCreated', ''), '%Y-%m-%dT%H:%M:%S.%f')

            
            _logger.info(f"Processing deposit {row.get('refID')} for member {member.name}")
            # Create transaction
            transaction = self.env['savings.transaction'].create({
                'savings_account_id': account.id,
                'transaction_type': 'deposit',
                'amount': float(row.get('amountDeposited', 0)),
                'status': 'pending',
                'currency_id': currency.id,
                'transaction_date': deposit_date.date(),
                'ref_id': row.get('refID', ''),
                'mongo_db_id': row.get('_id', ''),
                'created_by': row.get('createdBy', '')
            })

            _logger.info(f" AFter Processing deposit {row.get('refID')} for member {member.name}")
            # Confirm transaction
            transaction.action_confirm_transaction()
            
            _logger.info(f" AFter Confirming deposit {row.get('refID')} for member {member.name}")

            return True, None

        except Exception as e:
            return False, str(e)

    def _fetch_deposits_from_api(self, headers, domain, page=1, limit=1000):
        """Fetch deposits from API with pagination"""
        try:
            params = {
                'page': page,
                'limit': limit
            }
            
            _logger.info(f"Fetching deposits - Page: {page}, Limit: {limit}")
            response = requests.post(
                self._get_api_endpoint(),
                headers=headers,
                json=domain,
                params=params
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            _logger.error(f"Failed to fetch deposits from API: {str(e)}")
            return None

    def _fetch_all_deposits(self, headers, domain):
        """Fetch all deposits using pagination"""
        all_deposits = []
        page = 1
        limit = 1000
        
        while True:
            data = self._fetch_deposits_from_api(headers, domain, page, limit)
            if not data or not data.get('rows'):
                break
                
            current_deposits = data.get('rows', [])
            all_deposits.extend(current_deposits)
            
            if len(current_deposits) < limit:
                break
                
            _logger.info(f"Fetched {len(current_deposits)} deposits from page {page}")
            page += 1
            
        _logger.info(f"Total deposits fetched: {len(all_deposits)}")
        return {'rows': all_deposits}
    
    @api.model
    def sync_deposits(self):
        """Sync savings deposits from external API with pagination"""
        _logger.info("Starting deposits sync with pagination")
        
        sync_record = self.search([], limit=1)
        if not sync_record:
            sync_record = self.create({})
            
        token = self._get_authentication_token()
        if not token:
            return self._show_notification('Error', 'Failed to obtain authentication token', 'danger')

        headers = self._get_request_headers()
        domain = self._prepare_sync_domain()
        _logger.info("Domain for sync query: %s", domain)

        try:
            data = self._fetch_all_deposits(headers, domain)
        except Exception as e:
            return self._show_notification('Error', f'Failed to fetch data from API: {str(e)}', 'danger')

        success_count = 0
        error_count = 0
        errors = []

        for row in data.get('rows', []):
            success, error = self._process_deposit_record(row)
            if success:
                success_count += 1
            else:
                error_count += 1
                errors.append(f"Error processing deposit {row.get('refID', 'Unknown')}: {error}")

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
