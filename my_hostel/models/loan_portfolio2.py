

#please note
#there is a second higlighted implementation using materialised views, and i have also made the _auto field false to avoid the model from being added as a table directly to the db

from odoo import models, fields, api
from datetime import datetime, date

class LoanPortfolio2(models.Model):
    _name = 'loan.portfolio2'
    _description = 'Loan Portfolio Snapshot'
    _rec_name = 'name'
    _auto = False

    name = fields.Char(string='Portfolio Name', required=True)
    date_from = fields.Date(string='Date From', required=True, default=lambda self: date.today().replace(day=1))
    date_to = fields.Date(string='Date To', required=True, default=fields.Date.today)
    product_type = fields.Selection([
        ('ordinary', 'Ordinary Savings'),
        ('fixed_deposit', 'Fixed Deposit'),
        ('premium', 'Premium Savings'),
        ('regular', 'Regular Savings'),
        ('youth', 'Youth Savings'),
    ], string='Product Type', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, default=lambda self: self.env.company.currency_id)
    
    portfolio_line_ids = fields.One2many('loan.portfolio2.line', 'portfolio_id', string='Portfolio Lines')    
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
            
            if portfolio.total_opening_portfolio:
                change = portfolio.total_closing_portfolio - portfolio.total_opening_portfolio
                portfolio.total_change_percentage = (change / portfolio.total_opening_portfolio) * 100
            else:
                portfolio.total_change_percentage = 0.0

    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None, product_type=None):
        """Get dashboard data for the snapshot view"""
        domain = []
        
        if date_from:
            domain.append(('date_from', '>=', date_from))
        if date_to:
            domain.append(('date_to', '<=', date_to))
        if product_type:
            domain.append(('product_type', '=', product_type))
            
        portfolios = self.search(domain)
        
        # Aggregate data by product name and include product type
        product_data = {}
        for portfolio in portfolios:
            for line in portfolio.portfolio_line_ids:
                product = line.product_name
                if product not in product_data:
                    product_data[product] = {
                        'product_type': portfolio.product_type,  # Include product type
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
        
        # Calculate totals with change percentage
        total_opening = sum(data['opening_portfolio'] for data in product_data.values())
        total_closing = sum(data['closing_portfolio'] for data in product_data.values())
        total_change = 0.0
        if total_opening:
            total_change = ((total_closing - total_opening) / total_opening) * 100
        
        return {
            'product_data': product_data,
            'total_opening': total_opening,
            'total_disbursements': sum(data['disbursements'] for data in product_data.values()),
            'total_principal_repaid': sum(data['principal_repaid'] for data in product_data.values()),
            'total_interest_earned': sum(data['interest_earned'] for data in product_data.values()),
            'total_closing': total_closing,
            'total_change_percentage': total_change
        }

    @api.model
    def get_filter_options(self):
        """Get filter options for dashboard"""
        currencies = self.env['res.currency'].search([])
        
        return {
            'currencies': currencies.read(['id', 'name', 'symbol']),
            'product_types': [
                {'id': 'ordinary', 'name': 'Ordinary Savings'},
                {'id': 'fixed_deposit', 'name': 'Fixed Deposit'},
                {'id': 'premium', 'name': 'Premium Savings'},
                {'id': 'regular', 'name': 'Regular Savings'},
                {'id': 'youth', 'name': 'Youth Savings'}
            ]
        }

    @api.model
    def generate_snapshot_report(self, date_from=None, date_to=None, product_type=None):
        """Generate snapshot report"""
        report_data = self.get_dashboard_data(date_from, date_to, product_type)
        
        return {
            'type': 'ir.actions.report',
            'report_name': 'my_hostel.loan_portfolio2_report_template',
            'report_type': 'qweb-pdf',
            'data': {
                'report_data': report_data,
                'date_from': date_from,
                'date_to': date_to,
                'product_type': product_type,
            },
            'context': {
                'active_model': 'loan.portfolio2',
                'report_data': report_data,
                'date_from': date_from,
                'date_to': date_to,
                'product_type': product_type,
            }
        }


class LoanPortfolio2Line(models.Model):
    _name = 'loan.portfolio2.line'
    _description = 'Loan Portfolio Line'

    portfolio_id = fields.Many2one('loan.portfolio2', string='Portfolio', required=True, ondelete='cascade')
    product_name = fields.Char(string='Product Name', required=True)
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
                
                
# from odoo import models, fields, api
# from datetime import datetime, date
# import logging
# from odoo.tools import float_round

# _logger = logging.getLogger(__name__)

# class LoanPortfolio2(models.Model):
#     _name = 'loan.portfolio2'
#     _description = 'Loan Portfolio Snapshot'
#     _auto = False
#     _order = 'id'

#     id = fields.Integer('ID', readonly=True)
#     name = fields.Char('Portfolio Name', readonly=True)
#     date_from = fields.Date('Date From', readonly=True)
#     date_to = fields.Date('Date To', readonly=True)
#     product_type = fields.Selection([
#         ('ordinary', 'Ordinary Savings'),
#         ('fixed_deposit', 'Fixed Deposit'),
#         ('premium', 'Premium Savings'),
#         ('regular', 'Regular Savings'),
#         ('youth', 'Youth Savings'),
#     ], string='Product Type', readonly=True)
#     currency_id = fields.Many2one('res.currency', string='Currency', readonly=True)
#     opening_portfolio = fields.Monetary('Opening Portfolio', readonly=True)
#     disbursements = fields.Monetary('Disbursements', readonly=True)
#     principal_repaid = fields.Monetary('Principal Repaid', readonly=True)
#     interest_earned = fields.Monetary('Interest Earned', readonly=True)
#     closing_portfolio = fields.Monetary('Closing Portfolio', readonly=True)
#     change_percentage = fields.Float('Change %', readonly=True)

#     def init(self):
#         """Initialize the materialized view"""
#         self.env.cr.execute("""
#             DROP MATERIALIZED VIEW IF EXISTS loan_portfolio2 CASCADE
#         """)
#         self.env.cr.execute("""
#             CREATE MATERIALIZED VIEW loan_portfolio2 AS
#             WITH portfolio_lines AS (
#                 SELECT
#                     lpl.portfolio_id,
#                     SUM(lpl.opening_portfolio) AS opening_portfolio,
#                     SUM(lpl.disbursements) AS disbursements,
#                     SUM(lpl.principal_repaid) AS principal_repaid,
#                     SUM(lpl.interest_earned) AS interest_earned,
#                     SUM(lpl.closing_portfolio) AS closing_portfolio,
#                     CASE 
#                         WHEN SUM(lpl.opening_portfolio) > 0 
#                         THEN ((SUM(lpl.closing_portfolio) - SUM(lpl.opening_portfolio)) / SUM(lpl.opening_portfolio) * 100)
#                         ELSE 0.0 
#                     END AS change_percentage
#                 FROM loan_portfolio2_line lpl
#                 GROUP BY lpl.portfolio_id
#             )
#             SELECT 
#                 lp.id AS id,
#                 lp.name,
#                 lp.date_from,
#                 lp.date_to,
#                 lp.product_type,
#                 lp.currency_id,
#                 pl.opening_portfolio,
#                 pl.disbursements,
#                 pl.principal_repaid,
#                 pl.interest_earned,
#                 pl.closing_portfolio,
#                 pl.change_percentage
#             FROM loan_portfolio2 lp
#             LEFT JOIN portfolio_lines pl ON lp.id = pl.portfolio_id
#             WHERE lp.date_to <= CURRENT_DATE
#         """)
#         self.env.cr.execute("""
#             CREATE UNIQUE INDEX loan_portfolio2_id_idx 
#             ON loan_portfolio2 (id)
#         """)
#         self.env.cr.execute("""
#             CREATE INDEX loan_portfolio2_date_from_idx 
#             ON loan_portfolio2 (date_from)
#         """)
#         self.env.cr.execute("""
#             CREATE INDEX loan_portfolio2_date_to_idx 
#             ON loan_portfolio2 (date_to)
#         """)
#         self.env.cr.execute("""
#             CREATE INDEX loan_portfolio2_product_type_idx 
#             ON loan_portfolio2 (product_type)
#         """)

#     @api.model
#     def refresh_materialized_view(self):
#         """Refresh the materialized view"""
#         self.env.cr.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY loan_portfolio2")
#         _logger.info("Loan portfolio materialized view refreshed successfully")

#     @api.model
#     def get_dashboard_data(self, date_from=None, date_to=None, product_type=None):
#         """Get dashboard data from materialized view"""
#         self.refresh_materialized_view()
#         domain = []
        
#         if date_from:
#             domain.append(('date_from', '>=', date_from))
#         if date_to:
#             domain.append(('date_to', '<=', date_to))
#         if product_type:
#             domain.append(('product_type', '=', product_type))
            
#         portfolios = self.search(domain)
        
#         # Aggregate data by product type
#         product_data = {}
#         for portfolio in portfolios:
#             product = portfolio.product_type
#             if product not in product_data:
#                 product_data[product] = {
#                     'product_type': dict(self._fields['product_type'].selection).get(product, product),
#                     'opening_portfolio': 0,
#                     'disbursements': 0,
#                     'principal_repaid': 0,
#                     'interest_earned': 0,
#                     'closing_portfolio': 0,
#                     'change_percentage': 0.0
#                 }
                
#             product_data[product]['opening_portfolio'] += float_round(portfolio.opening_portfolio, precision_digits=2)
#             product_data[product]['disbursements'] += float_round(portfolio.disbursements, precision_digits=2)
#             product_data[product]['principal_repaid'] += float_round(portfolio.principal_repaid, precision_digits=2)
#             product_data[product]['interest_earned'] += float_round(portfolio.interest_earned, precision_digits=2)
#             product_data[product]['closing_portfolio'] += float_round(portfolio.closing_portfolio, precision_digits=2)
#             product_data[product]['change_percentage'] = float_round(portfolio.change_percentage, precision_digits=2)
        
#         # Calculate totals
#         total_opening = sum(float_round(data['opening_portfolio'], precision_digits=2) for data in product_data.values())
#         total_closing = sum(float_round(data['closing_portfolio'], precision_digits=2) for data in product_data.values())
#         total_change = 0.0
#         if total_opening:
#             total_change = float_round(((total_closing - total_opening) / total_opening) * 100, precision_digits=2)
        
#         return {
#             'product_data': product_data,
#             'total_opening': float_round(total_opening, precision_digits=2),
#             'total_disbursements': float_round(sum(data['disbursements'] for data in product_data.values()), precision_digits=2),
#             'total_principal_repaid': float_round(sum(data['principal_repaid'] for data in product_data.values()), precision_digits=2),
#             'total_interest_earned': float_round(sum(data['interest_earned'] for data in product_data.values()), precision_digits=2),
#             'total_closing': float_round(total_closing, precision_digits=2),
#             'total_change_percentage': total_change
#         }

#     @api.model
#     def get_filter_options(self):
#         """Get filter options for dashboard"""
#         currencies = self.env['res.currency'].search([])
        
#         return {
#             'currencies': currencies.read(['id', 'name', 'symbol']),
#             'product_types': [
#                 {'id': 'ordinary', 'name': 'Ordinary Savings'},
#                 {'id': 'fixed_deposit', 'name': 'Fixed Deposit'},
#                 {'id': 'premium', 'name': 'Premium Savings'},
#                 {'id': 'regular', 'name': 'Regular Savings'},
#                 {'id': 'youth', 'name': 'Youth Savings'}
#             ]
#         }

#     @api.model
#     def generate_snapshot_report(self, date_from=None, date_to=None, product_type=None):
#         """Generate snapshot report"""
#         self.refresh_materialized_view()
#         report_data = self.get_dashboard_data(date_from, date_to, product_type)
        
#         return {
#             'type': 'ir.actions.report',
#             'report_name': 'my_hostel.loan_portfolio2_report_template',
#             'report_type': 'qweb-pdf',
#             'data': {
#                 'report_data': report_data,
#                 'date_from': date_from,
#                 'date_to': date_to,
#                 'product_type': dict(self._fields['product_type'].selection).get(product_type, product_type) if product_type else None,
#                 'datetime': datetime,
#             },
#             'context': {
#                 'active_model': 'loan.portfolio2',
#                 'report_data': report_data,
#                 'date_from': date_from,
#                 'date_to': date_to,
#                 'product_type': dict(self._fields['product_type'].selection).get(product_type, product_type) if product_type else None,
#                 'datetime': datetime,
#             }
#         }

# class LoanPortfolio2Line(models.Model):
#     _name = 'loan.portfolio2.line'
#     _description = 'Loan Portfolio Line'

#     portfolio_id = fields.Many2one('loan.portfolio2', string='Portfolio', required=True, ondelete='cascade')
#     product_name = fields.Char(string='Product Name', required=True)
#     opening_portfolio = fields.Monetary(string='Opening Portfolio', currency_field='currency_id')
#     disbursements = fields.Monetary(string='Disbursements', currency_field='currency_id')
#     principal_repaid = fields.Monetary(string='Principal Repaid', currency_field='currency_id')
#     interest_earned = fields.Monetary(string='Interest Earned', currency_field='currency_id')
#     closing_portfolio = fields.Monetary(string='Closing Portfolio', currency_field='currency_id')
#     change_percentage = fields.Float(string='% Change', compute='_compute_change_percentage', store=True)
#     currency_id = fields.Many2one('res.currency', related='portfolio_id.currency_id', store=True)

#     @api.depends('opening_portfolio', 'closing_portfolio')
#     def _compute_change_percentage(self):
#         for line in self:
#             if line.opening_portfolio:
#                 change = line.closing_portfolio - line.opening_portfolio
#                 line.change_percentage = (change / line.opening_portfolio) * 100
#             else:
#                 line.change_percentage = 0.0