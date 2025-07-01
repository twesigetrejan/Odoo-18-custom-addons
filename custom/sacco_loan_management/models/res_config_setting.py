from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta
import logging
from ..config import (get_config, SACCO_LOANS_PAYMENTS_COLLECTION_ENDPOINT, ODOO_REGISTRATION_ENDPOINT)
import requests
import uuid
from odoo.http import request
_logger = logging.getLogger(__name__)

class ResConfigSettings(models.TransientModel):
    _inherit = ['res.config.settings', 'api.token.mixin']
    _name = 'res.config.settings'

    ins_reminder_days = fields.Integer(string="Reminder Before Days", related='company_id.ins_reminder_days', default=2, required=True, readonly=False)
    
    @api.onchange('ins_reminder_days')
    def _check_days(self):
        if self.ins_reminder_days <= 0:
            raise ValidationError(_("Installment Reminder Days must be greater than 0"))


    def action_sync_loan_payments(self):
        _logger.info("================= Starting loan payment synchronization =================")
        
        try:
            config = get_config(self.env)
            
            SACCO_NAME = self.env.user.company_id.name
            _logger.info(f"Syncing payments for SACCO: {SACCO_NAME}")

            api_url = f"{config['BASE_URL']}/{SACCO_LOANS_PAYMENTS_COLLECTION_ENDPOINT}"
            headers = self._get_request_headers()
            
            response = requests.get(api_url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            _logger.info(f"Successfully fetched data from API. Received {len(data.get('rows', []))} loan payment records.")
            
            return self._process_loan_payments(data)
            
        except requests.RequestException as e:
            _logger.error(f"Failed to fetch data from API: {str(e)}")
            return self._show_notification('Error', f'Failed to sync loan payments: {str(e)}', 'danger')

    def _process_loan_payments(self, data):
        """Process the loan payments data"""
        success_count = 0
        skip_count = 0
        error_count = 0

        if 'rows' in data:
            for loan_payment in data['rows']:
                try:
                    result = self._create_loan_payment(loan_payment)
                    if result == 'created':
                        success_count += 1
                    elif result == 'skipped':
                        skip_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    _logger.exception(f"Error creating loan payment {loan_payment.get('_id')}: {str(e)}")
                    error_count += 1

        return self._show_notification(
            'Sync Complete',
            f'Successfully processed {success_count} deposits. '
            f'Skipped {skip_count} existing deposits. '
            f'Errors encountered: {error_count}',
            'success' if error_count == 0 else 'warning'
        )

    def _get_currency(self, currency_code):
        """Get currency record from currency code"""
        currency = self.env['res.currency'].search([('name', '=', currency_code)], limit=1)
        if not currency:
            raise ValidationError(_(f"Currency {currency_code} not found in the system"))
        return currency
    
    def _create_loan_payment(self, payment_data):
        LoanPayment = self.env['sacco.loan.payments']
        Loan = self.env['sacco.loan.loan']

        _logger.info(f"Creating loan payment for member_id: {payment_data['memberId']}")

        try:
            # Check if loan payment already exists
            existing_deposit = LoanPayment.search([
                ('mongo_db_id', '=', payment_data['_id'])
            ], limit=1)
            
            if existing_deposit:
                _logger.info(f"Loan Payment already exists: {payment_data['_id']}. Skipping.")
                return 'skipped'
            
            # Get currency
            currency = self._get_currency(payment_data['currency'])
            
            # check if deposit is not approved
            if payment_data['status'] != 'Approved':
                _logger.info(f"Loan Payment is not approved: {payment_data['_id']}. Skipping.")
                return 'skipped'             
            
            # Find the corresponding loan product
            loan = Loan.search([
                ('name', '=', payment_data['loanId'])
            ], limit=1)
            
            _logger.info(f"Current loan payment for {loan.name}")

            if not loan:
                error_message = f"{payment_data['loanId']} loan doesn't exist locally, please create it!"
                _logger.error(error_message)
                raise UserError(error_message)

            # Create the payment
            payment_vals = {
                'loan_id': loan.id,
                'amount': float(payment_data['amountDeposited']),
                'currency': payment_data['currency'],
                'currency_id': currency.id,
                'payment_date': datetime.strptime(payment_data['dateCreated'], "%Y-%m-%dT%H:%M:%S.%f").date(),
                'status': 'pending' ,
                'created_by': payment_data['createdBy'],
                'mongo_db_id': payment_data['_id'],
            }

            _logger.info(f"Creating loan payment with values: {payment_vals}")
            payment = LoanPayment.create(payment_vals)
            
            payment.action_approve_payment()
            
            if not payment:
                _logger.error(f"Failed to create loan payment for mongo db id: {payment_data['_id']}")
                return None

            _logger.info(f"Loan payment created successfully. ID: {payment.id}")
            
            # Commit the transaction to ensure the payment is saved
            self.env.cr.commit()

            return 'created'
        except UserError:
            self.env.cr.rollback()
            raise
        except Exception as e:
            _logger.exception(f"Exception occurred while creating loan payment: {str(e)}")
            self.env.cr.rollback()
            return None

    def _get_base_url(self):
        base_url = request.httprequest.url_root
        return base_url.rstrip('/').replace('http://', '').replace('https://', '')  

    def _show_notification(self, title, message, type='info'):
        _logger.info(f"Showing notification - Title: {title}, Message: {message}, Type: {type}")
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

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4: