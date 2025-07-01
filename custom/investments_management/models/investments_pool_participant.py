from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta

class InvestmentPoolParticipant(models.Model):
    _name = 'sacco.investments.pool.participant'
    _description = 'Investment Pool Participant'
    _rec_name = 'investments_account_id'

    pool_id = fields.Many2one('sacco.investments.pool', string='Investment Pool', required=True, ondelete='cascade')
    investments_account_id = fields.Many2one('sacco.investments.account', string='Investment Account', required=True)
    member_id = fields.Many2one('res.partner', related='investments_account_id.member_id', string='Member')
    contribution_amount = fields.Float('Contribution Amount')
    actual_invested_amount = fields.Float('Actually Invested Amount')
    profit_earned = fields.Float('Profit Earned From Last Distribution')
    total_profit_earned = fields.Float('Total Profit Earned From Pool',
                                       compute='_compute_total_profit_earned',
                                       store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('invested', 'Invested'),
        ('completed', 'Completed')
    ], default='draft', string='Status')

    @api.constrains('actual_invested_amount')
    def _check_investment_amount(self):
        for participant in self:
            if participant.actual_invested_amount <= 0:
                raise ValidationError(_("Investment amount must be greater than zero."))

            remaining_balance = participant.investments_account_id.cash_balance - participant.actual_invested_amount
            if remaining_balance < participant.pool_id.minimum_balance:
                raise ValidationError(_("Investment would reduce account balance below minimum required cash balance."))
    
            if participant.actual_invested_amount > participant.contribution_amount:
                raise ValidationError(_("Investment amount cannot exceed available balance."))
            
    
    @api.depends('profit_earned', 'pool_id.interest_transaction_ids')
    def _compute_total_profit_earned(self):
        for participant in self:
            total_profit = 0.0
            for transaction in participant.pool_id.interest_transaction_ids:
                if transaction.investments_account_id == participant.investments_account_id:
                    total_profit += transaction.amount
                    
            participant.total_profit_earned = total_profit

    def unlink(self):
        for participant in self:
            if participant.pool_id.state == 'invested':
                raise ValidationError(_("You cannot delete a participant when the investment pool is in the 'Invested' state."))
        return super(InvestmentPoolParticipant, self).unlink()