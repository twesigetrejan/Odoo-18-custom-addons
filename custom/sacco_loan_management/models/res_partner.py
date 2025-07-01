from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class res_partner(models.Model):
    _inherit = "res.partner"
    
    is_allow_loan = fields.Boolean('Allow Loan', default=True)
    loan_request = fields.Integer('Loan Request Per Year', default=1)
    loans_outstanding = fields.Float(
        string='Loans Outstanding',
        compute='_compute_loans_outstanding',
        store=True,
        digits='Account',
        help="Total outstanding loan balance in the selected currency."
    )
    
    
    @api.constrains('is_allow_loan','loan_request')        
    def check_rate(self):
        if self.is_allow_loan and self.loan_request <= 0:
            raise ValidationError(_("Loan Request Per Year Must be Positive !!!"))
    
    
    loan_ids = fields.One2many('sacco.loan.loan','client_id', string='Loans', domain=[('state','not in', ['draft','reject','cancel'])])
    count_loan = fields.Integer('View Loan', compute='_count_loan')
    
    @api.depends('loan_ids')
    def _count_loan(self):
        for partner in self:
            partner.count_loan = len(partner.loan_ids)
            
    def action_view_loan(self):
        loan_ids = self.env['sacco.loan.loan'].search([('client_id','=',self.id)])
        if loan_ids:
            action = self.env.ref('sacco_loan_management.action_sacco_loan_loan').read()[0]
            action['domain'] = [('id', 'in', loan_ids.ids),('state','not in',['draft','reject','cancel'])]
            return action
        else:
            action = {'type': 'ir.actions.act_window_close'}
    


    @api.depends('balance_currency_id')
    def _compute_loans_outstanding(self):
        for partner in self:
            if not partner.is_sacco_member or not partner.balance_currency_id:
                partner.loans_outstanding = 0.0
                continue

            # Fetch loans for this member in the selected currency
            loans = self.env['sacco.loan.loan'].search([
                ('client_id', '=', partner.id),
                ('currency_id', '=', partner.balance_currency_id.id),
                ('state', 'in', ['open', 'disburse']),
            ])

            # Sum the remaining amount balances
            total_outstanding = sum(loan.remaining_amount for loan in loans)
            partner.loans_outstanding = total_outstanding if total_outstanding > 0 else 0.0       

