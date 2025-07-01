from odoo import models, api, fields, _
from odoo.exceptions import ValidationError
from datetime import date
import logging

_logger = logging.getLogger(__name__)

class InvestmentsTransaction(models.Model):
    _name = 'sacco.investments.transaction'
    _description = 'Investments Transaction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char('ID', default='/', copy=False)
    investments_account_id = fields.Many2one('sacco.investments.account', string='Investments Account')
    transaction_type = fields.Selection([
        ('deposit', 'Cash Deposit'),
        ('withdrawal', 'Cash Withdrawal'),
        ('investment_purchase', 'Investment Purchase'),
        ('investment_sale', 'Investment Sale'),
        ('interest', 'Interest'),
        ('dividend', 'Dividend'),
        ('fee', 'Fee')
    ], string="Transaction Type", required=True, default='deposit')
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
    investment_pool_id = fields.Many2one('sacco.investments.pool', string='Investment Pool',
                                        help="Related investment pool for interest transactions")
    member_id = fields.Many2one('res.partner', string='Member', required=True, domain=[('is_sacco_member', '=', True)])
    product_id = fields.Many2one('sacco.investments.product', string='Investments Product', required=True)
    has_investments_account = fields.Boolean(compute='_compute_has_investments_account', store=True)
    account_status = fields.Char(compute='_compute_has_investments_account', store=True)
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    receiving_account_id = fields.Many2one('sacco.receiving.account', string='Receiving Account', 
                                          help="The account that received this deposit", force_save="1")
    receipt_account = fields.Many2one('account.account', string='Receipt Account', force_save="1")
    general_transaction_id = fields.Many2one('sacco.general.transaction', string='General Transaction', ondelete='restrict')
    
    # MIS fields
    ref_id = fields.Char(string='Reference ID')
    mongo_db_id = fields.Char(string='Mongo DB ID', readonly=True)
    created_by = fields.Char(string='Created By')

    @api.model
    def create(self, vals):
        vals.update({
            'name': self.env['ir.sequence'].next_by_code('sacco.investments.transaction') or '/'
        })
        return super(InvestmentsTransaction, self).create(vals)  

    @api.constrains('amount')        
    def check_amount(self):                
        for line in self:
            if line.amount <= 0:
                raise ValidationError(_("Amount must be greater than zero."))
            if line.transaction_type == 'withdrawal' and line.investments_account_id and line.amount > line.investments_account_id.cash_balance:
                raise ValidationError(_("Withdrawal amount cannot exceed the available cash balance."))
            if line.investments_account_id and not line.investments_account_id.journal_account_lines and line.transaction_type in ['withdrawal', 'interest']:
                raise ValidationError(_("The first transaction in an investments account must be a deposit."))

    @api.onchange('transaction_type')
    def _onchange_transaction_type(self):
        """Clear investment_pool_id if transaction type is not interest or investment purchase"""
        if self.transaction_type not in ['interest', 'investment_purchase']:
            self.investment_pool_id = False

    def action_confirm_transaction(self):
        self.ensure_one()
        
        # Check if investments account exists
        account = self.env['sacco.investments.account'].search([
            ('member_id', '=', self.member_id.id),
            ('product_id', '=', self.product_id.id),
            ('state', '=', 'active'),
        ], limit=1)
        
        if not account:
            if self.transaction_type in ['withdrawal', 'interest']:
                raise ValidationError(_("The first transaction in an investments account must be a deposit."))
            account = self.env['sacco.investments.account'].create({
                'member_id': self.member_id.id,
                'product_id': self.product_id.id,
                'currency_id': self.product_id.currency_id.id,
                'state': 'active',
            })
        
        self.investments_account_id = account.id
        
        if not self.investments_account_id.product_id.investments_product_journal_id:
            raise ValidationError(_("Please select a payment journal for the investments product!"))
        
        # Ensure receipt_account is set if receiving_account_id is provided
        if self.receiving_account_id and not self.receipt_account:
            self.receipt_account = self.receiving_account_id.account_id
        elif not self.receipt_account and self.transaction_type in ['deposit', 'dividend']:
            raise ValidationError(_("A receipt account is required for deposit, or dividend transactions."))

        # Check sufficient balance for withdrawals, investment purchases, and fees
        if self.transaction_type in ['withdrawal', 'investment_purchase', 'fee']:
            available_cash = self.investments_account_id.cash_balance
            if available_cash < self.amount:
                raise ValidationError(_("Insufficient cash balance for this transaction."))

        if self.status != 'confirmed':
            self.status = 'confirmed'
            # Skip journal entry creation for interest transactions if journal_entry_id is already set
            if self.transaction_type != 'interest' or not self.journal_entry_id:
                self.post_entry()
                
        self.investments_account_id.action_refresh_journal_lines()

    def action_reject_transaction(self):
        self.status = 'rejected'
        
    @api.depends('product_id')
    def _compute_currency(self):
        for record in self:
            record.currency_id = record.product_id.currency_id if record.product_id else self.env.company.currency_id
            
    @api.depends('member_id', 'product_id')
    def _compute_has_investments_account(self):
        for record in self:
            if record.member_id and record.product_id:
                account = self.env['sacco.investments.account'].search([
                    ('member_id', '=', record.member_id.id),
                    ('product_id', '=', record.product_id.id),
                    ('state', '=', 'active'),
                ], limit=1)
                record.has_investments_account = bool(account)
                record.account_status = "Account Id: " + account.name if account else "No Active Account - Will be created on confirmation"
            else:
                record.has_investments_account = False
                record.account_status = "Select Member and Product"
    
    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id and self.product_id.default_receiving_account_id:
            self.receiving_account_id = self.product_id.default_receiving_account_id.id

    @api.onchange('receiving_account_id')
    def _onchange_receiving_account_id(self):
        if self.receiving_account_id:
            self.receipt_account = self.receiving_account_id.account_id
        else:
            self.receipt_account = False

    def get_account_move_vals(self):
        """Prepare values for the account move"""
        return {
            'date': self.transaction_date,
            'ref': self.name or 'Transaction',
            'journal_id': self.investments_account_id.product_id.investments_product_journal_id.id,
            'company_id': self.investments_account_id.product_id.investments_product_journal_id.company_id.id,
        }

    def get_transaction_lines(self):
        """Get the transaction line values based on transaction type"""
        product = self.investments_account_id.product_id
        partner_id = self.investments_account_id.member_id.id
        member_id = self.investments_account_id.member_id.member_id if self.investments_account_id.member_id.member_id else False

        # Validate required accounts
        if self.transaction_type in ['investment_purchase', 'investment_sale'] and not product.investments_product_account_id:
            raise ValidationError(_("Investment Account not configured!"))
        if self.transaction_type in ['deposit', 'withdrawal', 'fee', 'investment_purchase'] and not product.investments_product_cash_account_id:
            raise ValidationError(_("Cash Account not configured!"))
        if self.transaction_type == 'dividend' and not product.investments_product_cash_profit_account_id:
            raise ValidationError(_("Cash Profit Account not configured!"))

        if self.transaction_type == 'investment_purchase':
            return {
                'partner_id': partner_id,
                'account_id': product.investments_product_account_id.id,
                'credit': self.amount,
                'name': f"Purchase: {self.name}",
                'date_maturity': self.transaction_date,
                'member_id': member_id,
            }
        elif self.transaction_type == 'investment_sale':
            return {
                'partner_id': partner_id,
                'account_id': product.investments_product_account_id.id,
                'credit': self.amount,
                'name': f"Sale: {self.name}",
                'date_maturity': self.transaction_date,
                'member_id': member_id,
            }
        elif self.transaction_type in ['deposit', 'dividend']:
            account_id = product.investments_product_cash_profit_account_id.id if self.transaction_type == 'dividend' else product.investments_product_cash_account_id.id
            return {
                'partner_id': partner_id,
                'account_id': account_id,
                'credit': self.amount,
                'name': self.name or '/',
                'date_maturity': self.transaction_date,
                'member_id': member_id,
            }
        elif self.transaction_type in ['withdrawal', 'fee']:
            return {
                'partner_id': partner_id,
                'account_id': product.investments_product_cash_account_id.id,
                'debit': self.amount,
                'name': self.name or '/',
                'date_maturity': self.transaction_date,
                'member_id': member_id,
            }

    def get_partner_lines(self):
        """Get the partner line values based on transaction type"""
        partner_id = self.investments_account_id.member_id.id
        product = self.investments_account_id.product_id

        if self.transaction_type == 'investment_purchase':
            return {
                'partner_id': partner_id,
                'account_id': product.investments_product_cash_account_id.id,
                'debit': self.amount,
                'name': f"Purchase: {self.name}",
                'date_maturity': self.transaction_date,
            }
        elif self.transaction_type == 'investment_sale':
            return {
                'partner_id': partner_id,
                'account_id': product.investments_product_cash_account_id.id,
                'debit': self.amount,
                'name': f"Sale: {self.name}",
                'date_maturity': self.transaction_date,
            }
        else:  # deposit, dividend, withdrawal, fee
            if not self.receipt_account:
                raise ValidationError(_("No receipt account specified for this transaction."))
            # Determine whether to use debit or credit based on transaction type
            line_vals = {
                'partner_id': partner_id,
                'account_id': self.receipt_account.id,
                'name': self.name or '/',
                'date_maturity': self.transaction_date,
            }
            if self.transaction_type in ['deposit', 'dividend']:
                line_vals['debit'] = self.amount
            else:  # withdrawal, fee
                line_vals['credit'] = self.amount
            return line_vals

    def post_entry(self):
        """Post the accounting entry for the transaction"""
        # Skip journal entries for withdrawal if not needed
        if self.transaction_type == 'withdrawal':
            return

        account_move_val = self.get_account_move_vals()
        account_move = self.env['account.move'].create(account_move_val)
        
        if account_move:
            move_lines = []
            # Add partner line
            partner_line = self.get_partner_lines()
            if not partner_line['account_id']:
                raise ValidationError(_("No valid account found for the partner line."))
            move_lines.append((0, 0, partner_line))
            
            # Add transaction line
            transaction_line = self.get_transaction_lines()
            if not transaction_line['account_id']:
                raise ValidationError(_("No valid account found for the transaction line."))
            move_lines.append((0, 0, transaction_line))
            
            account_move.line_ids = move_lines
            self.journal_entry_id = account_move.id
            
            if account_move.state == 'draft':
                account_move.action_post()
                self.investments_account_id.action_refresh_journal_lines()

    def unlink(self):
        for transaction in self:
            if transaction.journal_entry_id:
                raise ValidationError(_('Cannot delete transaction with associated journal entries. Please set the entry to draft then delete it'))
            if transaction.general_transaction_id:
                raise ValidationError(_('Cannot delete transaction linked to a general transaction. Please unlink it first.'))
            # Store the associated investments account for refreshing journal lines
            account = transaction.investments_account_id
            # Perform the deletion
            super(InvestmentsTransaction, transaction).unlink()
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
            if transaction.investments_account_id:
                transaction.investments_account_id.action_refresh_journal_lines()