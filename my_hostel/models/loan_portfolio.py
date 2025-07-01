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

    @api.model
    def get_filtered_metrics(self, member_filter=None, loan_product_filter=None):
        domain = []
        
        if member_filter:
            domain.append(('member', 'ilike', member_filter))
        
        if loan_product_filter:
            domain.append(('loan_product', 'ilike', loan_product_filter))
        
        loan_details = self.env['loan.details'].search(domain)
        
        if not loan_details:
            return {
                'total_disbursed': 0,
                'expected_outstanding': 0,
                'actual_outstanding': 0,
                'loan_count': 0,
                'loan_details': [],
            }
        
        total_disbursed = sum(loan.disbursed_amount for loan in loan_details)
        expected_outstanding = sum(loan.expected_outstanding for loan in loan_details)
        actual_outstanding = sum(loan.actual_outstanding for loan in loan_details)
        loan_count = len(loan_details)
        
        return {
            'total_disbursed': total_disbursed,
            'expected_outstanding': expected_outstanding,
            'actual_outstanding': actual_outstanding,
            'loan_count': loan_count,
            'loan_details': loan_details.read([
                'loan_id', 'member', 'loan_product', 'interest_rate',
                'disbursed_amount', 'expected_outstanding', 'actual_outstanding', 'start_date'
            ]),
        }

    @api.model
    def get_filter_options(self):
        """Return unique members and loan products for filter dropdowns."""
        loan_details = self.env['loan.details'].search([])
        
        members = list(set(loan.member for loan in loan_details if loan.member))
        loan_products = list(set(loan.loan_product for loan in loan_details if loan.loan_product))
        
        return {
            'members': sorted(members),
            'loan_products': sorted(loan_products),
        }

    @api.model
    def generate_pdf_report(self, member_filter=None, loan_product_filter=None):
        """Generate PDF report for loan portfolio data."""
        report_data = self.get_filtered_metrics(member_filter, loan_product_filter)
        
        # chart_data = {
        # 'labels': ['Expected', 'Actual'],
        # 'datasets': [{
        #     'label': 'Outstanding Amount (UGX)',
        #     'data': [
        #         report_data.get('expected_outstanding', 0),
        #         report_data.get('actual_outstanding', 0)
        #     ],
        #     'backgroundColor': ['#36A2EB', '#FF6384']
        #     }]
        # }
        svg_chart = self.generate_svg_chart(
        report_data.get('expected_outstanding', 0),
        report_data.get('actual_outstanding', 0)
        )
        
        return {
            'type': 'ir.actions.report',
            'report_name': 'my_hostel.loan_portfolio_report_template',
            'report_type': 'qweb-pdf',
            'data': {
                'report_data': report_data,
                # 'chart_data': chart_data, 
                'svg_chart': svg_chart,
                'member_filter': member_filter,
                'loan_product_filter': loan_product_filter,
            },
            'context': {
                'active_model': 'loan.portfolio',
                'report_data': report_data,
                # 'chart_data': chart_data, 
                'member_filter': member_filter,
                'loan_product_filter': loan_product_filter,
            }
        }
    def generate_svg_chart(self, expected, actual):
        """Generate properly spaced SVG chart with all labels"""
        max_value = max(expected, actual, 1)
        chart_width = 600
        chart_height = 500  # Increased height to accommodate title
        bar_width = 100
        gap = 40
        top_margin = 40  # Space for title
        bottom_margin = 80  # Space for x-axis labels
        
        # Calculate available height for bars
        available_height = chart_height - top_margin - bottom_margin
        
        # Calculate bar heights
        expected_height = (expected / max_value) * available_height
        actual_height = (actual / max_value) * available_height
        
        # Base Y position (chart bottom minus bottom margin)
        base_y = chart_height - bottom_margin
        
        return f"""
        <svg width="100%" height="{chart_height}" viewBox="0 0 {chart_width} {chart_height}" font-family="Arial, sans-serif">
            <!-- Background -->
            <rect width="100%" height="100%" fill="#f8f9fa"/>
            
            
            <!-- X-axis line -->
            <line x1="50" y1="{base_y}" x2="{chart_width - 50}" y2="{base_y}" stroke="#495057" stroke-width="2"/>
            
            <!-- Expected bar -->
            <rect x="150" y="{base_y - expected_height}" 
                width="{bar_width}" height="{expected_height}" 
                fill="#36A2EB" rx="5" ry="5"/>
            <!-- Expected bar top label -->
            <text x="{150 + bar_width/2}" y="{base_y - expected_height - 15}" 
                text-anchor="middle" fill="#212529" font-size="12" font-weight="bold">
                Expected
            </text>
            <!-- Expected value label -->
            <text x="{150 + bar_width/2}" y="{base_y + 20}" 
                text-anchor="middle" fill="#212529" font-size="12">
                {'{:,.0f}'.format(expected)} UGX
            </text>
            
            <!-- Actual bar -->
            <rect x="{150 + bar_width + gap}" y="{base_y - actual_height}" 
                width="{bar_width}" height="{actual_height}" 
                fill="#FF6384" rx="5" ry="5"/>
            <!-- Actual bar top label - NOW INCLUDED -->
            <text x="{150 + bar_width + gap + bar_width/2}" y="{base_y - actual_height - 15}" 
                text-anchor="middle" fill="#212529" font-size="12" font-weight="bold">
                Actual
            </text>
            <!-- Actual value label -->
            <text x="{150 + bar_width + gap + bar_width/2}" y="{base_y + 20}" 
                text-anchor="middle" fill="#212529" font-size="12">
                {'{:,.0f}'.format(actual)} UGX
            </text>
            
            <!-- Y-axis indicators -->
            <line x1="50" y1="{top_margin}" x2="50" y2="{base_y}" stroke="#495057" stroke-width="1" stroke-dasharray="5,5"/>
            <text x="40" y="{top_margin + 15}" text-anchor="end" fill="#495057" font-size="10">{'{:,.0f}'.format(max_value)}</text>
            <text x="40" y="{base_y}" text-anchor="end" fill="#495057" font-size="10">0</text>
        </svg>
        """

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