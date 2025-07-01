from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime
from ..config import (get_config, CREATE_UPDATE_SAVINGS_STATEMENT_COLLECTION_ENDPOINT)
import requests
import logging 
import pytz
import time
import random
import binascii
from odoo.tools.misc import split_every

_logger = logging.getLogger(__name__)

# Setting batch size to process in smaller chunks
BATCH_SIZE = 1000  # This will depend on the available memory and response size

class SavingsStatementWizard(models.TransientModel):
    _name = 'sacco.savings.statement.wizard'
    _description = 'Savings Statement Wizard'
    _inherit = ['api.token.mixin']
    
    start_date = fields.Date('Start Date', required=True)
    end_date = fields.Date('End Date', required=True, default=fields.Date.today(), readonly=True)
    request_date = fields.Date('Request Date', default=fields.Date.today(), readonly=True)
    partner_id = fields.Many2one('res.partner', string='Member', domain=[('is_sacco_member', '=', 'True')], required=True)
    product_id = fields.Many2one('sacco.savings.product', string='Product', required=True, domain="[('id', 'in', available_product_ids)]")
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('error', 'Error')
    ], default='draft', string='Status')
    available_product_ids = fields.Many2many('sacco.savings.product', 
                                           compute='_compute_available_products')
    
    @api.depends('partner_id')
    def _compute_available_products(self):
        """Compute available savings products based on member's accounts"""
        for record in self:
            if record.partner_id:
                # Get all active savings accounts for the member
                savings_accounts = self.env['sacco.savings.account'].search([
                    ('member_id', '=', record.partner_id.id),
                    ('state', '!=', 'draft')
                ])
                # Get unique product IDs from those accounts
                record.available_product_ids = savings_accounts.mapped('product_id').ids
            else:
                record.available_product_ids = []
                
    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """Clear product selection when member changes"""
        self.product_id = False
    
    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Set currency when product changes"""
        if self.product_id:
            self.currency_id = self.product_id.currency_id.id
        else:
            self.currency_id = self.env.company.currency_id.id


    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for record in self:
            if record.start_date > record.end_date:
                raise ValidationError(_("Start date must be before end date"))
            
    def action_download_statement(self):
        self.ensure_one()
        self.state = 'processing'
        
        try:
            # Use read() instead of browse() for better performance
            savings_account_ids = self.env['sacco.savings.account'].search([
                ('member_id', '=', self.partner_id.id),
                ('product_id', '=', self.product_id.id),
                ('currency_id', '=', self.currency_id.id),
                ('state', '!=', 'draft'),
            ]).ids

            if not savings_account_ids:
                raise ValidationError(_("No savings accounts found for this member"))

            # Prepare report data with optimized queries
            statement_data = self._prepare_statement_data_optimized(savings_account_ids)
            
            # Prepare report context
            data = {
                'member_id': self.partner_id.member_id,
                'member_name': self.partner_id.name,
                'start_date': self.start_date,
                'end_date': self.end_date,
                'request_date': self.request_date,
                'currency': self.currency_id.name,
                'statement_data': statement_data,
            }
            
            self.state = 'done'
            return self.env.ref('savings_management.action_report_savings_statement').with_context(
                skip_report_rendering=True  # Skip immediate rendering
            ).report_action(self, data=data)

        except Exception as e:
            self.state = 'error'
            _logger.error("Error generating statement: %s", str(e))
            raise

    def _prepare_statement_data_optimized(self, account_ids):
        """Optimized method to prepare statement data with efficient queries."""
        statement_data = []
        
        # Fetch all required data in a single query
        accounts = self.env['sacco.savings.account'].browse(account_ids)
        
        for account in accounts:
            lines_data = []
            # Process transactions in chunks
            for lines_chunk in self._get_account_lines_chunked(account.id):
                formatted_chunk = self._format_account_lines_bulk(lines_chunk)
                lines_data.extend(formatted_chunk)
            
            if lines_data:
                statement_data.append({
                    'product': account.product_id.name,
                    'lines': lines_data
                })
        
        return statement_data

    def _get_account_lines_chunked(self, account_id):
        """Fetch and yield account lines in chunks for memory efficiency."""
        domain = [
            ('savings_account_id', '=', account_id),
            ('date', '>=', self.start_date),
            ('date', '<=', self.end_date),
        ]
        
        # Get total count
        total_count = self.env['sacco.journal.account.line'].search_count(domain)
        
        # Process in chunks
        for offset in range(0, total_count, BATCH_SIZE):
            lines = self.env['sacco.journal.account.line'].search(
                domain,
                limit=BATCH_SIZE,
                offset=offset,
                order="date asc, id asc"
            )
            if not lines:
                break
            yield lines

    def _format_account_lines_bulk(self, lines):
        """Bulk format account lines for better performance."""
        formatted_lines = []
        # Get selection field properly handling both function and static selection
        selection = self.env['sacco.journal.account.line']._fields['type'].selection
        if callable(selection):
            selection = selection(self.env['sacco.journal.account.line'])
        selection_dict = dict(selection)
        
        for line in lines:
            # Ensure all numeric values are properly converted to float
            try:
                opening_balance = float(line.opening_balance or 0.0)
                amount = float(line.amount or 0.0)
                closing_balance = float(line.closing_balance or 0.0)
            except (ValueError, TypeError):
                opening_balance = 0.0
                amount = 0.0
                closing_balance = 0.0

            formatted_lines.append({
                'date': fields.Date.to_string(line.date) if line.date else False,
                'type': selection_dict.get(line.type, line.type),
                'opening_balance': opening_balance,
                'credit': amount if line.type != 'withdrawal' else 0.0,
                'debit': amount if line.type == 'withdrawal' else 0.0,
                'closing_balance': closing_balance,
            })
        
        return formatted_lines

    def _chunk_data_for_report(self, data, chunk_size=1000):
        """Split report data into manageable chunks."""
        if not data.get('statement_data'):
            return [data]
        
        chunked_data = []
        for statement in data['statement_data']:
            if 'lines' in statement:
                for lines_chunk in split_every(chunk_size, statement['lines']):
                    chunk = dict(data)
                    chunk['statement_data'] = [{
                        'product': statement['product'],
                        'lines': lines_chunk
                    }]
                    chunked_data.append(chunk)
        
        return chunked_data or [data]

    def action_post_statement(self):
        """Post savings statement to external system."""
        self.ensure_one()

        _logger.info("=========================Starting savings statement create/update======================")
        
        # Authenticate and get the token
        token = self._get_authentication_token()
        if not token:
            return self._show_notification('Error', 'Failed to connect with external system', 'danger')

        # Fetch savings account and transactions
        savings_account = self._get_savings_account()
        transactions = self._get_transactions_in_batches(savings_account)
        
        if not transactions:
            return self._show_notification('Warning', 'No transactions found for the selected period', 'warning')

        # Prepare statement data
        statement_data = self._prepare_statement_data(savings_account, transactions)

        # Post or update the statement
        return self._post_or_update_statement(savings_account, statement_data, token)

    def _get_savings_account(self):
        """Retrieve savings account for the member and product."""
        savings_account = self.env['sacco.savings.account'].search([
            ('member_id', '=', self.partner_id.id),
            ('product_id', '=', self.product_id.id),
            ('currency_id', '=', self.currency_id.id),
            ('state', '!=', 'draft'),
        ], limit=1)

        if not savings_account:
            raise ValidationError(_("No active savings account found for this member and product"))

        return savings_account

    def _get_transactions_in_batches(self, savings_account):
        """Retrieve transactions in batches."""
        transactions = []
        offset = 0
        while True:
            batch = self.env['sacco.journal.account.line'].search([
                ('savings_account_id', '=', savings_account.id),
                ('date', '>=', self.start_date),
                ('date', '<=', self.end_date),
            ], limit=BATCH_SIZE, offset=offset, order='date asc, id asc')

            if not batch:
                break
            
            transactions.extend(batch)
            offset += len(batch)
        
        return transactions

    def _format_transactions(self, transactions):
        """Format transactions for external system consumption."""
        formatted_transactions = []
        
        for transaction in transactions:
            selection = transaction._fields['type'].selection
            if callable(selection):
                selection = selection(transaction)

            formatted_transactions.append({
                "date": transaction.date.isoformat() if transaction.date else None,
                "type": dict(selection).get(transaction.type, transaction.type),
                "opening_balance": float(transaction.opening_balance),
                "credit": float(transaction.amount) if transaction.type != 'withdrawal' else 0.0,
                "debit": float(transaction.amount) if transaction.type == 'withdrawal' else 0.0,
                "closing_balance": float(transaction.closing_balance)
            })
        
        return formatted_transactions

    def _prepare_statement_data(self, savings_account, transactions):
        """Prepare statement data to be sent to external system."""
        formatted_transactions = self._format_transactions(transactions)

        return {
            "memberId": self.partner_id.member_id,
            "memberName": self.partner_id.name,
            "startDate": self.start_date.isoformat() if self.start_date else None,
            "endDate": self.end_date.isoformat() if self.end_date else None,
            "requestDate": self.request_date.isoformat() if self.request_date else None,
            "product": self.product_id.name,
            'productType': 'Savings',
            "currency": self.currency_id.name,
            "currentBalance": float(savings_account.balance),
            "transactions": formatted_transactions,
            'createdBy': self.partner_id.member_id
        }


    def _generate_mongo_like_id(self):
        """Generate a 24-character hexadecimal string similar to MongoDB ObjectId"""
        # 4 bytes timestamp (8 hex chars)
        timestamp = int(time.time()).to_bytes(4, byteorder='big')
        # 5 bytes random (10 hex chars)
        random_bytes = random.randbytes(5)
        # 3 bytes counter (6 hex chars) - using random for simplicity
        counter = random.randint(0, 0xFFFFFF).to_bytes(3, byteorder='big')
        
        # Combine and convert to hex
        object_id = binascii.hexlify(timestamp + random_bytes + counter).decode('utf-8')
        return object_id
    
    def _post_or_update_statement(self, savings_account, statement_data, token):
        """Post or update the savings statement to the external system using a single endpoint."""
        
        headers = self._get_request_headers()
        config = get_config(self.env)
        
        # Use the statement_mongo_db_id if it exists, otherwise it will be handled by the endpoint
        mongo_id = savings_account.statement_mongo_db_id
        if not mongo_id:
            mongo_id = self._generate_mongo_like_id()
            savings_account.write({'statement_mongo_db_id': mongo_id})
            _logger.info(f"Generated new MongoDB-like ID for account {savings_account.name}: {mongo_id}")
            
        api_url = f"{config['BASE_URL']}/{CREATE_UPDATE_SAVINGS_STATEMENT_COLLECTION_ENDPOINT}/{mongo_id}".rstrip('/')
        
        try:
            _logger.info(f"Posting/Updating savings statement to {api_url}: {statement_data}")
            response = requests.post(api_url, headers=headers, json=statement_data)
            response.raise_for_status()
            
            response_data = response.json()
            if response_data and 'docId' in response_data:
                # Update the local statement_mongo_db_id if a new one is returned
                new_mongo_id = response_data['docId']
                if new_mongo_id != mongo_id:
                    savings_account.write({'statement_mongo_db_id': new_mongo_id})
                    _logger.info(f"Updated statement_mongo_db_id for account {savings_account.name} to {new_mongo_id}")
            
            return self._show_notification(
                'Success', 
                'Successfully posted/updated savings statement in external system',
                'success'
            )
        except requests.RequestException as e:
            error_msg = f"Failed to post/update savings statement: {str(e)}"
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