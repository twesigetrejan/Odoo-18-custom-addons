from odoo import models, api, fields, _
from odoo.exceptions import ValidationError
from datetime import date
import logging

_logger = logging.getLogger(__name__)

class SavingsTransaction(models.Model):
    _name = 'savings.transaction'
    _description = 'Savings Transaction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char('ID', default='/', copy=False)
    savings_account_id = fields.Many2one('sacco.savings.account', string='Savings Account')
    transaction_type = fields.Selection(
        [
            ('deposit', 'Deposit'),
            ('interest', 'Interest'),
            ('withdrawal', 'Withdrawal'),
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
    product_id = fields.Many2one('sacco.savings.product', string='Product', required=True)
    has_savings_account = fields.Boolean(compute='_compute_has_savings_account', store=True)
    account_status = fields.Char(compute='_compute_has_savings_account', store=True)
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    receiving_account_id = fields.Many2one('sacco.receiving.account', string='Receiving Account',
        help="The account that received this deposit")
    receipt_account = fields.Many2one('account.account', string='Receipt Account')
    general_transaction_id = fields.Many2one('sacco.general.transaction', string='General Transaction', ondelete='restrict')

    # MIS fields
    ref_id = fields.Char(string='Reference ID')
    mongo_db_id = fields.Char(string='Mongo DB ID', readonly=True)
    created_by = fields.Char(string='Created By')
        
    @api.model
    def create(self,vals):
        vals.update({
                    'name':self.env['ir.sequence'].next_by_code('savings.transaction') or '/'
                })
        return super(SavingsTransaction,self).create(vals)    
    
    @api.constrains('amount')        
    def check_amount(self):                
        for line in self:
            if line.amount <= 0:
                raise ValidationError(_("Amount must be greater than zero."))
            if line.transaction_type == 'withdrawal' and line.amount > line.savings_account_id.balance:
                raise ValidationError(_("Withdrawal amount cannot exceed the available balance."))
            if line.savings_account_id.balance == 0.0 and line.transaction_type in ['withdrawal', 'interest']:
                raise ValidationError(_("The first transaction in a savings account must be a deposit."))

    
    def action_confirm_transaction(self):
        self.ensure_one()
        
        # First check if savings account exists
        account = self.env['sacco.savings.account'].search([
            ('member_id', '=', self.member_id.id),
            ('product_id', '=', self.product_id.id),
            ('state', '=', 'active'),
        ], limit=1)
        
        if not account:
            if self.transaction_type in ['withdrawal', 'interest']:
                raise ValidationError(_("The first transaction in a savings account must be a deposit."))
                
            account = self.env['sacco.savings.account'].create({
                'member_id': self.member_id.id,
                'product_id': self.product_id.id,
                'currency_id': self.product_id.currency_id.id,
                'state': 'active',
            })
        
        self.savings_account_id = account.id
               
        if not self.savings_account_id.product_id.savings_product_journal_id:
            raise ValidationError(_("Please select a payment journal for the savings product!"))
        
        # Ensure receipt_account is set if receiving_account_id is provided
        if self.receiving_account_id and not self.receipt_account:
            self.receipt_account = self.receiving_account_id.account_id
        elif not self.receipt_account and self.transaction_type == 'deposit':
            raise ValidationError(_("A receipt account is required for deposit transactions. Please configure a receiving account with a valid accounting account."))

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
    def _compute_has_savings_account(self):
        for record in self:
            if record.member_id and record.product_id:
                account = self.env['sacco.savings.account'].search([
                    ('member_id', '=', record.member_id.id),
                    ('product_id', '=', record.product_id.id),
                    ('state', '=', 'active'),
                ], limit=1)
                record.has_savings_account = bool(account)
                record.account_status = "Account Id: " + account.name if account else "No Active Account - Will be created on confirmation"
            else:
                record.has_savings_account = False
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
            

    def get_account_move_vals(self):
        vals={
            'date':self.transaction_date,
            'ref':self.name or 'Transaction',
            'journal_id':self.savings_account_id.product_id.savings_product_journal_id and self.savings_account_id.product_id.savings_product_journal_id.id or False,
            'company_id':self.savings_account_id.product_id.savings_product_journal_id and self.savings_account_id.product_id.savings_product_journal_id.company_id and self.savings_account_id.product_id.savings_product_journal_id.company_id.id or False,
        }
        return vals
    
    def get_transaction_lines(self):
        if not self.savings_account_id.product_id.interest_account_id and self.transaction_type == 'interest':
            raise ValidationError(_("Select Disburse Account !!!"))        
        if self.transaction_type == 'interest':
            account_id = self.savings_account_id.product_id.interest_account_id
            vals={
                'partner_id':self.savings_account_id.member_id and self.savings_account_id.member_id.id or False,
                'account_id':account_id and account_id.id or False,
                'credit':self.amount,
                'name':self.transaction_type or '/',
                'date_maturity':self.transaction_date,
                'member_id': self.savings_account_id.member_id.member_id if self.savings_account_id.member_id and self.savings_account_id.member_id.member_id else False,
            }
        else:
            account_id = self.savings_account_id.product_id.savings_product_account_id
            vals={
                'partner_id':self.savings_account_id.member_id and self.savings_account_id.member_id.id or False,
                'account_id':account_id and account_id.id or False,
                'credit':self.amount,
                'name':self.transaction_type or '/',
                'date_maturity':self.transaction_date,
                'member_id': self.savings_account_id.member_id.member_id if self.savings_account_id.member_id and self.savings_account_id.member_id.member_id else False,
            }
            
        return vals
    
    def get_partner_lines(self):
        if self.transaction_type == 'interest':
            vals={
                'partner_id':self.savings_account_id.member_id and self.savings_account_id.member_id.id or False,
                'account_id':self.savings_account_id.member_id.property_account_receivable_id and self.savings_account_id.member_id.property_account_receivable_id.id or False,
                'debit':self.amount,
                'name':self.transaction_type or '/',
                'date_maturity':self.transaction_date,
            }
        else:
            account_id = self.receipt_account
            vals={
                'partner_id':self.savings_account_id.member_id and self.savings_account_id.member_id.id or False,
                'account_id':account_id and account_id.id or False,
                'debit':self.amount,
                'name':self.transaction_type or '/',
                'date_maturity':self.transaction_date,
            }
            
        return vals
    
    def post_entry(self):
        if self.transaction_type != 'withdrawal':
            # Validate required accounts
            if not self.receipt_account and self.transaction_type == 'deposit':
                raise ValidationError(_("No receipt account specified for deposit. Please configure a receiving account."))
            if not self.savings_account_id.product_id.savings_product_account_id:
                raise ValidationError(_("No savings product account configured for product: %s") % self.product_id.name)

            account_move_val = self.get_account_move_vals()
            account_move_id = self.env['account.move'].create(account_move_val)
            vals = []
            
            if account_move_id:
                # Debit line (receipt account)
                debit_vals = self.get_partner_lines()
                if not debit_vals['account_id']:
                    raise ValidationError(_("No valid account found for the debit line. Check the receiving account configuration."))
                vals.append((0, 0, debit_vals))
                
                # Credit line (savings product account)
                if self.amount:
                    credit_vals = self.get_transaction_lines()
                    if not credit_vals['account_id']:
                        raise ValidationError(_("No valid account found for the credit line. Check the savings product configuration."))
                    vals.append((0, 0, credit_vals))
                
                account_move_id.line_ids = vals
                self.journal_entry_id = account_move_id.id
                
                if account_move_id.state == 'draft':
                    account_move_id.action_post()
                    self.savings_account_id.action_refresh_journal_lines()
                    

    def unlink(self):
        for savings_transaction in self:
            if savings_transaction.journal_entry_id:
                raise ValidationError(_('Cannot delete transaction with associated journal entries. Please set the entry to draft then delete it'))
            if savings_transaction.general_transaction_id:
                raise ValidationError(_('Cannot delete transaction linked to a general transaction. Please unlink it first.'))
            # Store the associated savings account for refreshing journal lines
            account = savings_transaction.savings_account_id
            # Perform the deletion
            super(SavingsTransaction, savings_transaction).unlink()
            # Refresh journal lines for the associated account
            if account:
                account.action_refresh_journal_lines()
        return True
    

    # In savings_transaction.py, add to SavingsTransaction class
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
            if transaction.savings_account_id:
                transaction.savings_account_id.action_refresh_journal_lines()