from odoo import models, fields, api, _
from odoo.exceptions import UserError

class InvestmentsProductWizard(models.TransientModel):
    _name = 'investments_product_wizard'
    _description = 'Investments Product Creation Wizard'

    name = fields.Char(string='Product Name', required=True)
    interest_rate = fields.Float(string='Annual Interest Rate (%)', digits=(5, 2), required=True, default=0.0)
    minimum_balance = fields.Float(string='Minimum Investment Amount', required=True)
    period = fields.Selection([
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('annually', 'Annually'),
    ], string='Interest Period', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
        default=lambda self: self.env.company.currency_id)
    default_receiving_account_id = fields.Many2one('sacco.receiving.account',
        string='Default Receiving Account', required=True)
    default_paying_account_id = fields.Many2one('sacco.paying.account',
        string='Default Paying Account', required=True)
    investment_risk = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High')
    ], string='Risk Level', default='low')
    maturity_period = fields.Integer(string='Maturity Period (Months)')

    def action_create_investments_product(self):
        """Create an investment product and its associated accounts."""
        AccountAccount = self.env['account.account']
        InvestmentsProduct = self.env['sacco.investments.product']

        # Generate a unique product code
        product_code = InvestmentsProduct._get_investment_unique_code()

        # Create Investments Product Cash Account (type: liability_current, investments_cash)
        cash_account = AccountAccount.create({
            'name': f"{self.name} Investment Cash Account",
            'code': f"{product_code}1",
            'account_type': 'liability_current',
            'reconcile': True,
            'requires_member': True,
            'account_product_type': 'investments_cash',
        })

        # Create Investments Product Cash Profit Account (type: liability_current, investments_cash_profit)
        cash_profit_account = AccountAccount.create({
            'name': f"{self.name} Investment Cash Profit Account",
            'code': f"{product_code}2",
            'account_type': 'liability_current',
            'reconcile': True,
            'requires_member': True,
            'account_product_type': 'investments_cash_profit',
        })

        # Create Investments Product Account (type: asset_current, investments)
        investment_account = AccountAccount.create({
            'name': f"{self.name} Investment Fund Account",
            'code': f"{product_code}3",
            'account_type': 'asset_current',
            'reconcile': True,
            'requires_member': True,
            'account_product_type': 'investments',
        })

        # Create the investment product
        investments_product_vals = {
            'name': self.name,
            'product_code': product_code,
            'interest_rate': self.interest_rate,
            'minimum_balance': self.minimum_balance,
            'period': self.period,
            'currency_id': self.currency_id.id,
            'default_receiving_account_id': self.default_receiving_account_id.id,
            'default_paying_account_id': self.default_paying_account_id.id,
            'investment_risk': self.investment_risk,
            'maturity_period': self.maturity_period,
            'investments_product_cash_account_id': cash_account.id,
            'investments_product_cash_profit_account_id': cash_profit_account.id,
            'investments_product_account_id': investment_account.id,
        }

        investments_product = InvestmentsProduct.create(investments_product_vals)

        # Return an action to view the created investment product
        return {
            'type': 'ir.actions.act_window',
            'name': _('Created Investments Product'),
            'res_model': 'sacco.investments.product',
            'view_mode': 'form',
            'res_id': investments_product.id,
            'target': 'current',
        }