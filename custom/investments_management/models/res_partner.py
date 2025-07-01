from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    investment_balance = fields.Float(
        string='Investment Balance',
        compute='_compute_investment_balance',
        store=True,
        digits='Account',
        help="Total investment balance in the selected currency."
    )

    @api.depends('balance_currency_id')
    def _compute_investment_balance(self):
        for partner in self:
            if not partner.is_sacco_member or not partner.balance_currency_id:
                partner.investment_balance = 0.0
                continue

            # Fetch investment accounts for this member in the selected currency
            investment_accounts = self.env['sacco.investments.account'].search([
                ('member_id', '=', partner.id),
                ('currency_id', '=', partner.balance_currency_id.id),
                ('state', '=', 'active'),
            ])

            # Sum the total balances (cash_balance + investment_balance)
            total_balance = sum(account.total_balance for account in investment_accounts)
            partner.investment_balance = total_balance if total_balance > 0 else 0.0