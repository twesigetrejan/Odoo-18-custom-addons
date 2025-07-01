from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class InvestmentPoolProfit(models.Model):
    _name = 'sacco.investment.pool.profit'
    _description = 'Investment Pool Profit'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Profit ID', default='/', copy=False, required=True)
    investment_pool_id = fields.Many2one('sacco.investments.pool', string='Investment Pool', required=True,
                                        domain=[('state', 'in', ['invested'])])
    investment_product_id = fields.Many2one('sacco.investments.product', string='Investment Product',
                                           related='investment_pool_id.investment_product_id', store=True, readonly=True)
    profit_amount = fields.Float(string='Profit Amount', required=True,
                                 help="The profit (or loss if negative) to record for this pool.")
    transaction_date = fields.Date(string='Transaction Date', required=True, default=fields.Date.context_today,
                                   help="The accounting date for the journal entry.")
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    receiving_account_id = fields.Many2one('sacco.receiving.account', string='Receiving Account',
                                          default=lambda self: self._default_receiving_account(),
                                          help="The account receiving the profit.", force_save="1")
    receipt_account = fields.Many2one('account.account', string='Receipt Account', force_save="1",
                                     help="The accounting account linked to the receiving account.")
    investment_profit_expense_account_id = fields.Many2one(
        'account.account', string='Investment Profit Expense Account',
        related='investment_pool_id.investment_profit_expense_account_id', store=True, readonly=True
    )

    @api.model
    def create(self, vals):
        if vals.get('name', '/') == '/':
            vals['name'] = self.env['ir.sequence'].next_by_code('sacco.investment.pool.profit') or '/'
        return super(InvestmentPoolProfit, self).create(vals)

    def _default_receiving_account(self):
        if self.investment_pool_id and self.investment_pool_id.investment_product_id.default_receiving_account_id:
            return self.investment_pool_id.investment_product_id.default_receiving_account_id.id
        return False

    @api.onchange('investment_pool_id')
    def _onchange_investment_pool_id(self):
        if self.investment_pool_id and self.investment_pool_id.investment_product_id.default_receiving_account_id:
            self.receiving_account_id = self.investment_pool_id.investment_product_id.default_receiving_account_id
        else:
            self.receiving_account_id = False

    @api.onchange('receiving_account_id')
    def _onchange_receiving_account_id(self):
        if self.receiving_account_id:
            self.receipt_account = self.receiving_account_id.account_id
        else:
            self.receipt_account = False

    def action_confirm(self):
        self.ensure_one()
        if self.state != 'draft':
            raise ValidationError(_("Only draft profit records can be confirmed."))
        
        if not self.receiving_account_id or not self.receipt_account:
            raise ValidationError(_("Please specify a receiving account with a valid receipt account."))
        
        if not self.investment_profit_expense_account_id:
            raise ValidationError(_("No investment profit expense account configured for the pool."))
        
        if not self.investment_product_id.investments_product_journal_id:
            raise ValidationError(_("No journal configured for the investment product."))

        # Create journal entry
        move_vals = {
            'date': self.transaction_date,
            'ref': f"Profit Record: {self.name}",
            'journal_id': self.investment_product_id.investments_product_journal_id.id,
            'company_id': self.investment_product_id.investments_product_journal_id.company_id.id,
        }
        
        move_lines = [
            # Debit the receipt account (profit received)
            (0, 0, {
                'account_id': self.receipt_account.id,
                'debit': abs(self.profit_amount) if self.profit_amount > 0 else 0,
                'credit': abs(self.profit_amount) if self.profit_amount < 0 else 0,  # Handle losses
                'name': f"Profit Receipt: {self.name}",
                'date_maturity': self.transaction_date,
            }),
            # Credit the investment profit expense account (profit recorded)
            (0, 0, {
                'account_id': self.investment_profit_expense_account_id.id,
                'credit': abs(self.profit_amount) if self.profit_amount > 0 else 0,
                'debit': abs(self.profit_amount) if self.profit_amount < 0 else 0,  # Handle losses
                'name': f"Profit Record: {self.name}",
                'date_maturity': self.transaction_date,
            }),
        ]

        move = self.env['account.move'].create(move_vals)
        move.line_ids = move_lines
        move.action_post()
        
        self.write({
            'state': 'confirmed',
            'journal_entry_id': move.id,
        })
        
        self.investment_pool_id._compute_current_profit()

    def action_cancel(self):
        self.ensure_one()
        if self.state != 'draft':
            raise ValidationError(_("Only draft profit records can be cancelled."))
        self.state = 'cancelled'

    def unlink(self):
        for record in self:
            if record.state != 'draft' or record.state == 'confirmed':
                raise ValidationError(_("Only draft profit records can be deleted."))
        return super(InvestmentPoolProfit, self).unlink()