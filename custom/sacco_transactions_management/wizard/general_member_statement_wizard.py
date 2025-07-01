# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime
import requests
import logging
import binascii
import random
import time
from odoo.tools.misc import split_every
from ..config import get_config, CREATE_UPDATE_GENERAL_STATEMENT_COLLECTION_ENDPOINT

_logger = logging.getLogger(__name__)

BATCH_SIZE = 1000  # Consistent with savings module

class ResPartner(models.Model):
    _inherit = 'res.partner'

    general_statement_mongo_db_id = fields.Char('General Statement MongoDB ID', copy=False)

class GeneralMemberStatementWizard(models.TransientModel):
    _name = 'general.member.statement.wizard'
    _description = 'General Member Statement Wizard'
    _inherit = ['api.token.mixin']

    partner_id = fields.Many2one('res.partner', string='Member', required=True, domain=[('is_sacco_member', '=', True)])
    date_from = fields.Date(string='Start Date', required=True, default=lambda self: fields.Date.today().replace(year=fields.Date.today().year - 1))
    date_to = fields.Date(string='End Date', required=True, default=fields.Date.today())
    state = fields.Selection([
        ('draft', 'Draft'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('error', 'Error')
    ], default='draft', string='Status')

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for record in self:
            if record.date_from > record.date_to:
                raise UserError("Start Date must be before End Date.")

    def action_generate_statement(self):
        self.ensure_one()
        self.state = 'processing'
        try:
            options = {
                'partner_id': self.partner_id.id,
                'date': {
                    'date_from': fields.Date.to_string(self.date_from),
                    'date_to': fields.Date.to_string(self.date_to),
                    'mode': 'range',
                },
            }
            report_data = self.env['member.ledger.report.handler'].action_generate_member_statement(options)
            self.state = 'done'
            return report_data  # Return the action for PDF generation
        except Exception as e:
            self.state = 'error'
            _logger.error(f"Error generating statement: {str(e)}")
            raise

    def action_post_statement(self):
        """Post general statement to external system."""
        self.ensure_one()
        _logger.info("=========================Starting general statement create/update======================")

        # Authenticate and get the token
        token = self._get_authentication_token()
        if not token:
            return self._show_notification('Error', 'Failed to connect with external system', 'danger')

        # Prepare statement data
        statement_data = self._prepare_statement_data()

        # Post or update the statement
        return self._post_or_update_statement(statement_data, token)

    def _prepare_statement_data(self):
        """Prepare statement data for the external system."""
        options = {
            'partner_id': self.partner_id.id,
            'date': {
                'date_from': fields.Date.to_string(self.date_from),
                'date_to': fields.Date.to_string(self.date_to),
                'mode': 'range',
            },
        }
        report_data = self.env['member.ledger.report.handler'].action_generate_member_statement(options)
        statement_data = report_data.get('data', {}) if isinstance(report_data, dict) else {}

        if not statement_data.get('lines'):
            raise ValidationError(_("No transactions found for the selected period"))

        # Format transactions
        formatted_transactions = [
            {
                "date": line['date'].isoformat(),
                "savings": float(line['savings'] or 0.0),
                "savings_interest": float(line['savings_interest'] or 0.0),
                "loan": float(line['loan'] or 0.0),
                "loan_interest": float(line['loan_interest'] or 0.0),
                "shares": float(line['shares'] or 0.0),
                "share_number": float(line['share_number'] or 0.0),
                "description": line['description'],
            } for line in statement_data.get('lines', [])
        ]

        return {
            "memberId": self.partner_id.member_id,
            "memberName": self.partner_id.name,
            "startDate": self.date_from.isoformat(),
            "endDate": self.date_to.isoformat(),
            "requestDate": datetime.now().date().isoformat(),
            "product": "General",
            "productType": "General",
            "totals": {
                "savings": float(statement_data['totals']['savings']),
                "savings_interest": float(statement_data['totals']['savings_interest']),
                "loan": float(statement_data['totals']['loan']),
                "loan_interest": float(statement_data['totals']['loan_interest']),
                "shares": float(statement_data['totals']['shares']),
                "share_number": float(statement_data['totals']['share_number']),
            },
            "transactions": formatted_transactions,
            "createdBy": self.partner_id.member_id
        }

    def _generate_mongo_like_id(self):
        """Generate a 24-character hexadecimal string similar to MongoDB ObjectId."""
        timestamp = int(time.time()).to_bytes(4, byteorder='big')
        random_bytes = random.randbytes(5)
        counter = random.randint(0, 0xFFFFFF).to_bytes(3, byteorder='big')
        return binascii.hexlify(timestamp + random_bytes + counter).decode('utf-8')

    def _post_or_update_statement(self, statement_data, token):
        """Post or update the general statement to the external system."""
        headers = self._get_request_headers()
        config = get_config(self.env)

        mongo_id = self.partner_id.general_statement_mongo_db_id
        if not mongo_id:
            mongo_id = self._generate_mongo_like_id()
            self.partner_id.write({'general_statement_mongo_db_id': mongo_id})
            _logger.info(f"Generated new MongoDB-like ID: {mongo_id}")

        api_url = f"{config['BASE_URL']}/{CREATE_UPDATE_GENERAL_STATEMENT_COLLECTION_ENDPOINT}/{mongo_id}".rstrip('/')

        try:
            _logger.info(f"Posting/Updating general statement to {api_url}: {statement_data}")
            response = requests.post(api_url, headers=headers, json=statement_data)
            response.raise_for_status()

            response_data = response.json()
            if response_data and 'docId' in response_data:
                new_mongo_id = response_data['docId']
                if new_mongo_id != mongo_id:
                    self.partner_id.write({'general_statement_mongo_db_id': new_mongo_id})
                    _logger.info(f"Updated general_statement_mongo_db_id to {new_mongo_id}")

            return self._show_notification(
                'Success',
                'Successfully posted/updated general statement in external system',
                'success'
            )
        except requests.RequestException as e:
            error_msg = f"Failed to post/update general statement: {str(e)}"
            _logger.error(error_msg)
            return self._show_notification('Error', error_msg, 'danger')

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

    @api.model
    def action_mass_post_statements(self, partners):
        """Mass action to post general statements for selected SACCO members."""
        if not partners:
            raise ValidationError(_("No members selected for statement posting."))

        _logger.info(f"Starting mass statement posting for {len(partners)} members")

        success_count = 0
        for partner in partners.filtered(lambda p: p.is_sacco_member):
            try:
                wizard = self.create({
                    'partner_id': partner.id,
                    'date_from': fields.Date.today().replace(year=fields.Date.today().year - 1),
                    'date_to': fields.Date.today(),
                })
                result = wizard.action_post_statement()
                if isinstance(result, dict) and result.get('type') == 'ir.actions.client' and result['params']['type'] == 'success':
                    success_count += 1
                wizard.unlink()  # Clean up transient record
                self.env.cr.commit()
                _logger.info(f"Successfully posted statement for member {partner.member_id}")
            except Exception as e:
                self.env.cr.rollback()
                _logger.error(f"Failed to post statement for member {partner.member_id}: {str(e)}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Mass Statement Posting'),
                'message': _('%d out of %d statements posted successfully') % (success_count, len(partners)),
                'type': 'success' if success_count > 0 else 'warning',
                'sticky': False,
            }
        }

    @api.model
    def action_mass_post_all_statements(self):
        """Cron job to mass post general statements for SACCO members with transactions."""
        _logger.info("Starting cron job to post general statements for SACCO members with transactions")
        
        # Define the date range for the statements
        date_from = fields.Date.today().replace(year=fields.Date.today().year - 1)
        date_to = fields.Date.today()
        
        # Fetch all SACCO members
        partners = self.env['res.partner'].search([('is_sacco_member', '=', True)])
        if not partners:
            _logger.info("No SACCO members found to process statements.")
            return

        # Filter members with transactions in the date range
        partners_with_transactions = self.env['res.partner']
        for partner in partners:
            options = {
                'partner_id': partner.id,
                'date': {
                    'date_from': fields.Date.to_string(date_from),
                    'date_to': fields.Date.to_string(date_to),
                    'mode': 'range',
                },
            }
            report_data = self.env['member.ledger.report.handler'].action_generate_member_statement(options)
            statement_data = report_data.get('data', {}) if isinstance(report_data, dict) else {}
            if statement_data.get('lines'):  # Check if there are any transactions
                partners_with_transactions |= partner

        if not partners_with_transactions:
            _logger.info("No SACCO members with transactions found to process statements.")
            return

        # Call action_mass_post_statements to handle posting for members with transactions
        try:
            result = self.action_mass_post_statements(partners_with_transactions)
            _logger.info("Cron job completed. Check logs for details.")
            return result
        except Exception as e:
            _logger.error(f"Cron job failed: {str(e)}")
            raise