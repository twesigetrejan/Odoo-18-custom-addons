from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SavingsProductWizard(models.TransientModel):
    _name = 'savings_product_wizard'
    _description = 'Savings Product Creation Wizard'

    name = fields.Char(string='Product Name', required=True)
    interest_rate = fields.Float(string='Annual Interest Rate (%)', digits=(5, 2), required=True)
    period = fields.Selection([
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('semi_annually', 'Semi Annually (6 months)'),
        ('annually', 'Annually'),
    ], string='Interest Period', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
        default=lambda self: self.env.company.currency_id)
    default_receiving_account_id = fields.Many2one('sacco.receiving.account',
        string='Default Receiving Account', required=True)
    default_paying_account_id = fields.Many2one('sacco.paying.account',
        string='Default Paying Account', required=True)

    def action_create_savings_product(self):
        """Create a savings product and its associated accounts."""
        AccountAccount = self.env['account.account']
        SavingsProduct = self.env['sacco.savings.product']

        # Generate a unique product code
        product_code = SavingsProduct._get_unique_code()

        # Create Interest Expense Account (type: expense)
        interest_account = AccountAccount.create({
            'name': f"Interest Expense for {self.name}",
            'code': f"{product_code}3",
            'account_type': 'expense',
            'reconcile': True,
            'requires_member': False,
        })

        # Create Interest Disbursement Account (type: liability_current, savings_interest)
        interest_disbursement_account = AccountAccount.create({
            'name': f"{self.name} Interest Disbursement",
            'code': f"{product_code}4",
            'account_type': 'liability_current',
            'reconcile': True,
            'requires_member': True,
            'account_product_type': 'savings_interest',
        })

        # Create Savings Product Account (type: liability_current, savings)
        savings_product_account = AccountAccount.create({
            'name': f"{self.name} Savings Account",
            'code': f"{product_code}1",
            'account_type': 'liability_current',
            'reconcile': True,
            'requires_member': True,
            'account_product_type': 'savings',
        })

        # Create the savings product
        savings_product_vals = {
            'name': self.name,
            'product_code': product_code,
            'interest_rate': self.interest_rate,
            'period': self.period,
            'currency_id': self.currency_id.id,
            'default_receiving_account_id': self.default_receiving_account_id.id,
            'default_paying_account_id': self.default_paying_account_id.id,
            'interest_account_id': interest_account.id,
            'interest_disbursement_account_id': interest_disbursement_account.id,
            'savings_product_account_id': savings_product_account.id,
        }

        savings_product = SavingsProduct.create(savings_product_vals)

        # Return an action to view the created savings product
        return {
            'type': 'ir.actions.act_window',
            'name': _('Created Savings Product'),
            'res_model': 'sacco.savings.product',
            'view_mode': 'form',
            'res_id': savings_product.id,
            'target': 'current',
        }