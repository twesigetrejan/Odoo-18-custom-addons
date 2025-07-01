from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from ..config import (get_config, CREATE_UPDATE_INVESTMENTS_STATEMENT_COLLECTION_ENDPOINT)
from datetime import datetime
import logging
import requests
import time
import random
import binascii

_logger = logging.getLogger(__name__)

class InvestmentsStatementWizard(models.TransientModel):
    _name = 'sacco.investments.statement.wizard'
    _description = 'Investments Statement Wizard'
    _inherit = ['api.token.mixin']
    
    start_date = fields.Date('Start Date', required=True)
    end_date = fields.Date('End Date', required=True, default=fields.Date.today(), readonly=True)
    request_date = fields.Date('Request Date', default=fields.Date.today(), readonly=True)
    partner_id = fields.Many2one('res.partner', string='Member', 
                                domain=[('is_sacco_member', '=', 'True')], required=True)
    product_id = fields.Many2one('sacco.investments.product', string='Investment Product', required=True, domain="[('id', 'in', available_product_ids)]")
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, store=True)
    available_product_ids = fields.Many2many('sacco.investments.product', 
                                           compute='_compute_available_products')
    
    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for record in self:
            if record.start_date > record.end_date:
                raise ValidationError(_("Start date must be before end date"))
            
            # earliest_account = self.env['sacco.investments.account'].search([
            #     ('member_id', '=', record.partner_id.id),
            # ], order='initial_deposit_date asc', limit=1)
            
    @api.depends('partner_id')
    def _compute_available_products(self):
        """Compute available investments products based on member's accounts"""
        for record in self:
            if record.partner_id:
                # Get all active investments accounts for the member
                investments_accounts = self.env['sacco.investments.account'].search([
                    ('member_id', '=', record.partner_id.id),
                    ('state', '!=', 'draft')
                ])
                # Get unique product IDs from those accounts
                record.available_product_ids = investments_accounts.mapped('product_id').ids
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
    
    def action_download_statement(self):
        self.ensure_one()
        
        investment_accounts = self.env['sacco.investments.account'].search([
            ('member_id', '=', self.partner_id.id),
            ('product_id', '=', self.product_id.id),
            ('currency_id', '=', self.currency_id.id),
            ('state', '!=', 'draft'),
        ])
        
        if not investment_accounts:
            raise ValidationError(_("No investment accounts found for this member"))
        
        statement_data = []
        for account in investment_accounts:
            lines = self.env['sacco.investment.account.journal.line'].search([
                ('investment_account_id', '=', account.id),
                ('date', '>=', self.start_date),
                ('date', '<=', self.end_date),
            ], order="date asc, id asc")
            
            if lines:
                formatted_lines = []
                for line in lines:
                    selection = line._fields['type'].selection
                    if callable(selection):
                        selection = selection(line)
                    
                    formatted_lines.append({
                        'date': fields.Date.to_string(line.date),
                        'type': dict(selection).get(line.type, line.type),
                        'opening_cash_balance': float(line.opening_cash_balance),
                        'opening_investment_balance': float(line.opening_investment_balance),
                        'amount': float(line.amount),
                        'closing_cash_balance': float(line.closing_cash_balance),
                        'closing_investment_balance': float(line.closing_investment_balance),
                    })
                
                statement_data.append({
                    'product': account.product_id.name,
                    'lines': formatted_lines,
                    'cash_balance': float(account.cash_balance),
                    'investment_balance': float(account.investment_balance),
                    'total_profit': float(account.total_profit)
                })
                
        data = {
            'member_id': self.partner_id.member_id,
            'member_name': self.partner_id.name,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'request_date': self.request_date,
            'currency': self.currency_id.name,
            'statement_data': statement_data,
        }
        
        return self.env.ref('investments_management.action_report_investments_statement').report_action(self, data=data)


    def _show_notification(self, title, message, type='info'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'type': type,
                'sticky': False,
            }
        }

    def action_post_statement(self):
        """Post investments statement to external system"""
        self.ensure_one()

        _logger.info("=========================Starting investments statement post=========================")
        
        # Authenticate and get the token
        token = self._get_authentication_token()
        if not token:
            return self._show_notification('Error', 'Failed to connect with external system', 'danger')

        # Fetch investments account and transactions
        investments_account = self._get_investments_account()
        investments_account.action_refresh_journal_lines()
        transactions = self._get_transactions(investments_account)
        
        if not transactions:
            return self._show_notification('Warning', 'No transactions found for the selected period', 'warning')

        # Prepare statement data
        statement_data = self._prepare_statement_data(investments_account, transactions)

        # Post or update the statement
        return self._post_or_update_statement(investments_account, statement_data, token)


    def _get_investments_account(self):
        """Retrieve investments account for the member and product."""
        investments_account = self.env['sacco.investments.account'].search([
            ('member_id', '=', self.partner_id.id),
            ('product_id', '=', self.product_id.id),
            ('currency_id', '=', self.currency_id.id),
            ('state', '!=', 'draft'),
        ], limit=1)

        if not investments_account:
            raise ValidationError(_("No active investments account found for this member and product"))

        return investments_account


    def _get_transactions(self, investments_account):
        """Retrieve transactions for the investments account within the date range."""
        transactions = self.env['sacco.investment.account.journal.line'].search([
            ('investment_account_id', '=', investments_account.id),
            ('date', '>=', self.start_date),
            ('date', '<=', self.end_date),
        ], order='date asc, id asc')

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
                "opening_cash_balance": float(transaction.opening_cash_balance),
                "opening_investment_balance": float(transaction.opening_investment_balance),
                "amount": float(transaction.amount),
                "closing_cash_balance": float(transaction.closing_cash_balance),
                "closing_investment_balance": float(transaction.closing_investment_balance)
            })
        
        return formatted_transactions


    def _prepare_statement_data(self, investments_account, transactions):
        """Prepare statement data to be sent to external system."""
        formatted_transactions = self._format_transactions(transactions)

        return {
            "memberId": self.partner_id.member_id,
            "memberName": self.partner_id.name,
            "startDate": self.start_date.isoformat() if self.start_date else None,
            "endDate": self.end_date.isoformat() if self.end_date else None,
            "requestDate": self.request_date.isoformat() if self.request_date else None,
            "product": self.product_id.name,
            'productType': 'Investments',
            "currency": self.currency_id.name,
            "cashBalance": float(investments_account.cash_balance),
            "investmentBalance": float(investments_account.investment_balance),
            "totalProfit": float(investments_account.total_profit),
            "transactions": formatted_transactions,
            "createdBy": self.partner_id.member_id
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

    def _post_or_update_statement(self, investments_account, statement_data, token):
        """Post or update the investments statement to the external system using a single endpoint."""
        headers = self._get_request_headers()
        config = get_config(self.env)
        
        # Use the statement_mongo_db_id if it exists, otherwise generate a new one
        mongo_id = investments_account.statement_mongo_db_id
        if not mongo_id:
            mongo_id = self._generate_mongo_like_id()
            investments_account.write({'statement_mongo_db_id': mongo_id})
            _logger.info(f"Generated new MongoDB-like ID for account {investments_account.name}: {mongo_id}")
        
        api_url = f"{config['BASE_URL']}/{CREATE_UPDATE_INVESTMENTS_STATEMENT_COLLECTION_ENDPOINT}/{mongo_id}".rstrip('/')
        
        try:
            _logger.info(f"Posting/Updating investments statement to {api_url}: {statement_data}")
            response = requests.post(api_url, headers=headers, json=statement_data)
            response.raise_for_status()
            
            response_data = response.json()
            if response_data and 'docId' in response_data:
                # Update the local statement_mongo_db_id if a new one is returned
                new_mongo_id = response_data['docId']
                if new_mongo_id != mongo_id:
                    investments_account.write({'statement_mongo_db_id': new_mongo_id})
                    _logger.info(f"Updated statement_mongo_db_id for account {investments_account.name} to {new_mongo_id}")
            
            return self._show_notification(
                'Success', 
                'Successfully posted/updated investments statement in external system',
                'success'
            )
        except requests.RequestException as e:
            error_msg = f"Failed to post/update investments statement: {str(e)}"
            _logger.error(error_msg)
            return self._show_notification('Error', error_msg, 'danger')

