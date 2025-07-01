from odoo import models, fields, api, _
from odoo.exceptions import UserError

class LoanProductWizard(models.TransientModel):
    _name = 'loan_product_wizard'
    _description = 'Loan Product Creation Wizard'

    name = fields.Char(string='Product Name', required=True)
    is_interest_apply = fields.Boolean(string='Apply Interest', default=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
        default=lambda self: self.env.company.currency_id)
    interest_mode = fields.Selection([('flat', 'Flat'), ('reducing', 'Reducing')], string='Interest Mode')
    rate = fields.Float(string='Interest Rate (%)', required=True)
    loan_amount = fields.Float(string='Loan Amount Limit', required=True, default=0.0)
    loan_term_by_month = fields.Integer(string='Loan Period (Months)', required=True, default=12)
    default_receiving_account_id = fields.Many2one('sacco.receiving.account',
        string='Default Receiving Account', required=True)
    default_paying_account_id = fields.Many2one('sacco.paying.account',
        string='Default Paying Account', required=True)

    @api.onchange('is_interest_apply')
    def _onchange_is_interest_apply(self):
        if self.is_interest_apply:
            self.interest_mode = 'flat'
        else:
            self.interest_mode = False

    def action_create_loan_product(self):
        """Create a loan product and its associated accounts."""
        AccountAccount = self.env['account.account']
        LoanType = self.env['sacco.loan.type']

        # Generate a unique product code
        product_code = LoanType._get_loan_unique_code()

        # Create Loan Disburse Account (type: asset_current, loans)
        loan_account = AccountAccount.create({
            'name': f"{self.name} - Disbursements",
            'code': f"{product_code}1",
            'account_type': 'asset_current',
            'reconcile': True,
            'requires_member': True,
            'account_product_type': 'loans',
        })

        # Create Interest Account (type: asset_current, loans_interest)
        interest_account = AccountAccount.create({
            'name': f"Interest Income from {self.name}",
            'code': f"{product_code}2",
            'account_type': 'asset_current',
            'reconcile': True,
            'requires_member': True,
            'account_product_type': 'loans_interest',
        })

        # Installment Account is set equal to Loan Account
        installment_account = loan_account

        # Get or ensure Member Journal exists
        member_journal = self.env['account.journal'].search([('name', '=', 'Member Journal')], limit=1)
        if not member_journal:
            raise UserError(_("Member Journal not found. Please create it first."))

        # Create the loan product
        loan_product_vals = {
            'name': self.name,
            'product_code': product_code,
            'is_interest_apply': self.is_interest_apply,
            'currency_id': self.currency_id.id,
            'interest_mode': self.interest_mode if self.is_interest_apply else False,
            'rate': self.rate,
            'loan_amount': self.loan_amount,
            'loan_term_by_month': self.loan_term_by_month,
            'default_receiving_account_id': self.default_receiving_account_id.id,
            'default_paying_account_id': self.default_paying_account_id.id,
            'loan_account_id': loan_account.id,
            'interest_account_id': interest_account.id,
            'installment_account_id': installment_account.id,
            'disburse_journal_id': member_journal.id,
            'loan_payment_journal_id': member_journal.id,
        }

        loan_product = LoanType.create(loan_product_vals)

        # Return an action to view the created loan product
        return {
            'type': 'ir.actions.act_window',
            'name': _('Created Loan Product'),
            'res_model': 'sacco.loan.type',
            'view_mode': 'form',
            'res_id': loan_product.id,
            'target': 'current',
        }