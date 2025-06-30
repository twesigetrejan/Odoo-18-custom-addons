
from odoo import models, fields, api

class LoanPortfolio(models.Model):
    _name = 'loan.portfolio'
    _description = 'Loan Portfolio Performance'
    _rec_name = 'portfolio_code'

    portfolio_code = fields.Char(string='Portfolio Code', required=True, help='Unique code for the loan portfolio')
    total_disbursed = fields.Monetary(string='Total Disbursed', currency_field='currency_id', required=True)
    expected_outstanding = fields.Monetary(string='Expected Outstanding', currency_field='currency_id', required=True)
    actual_outstanding = fields.Monetary(string='Actual Outstanding', currency_field='currency_id', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, default=lambda self: self.env.company.currency_id)

    loan_ids = fields.One2many('loan.details', 'portfolio_id', string='Loan Details')

    @api.depends('loan_ids.expected_outstanding', 'loan_ids.actual_outstanding')
    def _compute_totals(self):
        for portfolio in self:
            portfolio.expected_outstanding = sum(loan.expected_outstanding for loan in portfolio.loan_ids)
            portfolio.actual_outstanding = sum(loan.actual_outstanding for loan in portfolio.loan_ids)
            portfolio.total_disbursed = sum(loan.disbursed_amount for loan in portfolio.loan_ids)

    @api.model
    def get_overview_metrics(self):
        """Return aggregated metrics for the dashboard."""
        # Fetch all portfolios to aggregate data
        portfolios = self.search([])
        if not portfolios:
            return {
                'total_disbursed': 0,
                'expected_outstanding': 0,
                'actual_outstanding': 0,
                'loan_count': 0,
            }

        total_disbursed = sum(portfolio.total_disbursed for portfolio in portfolios)
        expected_outstanding = sum(portfolio.expected_outstanding for portfolio in portfolios)
        actual_outstanding = sum(portfolio.actual_outstanding for portfolio in portfolios)
        loan_count = sum(len(portfolio.loan_ids) for portfolio in portfolios)

        return {
            'total_disbursed': total_disbursed,
            'expected_outstanding': expected_outstanding,
            'actual_outstanding': actual_outstanding,
            'loan_count': loan_count,
        }

class LoanDetails(models.Model):
    _name = 'loan.details'
    _description = 'Loan Details'

    portfolio_id = fields.Many2one('loan.portfolio', string='Portfolio', required=True)
    loan_id = fields.Char(string='Loan ID', required=True)
    member = fields.Char(string='Member', required=True)
    loan_product = fields.Char(string='Loan Product')
    interest_rate = fields.Float(string='Interest Rate', required=True)
    tenure_months = fields.Integer(string='Tenure (Months)', required=True)
    disbursed_amount = fields.Monetary(string='Disbursed Amount', currency_field='currency_id')
    expected_outstanding = fields.Monetary(string='Expected Outstanding', currency_field='currency_id')
    actual_outstanding = fields.Monetary(string='Actual Outstanding', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency', related='portfolio_id.currency_id', store=True)
    start_date = fields.Date(string='Start Date')
    outstanding_history = fields.Text(string='Outstanding History')