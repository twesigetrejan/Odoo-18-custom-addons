from odoo import models, fields, api
from datetime import datetime, date

class LoanPortfolio2(models.Model):
    _name = 'loan.portfolio2'
    _description = 'Loan Portfolio Snapshot'
    _rec_name = 'name'

    name = fields.Char(string='Portfolio Name', required=True)
    date_from = fields.Date(string='Date From', required=True, default=lambda self: date.today().replace(day=1))
    date_to = fields.Date(string='Date To', required=True, default=fields.Date.today)
    branch_id = fields.Many2one('res.branch', string='Branch')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, default=lambda self: self.env.company.currency_id)
    
    # Portfolio lines
    portfolio_line_ids = fields.One2many('loan.portfolio2.line', 'portfolio_id', string='Portfolio Lines')
    
    # Summary fields
    total_opening_portfolio = fields.Monetary(string='Total Opening Portfolio', compute='_compute_totals', store=True)
    total_disbursements = fields.Monetary(string='Total Disbursements', compute='_compute_totals', store=True)
    total_principal_repaid = fields.Monetary(string='Total Principal Repaid', compute='_compute_totals', store=True)
    total_interest_earned = fields.Monetary(string='Total Interest Earned', compute='_compute_totals', store=True)
    total_closing_portfolio = fields.Monetary(string='Total Closing Portfolio', compute='_compute_totals', store=True)
    total_change_percentage = fields.Float(string='Total Change %', compute='_compute_totals', store=True)

    @api.depends('portfolio_line_ids.opening_portfolio', 'portfolio_line_ids.disbursements', 
                 'portfolio_line_ids.principal_repaid', 'portfolio_line_ids.interest_earned',
                 'portfolio_line_ids.closing_portfolio')
    def _compute_totals(self):
        for portfolio in self:
            lines = portfolio.portfolio_line_ids
            portfolio.total_opening_portfolio = sum(lines.mapped('opening_portfolio'))
            portfolio.total_disbursements = sum(lines.mapped('disbursements'))
            portfolio.total_principal_repaid = sum(lines.mapped('principal_repaid'))
            portfolio.total_interest_earned = sum(lines.mapped('interest_earned'))
            portfolio.total_closing_portfolio = sum(lines.mapped('closing_portfolio'))
            
            # Calculate total change percentage
            if portfolio.total_opening_portfolio:
                change = portfolio.total_closing_portfolio - portfolio.total_opening_portfolio
                portfolio.total_change_percentage = (change / portfolio.total_opening_portfolio) * 100
            else:
                portfolio.total_change_percentage = 0.0

    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None, branch_id=None):
        """Get dashboard data for the snapshot view"""
        domain = []
        
        if date_from:
            domain.append(('date_from', '>=', date_from))
        if date_to:
            domain.append(('date_to', '<=', date_to))
        if branch_id:
            domain.append(('branch_id', '=', branch_id))
            
        portfolios = self.search(domain)
        
        # Aggregate data by product
        product_data = {}
        for portfolio in portfolios:
            for line in portfolio.portfolio_line_ids:
                product = line.product_name
                if product not in product_data:
                    product_data[product] = {
                        'opening_portfolio': 0,
                        'disbursements': 0,
                        'principal_repaid': 0,
                        'interest_earned': 0,
                        'closing_portfolio': 0,
                    }
                
                product_data[product]['opening_portfolio'] += line.opening_portfolio
                product_data[product]['disbursements'] += line.disbursements
                product_data[product]['principal_repaid'] += line.principal_repaid
                product_data[product]['interest_earned'] += line.interest_earned
                product_data[product]['closing_portfolio'] += line.closing_portfolio
        
        # Calculate change percentages
        for product, data in product_data.items():
            if data['opening_portfolio']:
                change = data['closing_portfolio'] - data['opening_portfolio']
                data['change_percentage'] = (change / data['opening_portfolio']) * 100
            else:
                data['change_percentage'] = 0.0
        
        return {
            'product_data': product_data,
            'total_opening': sum(data['opening_portfolio'] for data in product_data.values()),
            'total_disbursements': sum(data['disbursements'] for data in product_data.values()),
            'total_principal_repaid': sum(data['principal_repaid'] for data in product_data.values()),
            'total_interest_earned': sum(data['interest_earned'] for data in product_data.values()),
            'total_closing': sum(data['closing_portfolio'] for data in product_data.values()),
        }

    @api.model
    def get_filter_options(self):
        """Get filter options for dashboard"""
        branches = self.env['res.branch'].search([])
        currencies = self.env['res.currency'].search([])
        
        return {
            'branches': branches.read(['id', 'name']),
            'currencies': currencies.read(['id', 'name', 'symbol']),
        }

    @api.model
    def generate_snapshot_report(self, date_from=None, date_to=None, branch_id=None):
        """Generate snapshot report"""
        report_data = self.get_dashboard_data(date_from, date_to, branch_id)
        
        return {
            'type': 'ir.actions.report',
            'report_name': 'my_hostel.loan_portfolio2_report_template',
            'report_type': 'qweb-pdf',
            'data': {
                'report_data': report_data,
                'date_from': date_from,
                'date_to': date_to,
                'branch_id': branch_id,
            },
            'context': {
                'active_model': 'loan.portfolio2',
                'report_data': report_data,
                'date_from': date_from,
                'date_to': date_to,
                'branch_id': branch_id,
            }
        }


class LoanPortfolio2Line(models.Model):
    _name = 'loan.portfolio2.line'
    _description = 'Loan Portfolio Line'

    portfolio_id = fields.Many2one('loan.portfolio2', string='Portfolio', required=True, ondelete='cascade')
    product_name = fields.Char(string='Product', required=True)
    opening_portfolio = fields.Monetary(string='Opening Portfolio', currency_field='currency_id')
    disbursements = fields.Monetary(string='Disbursements', currency_field='currency_id')
    principal_repaid = fields.Monetary(string='Principal Repaid', currency_field='currency_id')
    interest_earned = fields.Monetary(string='Interest Earned', currency_field='currency_id')
    closing_portfolio = fields.Monetary(string='Closing Portfolio', currency_field='currency_id')
    change_percentage = fields.Float(string='% Change', compute='_compute_change_percentage', store=True)
    currency_id = fields.Many2one('res.currency', related='portfolio_id.currency_id', store=True)

    @api.depends('opening_portfolio', 'closing_portfolio')
    def _compute_change_percentage(self):
        for line in self:
            if line.opening_portfolio:
                change = line.closing_portfolio - line.opening_portfolio
                line.change_percentage = (change / line.opening_portfolio) * 100
            else:
                line.change_percentage = 0.0