from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    savings_balance = fields.Float(
        string='Savings Balance',
        compute='_compute_savings_balance',
        store=True,
        digits='Account',
        help="Total savings balance in the selected currency."
    )

    @api.depends('balance_currency_id')
    def _compute_savings_balance(self):
        for partner in self:
            if not partner.is_sacco_member or not partner.balance_currency_id:
                partner.savings_balance = 0.0
                continue

            # Fetch savings accounts for this member in the selected currency
            savings_accounts = self.env['sacco.savings.account'].search([
                ('member_id', '=', partner.id),
                ('currency_id', '=', partner.balance_currency_id.id),
                ('state', '=', 'active'),
            ])

            # Sum the balances
            total_balance = sum(account.balance for account in savings_accounts)
            partner.savings_balance = total_balance if total_balance > 0 else 0.0