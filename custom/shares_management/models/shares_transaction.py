from odoo import models, api, fields, _
from odoo.exceptions import ValidationError
from datetime import date
import logging

_logger = logging.getLogger(__name__)

class SharesTransaction(models.Model):
    _name = 'shares.transaction'
    _description = 'Shares Transaction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char('ID', default='/', copy=False)
    shares_account_id = fields.Many2one('sacco.shares.account', string='Shares Account')
    transaction_type = fields.Selection(
        [
            ('deposit', 'Deposit'),
         ], string="Transaction Type", required=True, default='deposit'
    )
    amount = fields.Float(string="Amount", required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', compute='_compute_currency', store=True)
    transaction_date = fields.Date(string="Transaction Date", required=True, default=fields.Date.context_today)
    status = fields.Selection(
        [
            ('pending', 'Pending'),
            ('confirmed', 'Confirmed'),
            ('rejected', 'Rejected'),
         ], string='Status', default='pending'
    )
    member_id = fields.Many2one('res.partner', string='Member', required=True, domain=[('is_sacco_member', '=', True)])
    product_id = fields.Many2one('sacco.shares.product', string='Product', required=True)
    has_shares_account = fields.Boolean(compute='_compute_has_shares_account', store=True)
    account_status = fields.Char(compute='_compute_has_shares_account', store=True)
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    receiving_account_id = fields.Many2one('sacco.receiving.account', string='Receiving Account',
        help="The account that received this deposit")
    receipt_account = fields.Many2one('account.account', string='Receipt Account')
    original_shares_product_account_id = fields.Many2one('account.account', string='Original Shares Product Account')
    current_shares_product_account_id = fields.Many2one('account.account', string='Current Shares Product Account')
    number_of_shares = fields.Float(string='Number of Shares', compute='_compute_number_of_shares', store=True)
    general_transaction_id = fields.Many2one('sacco.general.transaction', string='General Transaction', ondelete='restrict')

    # MIS fields
    ref_id = fields.Char(string='Reference ID')
    mongo_db_id = fields.Char(string='Mongo DB ID', readonly=True)
    created_by = fields.Char(string='Created By')
        
    @api.model
    def create(self,vals):
        vals.update({
                    'name':self.env['ir.sequence'].next_by_code('shares.transaction') or '/'
                })
        return super(SharesTransaction,self).create(vals)    
    
    @api.constrains('amount')        
    def check_amount(self):                
        for line in self:
            if line.amount <= 0:
                raise ValidationError(_("Amount must be greater than zero."))
    
    def action_confirm_transaction(self):
        self.ensure_one()
        
        # First check if shares account exists
        account = self.env['sacco.shares.account'].search([
            ('member_id', '=', self.member_id.id),
            ('product_id', '=', self.product_id.id),
            ('state', '=', 'active'),
        ], limit=1)
        
        if not account:                
            # Create new shares account
            account = self.env['sacco.shares.account'].create({
                'member_id': self.member_id.id,
                'product_id': self.product_id.id,
                'currency_id': self.product_id.currency_id.id,
                'state': 'active',
            })
        
        self.shares_account_id = account.id
               
        if not self.shares_account_id.product_id.original_shares_product_journal_id:
            raise ValidationError(_("Please Select Payment Journal for the Particular Product !!!"))
        
        try:            
            if self.status != 'confirmed':
                self.status = 'confirmed'
                self.post_entry()
            return True
            
        except Exception as e:
            _logger.error(f"Error confirming transaction {self.name}: {str(e)}")
            raise

        
    def action_reject_transaction(self):
        self.status = 'rejected'
                
    @api.depends('product_id')
    def _compute_currency(self):
        for record in self:
            record.currency_id = record.product_id.currency_id if record.product_id else self.env.company.currency_id
            
    @api.depends('member_id', 'product_id')
    def _compute_has_shares_account(self):
        for record in self:
            if record.member_id and record.product_id:
                account = self.env['sacco.shares.account'].search([
                    ('member_id', '=', record.member_id.id),
                    ('product_id', '=', record.product_id.id),
                    ('state', '=', 'active'),
                ], limit=1)
                record.has_shares_account = bool(account)
                record.account_status = "Account Id: " + account.name if account else "No Active Account - Will be created on confirmation"
            else:
                record.has_shares_account = False
                record.account_status = "Select Member and Product"


    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id and self.product_id.default_receiving_account_id:
            self.receiving_account_id = self.product_id.default_receiving_account_id.id
            

    @api.onchange('receiving_account_id')
    def _onchange_receiving_account_id(self):
        """Update receipt_account when receiving_account_id changes"""
        if self.receiving_account_id:
            self.receipt_account = self.receiving_account_id.account_id
        else:
            self.receipt_account = False
            
    @api.depends('amount', 'product_id')
    def _compute_number_of_shares(self):
        for record in self:
            if record.amount and record.product_id.current_shares_amount > 0:
                record.number_of_shares = record.amount / record.product_id.current_shares_amount
            else:
                record.number_of_shares = 0.0
            

    def get_account_move_vals(self):
        vals={
            'date':self.transaction_date,
            'ref':self.name or 'Transaction',
            'journal_id':self.shares_account_id.product_id.original_shares_product_journal_id and self.shares_account_id.product_id.original_shares_product_journal_id.id or False,
            'company_id':self.shares_account_id.product_id.original_shares_product_journal_id and self.shares_account_id.product_id.original_shares_product_journal_id.company_id and self.shares_account_id.product_id.original_shares_product_journal_id.company_id.id or False,
        }
        return vals
    
    
    def post_entry(self):
        account_move_val = self.get_account_move_vals()
        account_move_id = self.env['account.move'].create(account_move_val)
        vals=[]
        
        # Calculate the number of shares being purchased
        # The amount is the total to be paid and we need to divide by current share price
        product = self.shares_account_id.product_id
        current_share_price = product.current_shares_amount
        original_share_price = product.original_shares_amount
        number_of_shares = self.amount / current_share_price
        
        # 1. Debit the receiving account (total payment)
        receiving_line = {
            'partner_id': self.shares_account_id.member_id and self.shares_account_id.member_id.id or False,
            'account_id': self.receipt_account and self.receipt_account.id or False,
            'debit': self.amount,
            'name': f"{self.transaction_type or '/'} - Purchase of {number_of_shares} shares",
            'date_maturity': self.transaction_date,
        }
        
        vals.append((0, 0, receiving_line))
        
        # 2. Credit the original shares account (number of shares * original share value)
        original_shares_amount = number_of_shares * original_share_price
        original_shares_line = {
            'partner_id': self.shares_account_id.member_id and self.shares_account_id.member_id.id or False,
            'account_id': product.original_shares_product_account_id and product.original_shares_product_account_id.id or False,
            'credit': original_shares_amount,
            'name': f"{self.transaction_type or '/'} - Original shares value",
            'date_maturity': self.transaction_date,
            'member_id': self.shares_account_id.member_id.member_id if self.shares_account_id.member_id and self.shares_account_id.member_id.member_id else False,
        }
        
        vals.append((0, 0, original_shares_line))
        
        # 3. Credit the shares premium account (number of shares * (current - original) share value)
        premium_amount = number_of_shares * (current_share_price - original_share_price)
        if premium_amount > 0:
            premium_line = {
                'partner_id': self.shares_account_id.member_id and self.shares_account_id.member_id.id or False,
                'account_id': product.current_shares_product_account_id and product.current_shares_product_account_id.id or False,
                'credit': premium_amount,
                'name': f"{self.transaction_type or '/'} - Shares premium",
                'date_maturity': self.transaction_date,
            }
        
            vals.append((0, 0, premium_line))
        
        account_move_id.line_ids = vals
        self.journal_entry_id = account_move_id and account_move_id.id or False
        
        if account_move_id.state == 'draft':
            account_move_id.action_post()    
            self.shares_account_id.action_refresh_journal_lines()
            

    def unlink(self):
        for shares_transaction in self:
            if shares_transaction.journal_entry_id:
                raise ValidationError(_('Cannot delete transaction with associated journal entries. Please set the entry to draft then delete it'))
            if shares_transaction.general_transaction_id:
                raise ValidationError(_('Cannot delete transaction linked to a general transaction. Please unlink it first.'))
            # Store the associated shares account for refreshing journal lines
            account = shares_transaction.shares_account_id
            # Perform the deletion
            super(SharesTransaction, shares_transaction).unlink()
            # Refresh journal lines for the associated account
            if account:
                account.action_refresh_journal_lines()
        return True
    

    def action_reverse(self):
        """Reverse the transaction by setting journal entries to draft and deleting them, then setting transaction to pending"""
        for transaction in self:
            if transaction.status != 'confirmed':
                raise ValidationError(_("Only confirmed transactions can be reversed."))
                
            # Set journal entry to draft if it exists
            if transaction.journal_entry_id and transaction.journal_entry_id.state == 'posted':
                transaction.journal_entry_id.button_draft()
                
            # Delete the journal entry
            if transaction.journal_entry_id:
                transaction.journal_entry_id.unlink()
                
            # Reset transaction to pending
            transaction.write({
                'status': 'pending',
                'journal_entry_id': False
            })
            
            # Refresh account journal lines
            if transaction.shares_account_id:
                transaction.shares_account_id.action_refresh_journal_lines()