from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SaccoLoanGuarantor(models.Model):
    _name = "sacco.loan.guarantor"
    _description = "SACCO Loan Guarantor"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    loan_id = fields.Many2one('sacco.loan.loan', string='Loan', required=True, ondelete='cascade')
    guarantor_member_id = fields.Many2one(
        'res.partner',
        string='Guarantor Member',
        domain=[('is_sacco_member', '=', True)],
        required=True
    )
    pledge_type = fields.Selection(
        [('savings', 'Savings'), ('shares', 'Shares')],
        string='Pledge Type',
        required=True
    )
    pledge_amount = fields.Float(string='Pledge Amount', required=True)
    signature_path = fields.Many2one(
        'ir.attachment',
        string='Electronic Signature',
        domain="[('res_model', '=', 'sacco.loan.guarantor'), ('res_id', '=', id)]"
    )
    released_flag = fields.Boolean(
        string='Released',
        default=False,
        help="Indicates if the guarantor's pledge is released (set to True when the loan is closed)."
    )

    @api.model
    def create(self, vals):
        """Ensure only one guarantor per loan."""
        if 'loan_id' in vals:
            existing_guarantor = self.search([('loan_id', '=', vals['loan_id'])])
            if existing_guarantor:
                raise ValidationError(_("A loan can have only one guarantor."))
        return super(SaccoLoanGuarantor, self).create(vals)

    @api.constrains('guarantor_member_id', 'loan_id')
    def _check_guarantor_not_borrower(self):
        """Ensure the guarantor is not the same as the loan's member."""
        for record in self:
            if record.guarantor_member_id == record.loan_id.client_id:
                raise ValidationError(_("The guarantor cannot be the same as the loan's member."))
            if record.pledge_amount <= 0:
                raise ValidationError(_("Pledge amount must be positive."))

    # @api.constrains('pledge_type', 'pledge_amount')
    # def _check_pledge_validity(self):
    #     """Validate pledge amount against member's savings or shares based on pledge type."""
    #     for record in self:
    #         member = record.guarantor_member_id
    #         if record.pledge_type == 'savings':
    #             available_savings = member.savings_balance or 0.0 
    #             if record.pledge_amount > available_savings:
    #                 raise ValidationError(
    #                     _("Pledge amount (%s) exceeds member's available savings (%s).") % 
    #                     (record.pledge_amount, available_savings)
    #                 )
    #         elif record.pledge_type == 'shares':
    #             available_shares = member.shares_balance or 0.0
    #             if record.pledge_amount > available_shares:
    #                 raise ValidationError(
    #                     _("Pledge amount (%s) exceeds member's available shares (%s).") % 
    #                     (record.pledge_amount, available_shares)
    #                 )