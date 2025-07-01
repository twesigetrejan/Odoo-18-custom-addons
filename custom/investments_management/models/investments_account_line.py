from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date
import logging

_logger = logging.getLogger(__name__)

class InvestmentsAccountLine(models.Model):
    _name = 'sacco.investments.account.line'
    _description = 'SACCO Investments Account Line'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('ID', default='/', copy=False)
    investments_transaction_id = fields.Many2one('sacco.investments.transaction', string='Transaction', 
                                               required=True, domain=[('status', '=', 'confirmed')], 
                                               readonly=True)
    investments_account_id = fields.Many2one(related='investments_transaction_id.investments_account_id', 
                                           string='Investments Account', required=True, 
                                           ondelete='cascade', store=True)
    date = fields.Date(related='investments_transaction_id.transaction_date',  
                      string='Date', required=True, readonly=True, store=True)
    amount = fields.Float(related='investments_transaction_id.amount', 
                         string='Amount', required=True, readonly=True, 
                         store=True, digits='Account')
    type = fields.Selection(related='investments_transaction_id.transaction_type', 
                          string="Type", required=True, readonly=True, store=True)
    
    # Cash balance tracking
    opening_cash_balance = fields.Float('Opening Cash Balance', readonly=True, store=True, digits='Account',
                                      help="Opening cash balance before transaction")
    closing_cash_balance = fields.Float('Closing Cash Balance', readonly=True, store=True, digits='Account',
                                      help="Closing cash balance after transaction")
    
    # Investment balance tracking
    opening_investment_balance = fields.Float('Opening Investment Balance', readonly=True, store=True, digits='Account',
                                           help="Opening investment balance before transaction")
    closing_investment_balance = fields.Float('Closing Investment Balance', readonly=True, store=True, digits='Account',
                                           help="Closing investment balance after transaction")
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry', copy=False)
    
    @api.model
    def create(self, vals):
        if vals.get('investments_transaction_id'):
            transaction = self.env['sacco.investments.transaction'].browse(vals['investments_transaction_id'])
            vals['name'] = transaction.name or '/'
            
        investments_account = self.env['sacco.investments.account'].browse(vals['investments_account_id'])
        last_line = self.search([('investments_account_id', '=', investments_account.id)], 
                               order='date desc, id desc', limit=1)
        
        # Set initial balances
        if last_line:
            vals['opening_cash_balance'] = last_line.closing_cash_balance
            vals['opening_investment_balance'] = last_line.closing_investment_balance
        else:
            vals['opening_cash_balance'] = 0
            vals['opening_investment_balance'] = 0
            investments_account.initial_deposit_date = vals['date']

        # Calculate closing balances based on transaction type
        transaction_type = vals['type']
        amount = vals['amount']
        
        # Initialize closing balances with opening balances
        vals['closing_cash_balance'] = vals['opening_cash_balance']
        vals['closing_investment_balance'] = vals['opening_investment_balance']
        
        # Update balances based on transaction type
        if transaction_type in ['deposit', 'interest', 'dividend', 'investment_sale']:
            vals['closing_cash_balance'] = vals['opening_cash_balance'] + amount
            if transaction_type == 'investment_sale':
                vals['closing_investment_balance'] = vals['opening_investment_balance'] - amount
                
        elif transaction_type in ['withdrawal', 'fee']:
            vals['closing_cash_balance'] = vals['opening_cash_balance'] - amount
            
        elif transaction_type == 'investment_purchase':
            vals['closing_cash_balance'] = vals['opening_cash_balance'] - amount
            vals['closing_investment_balance'] = vals['opening_investment_balance'] + amount
        
        if investments_account.update_statement:
            investments_account.update_statement = False
        
        return super(InvestmentsAccountLine, self).create(vals)
    
    @api.onchange('investments_transaction_id')
    def _onchange_investments_transaction_id(self):
        if self.investments_transaction_id:
            self.name = self.investments_transaction_id.name or '/'
            
    def get_account_move_vals(self):
        vals = {
            'date': self.date,
            'ref': self.name or 'Transaction',
            'journal_id': self.investments_account_id.product_id.investments_product_journal_id and self.investments_account_id.product_id.investments_product_journal_id.id or False,
            'company_id': self.investments_account_id.product_id.investments_product_journal_id and self.investments_account_id.product_id.investments_product_journal_id.company_id and self.investments_account_id.product_id.investments_product_journal_id.company_id.id or False,
        }
        return vals
    
    def get_transaction_lines(self):
        """Get the transaction line values based on transaction type"""
        _logger.info("Starting get_transaction_lines for transaction: %s", self.name)
        product = self.investments_account_id.product_id
        
        # Validate required accounts
        if self.type in ['investment_purchase', 'investment_sale'] and not product.investments_product_account_id:
            _logger.error("Investment Account not configured for product: %s", product.name)
            raise ValidationError(_("Investment Account not configured!"))
        if not product.investments_product_cash_account_id:
            _logger.error("Cash Account not configured for product: %s", product.name)
            raise ValidationError(_("Cash Account not configured!"))

        partner_id = self.investments_account_id.member_id.id
        cash_account_id = product.investments_product_cash_account_id
        investment_account_id = product.investments_product_account_id
        
        _logger.debug("Transaction type: %s, Amount: %s, Partner ID: %s", self.type, self.amount, partner_id)
        _logger.debug("Cash Account: %s (ID: %s), Investment Account: %s (ID: %s)", 
                    cash_account_id.name, cash_account_id.id, 
                    investment_account_id.name, investment_account_id.id)
        
        # Handle different transaction types
        if self.type == 'investment_purchase':
            account_id = investment_account_id
            vals = {
                'partner_id': partner_id or False,
                'account_id': account_id.id,
                'debit': self.amount,
                'name': f"Purchase: {self.name}",
                'date_maturity': self.date,
                'member_id': self.investments_account_id.member_id.member_id if self.investments_account_id.member_id and self.investments_account_id.member_id.member_id else False,
            }
                
        elif self.type == 'investment_sale':
            account_id = investment_account_id
            vals = {
                'partner_id': partner_id or False,
                'account_id': account_id.id,
                'credit': self.amount,
                'name': f"Sale: {self.name}",
                'date_maturity': self.date,
                'member_id': self.investments_account_id.member_id.member_id if self.investments_account_id.member_id and self.investments_account_id.member_id.member_id else False,
            }
                
        else:  # deposit, interest, withdrawal, dividend, fee
            account_id = cash_account_id
            if self.type in ['deposit', 'dividend', 'interest']:
                debit_credit = 'credit'  
            else:
                debit_credit = 'debit'  
                
            vals = {
                'partner_id': partner_id or False,
                'account_id': account_id.id,
                debit_credit: self.amount,
                'name': self.name or '/',
                'date_maturity': self.date,
                'member_id': self.investments_account_id.member_id.member_id if self.investments_account_id.member_id and self.investments_account_id.member_id.member_id else False,
            }
        
        _logger.info("Transaction line vals: %s", vals)
        return vals
    
    def get_partner_lines(self):
        """Get the partner line values based on transaction type"""
        _logger.info("Starting get_partner_lines for transaction: %s", self.name)
        partner = self.investments_account_id.member_id
        product = self.investments_account_id.product_id
        partner_id = partner.id if partner else False
        cash_account_id = product.investments_product_cash_account_id.id if product.investments_product_cash_account_id else None
        investment_account_id = product.investments_product_account_id.id if product.investments_product_account_id else None

        _logger.debug("Partner ID: %s, Cash Account ID: %s, Investment Account ID: %s", 
                    partner_id, cash_account_id, investment_account_id)

        def create_line(account_id, amount_key, amount, name):
            if not account_id:
                raise ValidationError(_("No valid account configured for this transaction. Please check the receiving account configuration."))
            _logger.debug("Creating line - Account ID: %s, Amount Key: %s, Amount: %s, Name: %s", 
                        account_id, amount_key, amount, name)
            vals = {
                'partner_id': partner_id,
                'account_id': account_id,
                amount_key: amount,
                'name': name,
                'date_maturity': self.date,
            }
            account = self.env['account.account'].browse(account_id)
            if account.requires_member and account.account_product_type == 'investments':
                vals['investments_account_id'] = self.investments_account_id.id
                _logger.debug("Linked investments_account_id: %s to partner line", self.investments_account_id.id)
            return vals

        if self.type == 'investment_purchase':
            vals = create_line(cash_account_id, 'credit', self.amount, f"Purchase: {self.name}")
        elif self.type == 'investment_sale':
            vals = create_line(cash_account_id, 'debit', self.amount, f"Sale: {self.name}")
        else:  # deposit, interest, withdrawal, dividend, fee
            amount_key = 'debit' if self.type in ['deposit', 'dividend', 'interest'] else 'credit'
            account_id = self.investments_transaction_id.receipt_account
            if not account_id:
                raise ValidationError(_("No receipt account specified for the transaction. Please configure a receiving account with a valid accounting account."))
            vals = create_line(account_id.id, amount_key, self.amount, self.name or '/')

        _logger.info("Partner line vals: %s", vals)
        return vals
    
    def post_entry(self):
        """Post the accounting entry for the transaction"""
        # Skip journal entries for certain transaction types if configured
        if self.type == 'withdrawal':
            return
            
        account_move_val = self.get_account_move_vals()
        account_move = self.env['account.move'].create(account_move_val)
        
        if account_move:
            move_lines = []
            # Add partner lines
            move_lines.append((0, 0, self.get_partner_lines()))
            # Add transaction lines
            move_lines.append((0, 0, self.get_transaction_lines()))
            
            account_move.line_ids = move_lines
            self.journal_entry_id = account_move and account_move.id or False
            
            if account_move.state == 'draft':
                account_move.action_post()  
