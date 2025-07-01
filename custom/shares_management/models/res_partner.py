from odoo import models, fields, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    shares_balance = fields.Float(
        string='Shares Balance',
        compute='_compute_shares_balance',
        store=True,
        digits='Account',
        help="Total shares balance in the selected currency, calculated as share number times product price per share."
    )

    @api.depends('balance_currency_id')
    def _compute_shares_balance(self):
        for partner in self:
            if not partner.is_sacco_member or not partner.balance_currency_id:
                partner.shares_balance = 0.0
                continue

            # Fetch shares accounts for this member in the selected currency
            shares_accounts = self.env['sacco.shares.account'].search([
                ('member_id', '=', partner.id),
                ('currency_id', '=', partner.balance_currency_id.id),
                ('state', '=', 'active'),
            ])

            # Sum the balances (share_number * current_shares_amount)
            total_balance = 0.0
            for account in shares_accounts:
                current_shares_amount = account.product_id.current_shares_amount if account.product_id else 0.0
                total_balance += account.share_number * current_shares_amount

            partner.shares_balance = total_balance if total_balance > 0 else 0.0