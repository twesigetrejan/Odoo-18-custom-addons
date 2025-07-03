from odoo import models, fields, api
from datetime import date


class SavingPortfolio(models.Model):
    _name = 'saving.portfolio'
    _description = 'Saving Portfolio Overview'
    _rec_name = 'portfolio_code'

    portfolio_code = fields.Selection([
        ('students', 'Students'),
        ('corporate_clients', 'Corporate clients'),
        ('youth_groups', 'Youth Groups'),
        ('senior_citizens', 'Senior Citizens'),
        ('NGO', 'NGO / Charity groups'),
        ('government_workers', 'Government workers'),
        ('farmers', 'farmers')
    ], string='Portfolio Name', required=True, help="Category of savings group")
    
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                  default=lambda self: self.env.company.currency_id)

    total_accounts = fields.Integer(string='Total Accounts', compute='_compute_totals')
    total_balances = fields.Monetary(string='Total Balances', currency_field='currency_id', compute='_compute_totals')

    account_ids = fields.One2many('saving.details', 'portfolio_id', string='Saving Accounts')

    @api.depends('account_ids.balance')
    def _compute_totals(self):
        for portfolio in self:
            portfolio.total_accounts = len(portfolio.account_ids)
            portfolio.total_balances = sum(a.balance for a in portfolio.account_ids)

    @api.model
    def get_dashboard_metrics(self, dormancy_period=90, balance_threshold=None):
        accounts = self.env['saving.details'].search([])

        total_accounts = len(accounts)
        dormant_accounts = len(accounts.filtered(lambda a: a.days_idle >= dormancy_period))
        dormant_balances = sum(a.balance for a in accounts.filtered(lambda a: a.days_idle >= dormancy_period))

        metrics = {
            'total_accounts': total_accounts,
            'dormant_accounts': dormant_accounts,
            'dormant_balances': dormant_balances,
            'dormant_percentage': (dormant_accounts / total_accounts) * 100 if total_accounts else 0
        }

        if balance_threshold is not None:
            balance_accounts = len(accounts.filtered(lambda a: a.balance < balance_threshold))
            metrics['balance_accounts'] = balance_accounts

        return metrics

    @api.model
    def get_idle_distribution(self):
        distribution = {'30': 0, '60': 0, '120': 0, '160+': 0}
        accounts = self.env['saving.details'].search([])

        for acc in accounts:
            if acc.days_idle >= 160:
                distribution['160+'] += 1
            elif acc.days_idle >= 120:
                distribution['120'] += 1
            elif acc.days_idle >= 60:
                distribution['60'] += 1
            elif acc.days_idle >= 30:
                distribution['30'] += 1

        return distribution


class SavingDetails(models.Model):
    _name = 'saving.details'
    _description = 'Individual Saving Account Details'
    _rec_name ='member_name'
    _order = 'member_id'

    portfolio_id = fields.Many2one('saving.portfolio', string='Portfolio', required=True)
    member_id = fields.Char(string='Member ID', required=True)
    member_name = fields.Char(string='Name', required=True)
    product_type = fields.Selection([
        ('ordinary', 'Ordinary Savings'),
        ('fixed_deposit', 'Fixed Deposit'),
        ('premium', 'Premium Savings'),
        ('regular', 'Regular Savings'),
        ('youth', 'Youth Savings'),
    ], string='Product', required=True)

    currency_id = fields.Many2one('res.currency', string='Currency', related='portfolio_id.currency_id', store=True)
    transaction_ids = fields.One2many('saving.transaction', 'account_id', string='Transactions')

    balance = fields.Monetary(string='Balance', compute='_compute_balance', store=True, currency_field='currency_id')
    last_transaction_date = fields.Datetime(string='Last Transaction Date', compute='_compute_last_transaction', store=True)
    days_idle = fields.Integer(string='Days Idle', compute='_compute_days_idle', store=True)

    @api.depends('transaction_ids.amount', 'transaction_ids.transaction_type')
    def _compute_balance(self):
        for rec in self:
            deposits = sum(t.amount for t in rec.transaction_ids if t.transaction_type == 'deposit')
            withdrawals = sum(t.amount for t in rec.transaction_ids if t.transaction_type == 'withdrawal')
            rec.balance = deposits - withdrawals

    @api.depends('transaction_ids.transaction_date')
    def _compute_last_transaction(self):
        for rec in self:
            if rec.transaction_ids:
                rec.last_transaction_date = max(rec.transaction_ids.mapped('transaction_date'))
            else:
                rec.last_transaction_date = False

    @api.depends('last_transaction_date')
    def _compute_days_idle(self):
        today = date.today()
        for rec in self:
            rec.days_idle = (today - rec.last_transaction_date.date()).days if rec.last_transaction_date else 0


class SavingTransaction(models.Model):
    _name = 'saving.transaction'
    _description = 'Saving Transactions'
    _rec_name = 'account_id'

    account_id = fields.Many2one('saving.details', string='Account', required=True, ondelete='cascade')
    transaction_type = fields.Selection([
        ('deposit', 'Deposit'),
        ('withdrawal', 'Withdrawal'),
    ], string='Type', required=True)
    amount = fields.Monetary(string='Amount', required=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency', related='account_id.currency_id', store=True)
    transaction_date = fields.Datetime(string='Transaction Date', default=fields.Datetime.now)
    reference = fields.Char(string='Reference')
