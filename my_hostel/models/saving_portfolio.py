from odoo import models, fields, api
from datetime import date, datetime
import base64
import io
import logging
_logger = logging.getLogger(__name__)

try:
    import matplotlib.pyplot as plt
    import matplotlib
    matplotlib.use('Agg')
except ImportError:
    plt = None


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
    ], string='Portfolio Name', required=True)
    
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
    def get_filter_options(self):
        """Get filter options for the dashboard"""
        accounts = self.env['saving.details'].search([])
        
        members = list(set(accounts.mapped('member_name')))
        members.sort()
        
        product_types = list(set(accounts.mapped('product_type')))
        product_types.sort()
        
        portfolios = list(set(accounts.mapped('portfolio_id.portfolio_code')))
        portfolios.sort()
        
        return {
            'members': members,
            'product_types': product_types,
            'portfolios': portfolios
        }

    @api.model
    def get_filtered_metrics(self, member_filter=None, product_filter=None, portfolio_filter=None, 
                        dormancy_period=90, balance_threshold=None):
        """Get filtered metrics for dashboard"""
        domain = []
        
        if member_filter:
            domain.append(('member_name', '=', member_filter))
        if product_filter:
            domain.append(('product_type', '=', product_filter))
        if portfolio_filter:
            domain.append(('portfolio_id.portfolio_code', '=', portfolio_filter))
        
        # Get ALL accounts in database (for total counts)
        all_accounts = self.env['saving.details'].search([])
        
        # Get accounts matching member/product/portfolio filters
        filtered_accounts = self.env['saving.details'].search(domain)
        
        # Apply dormancy and balance filters to the filtered accounts
        fully_filtered_accounts = filtered_accounts.filtered(
            lambda a: a.days_idle >= dormancy_period and 
                    a.balance >= balance_threshold
        )
        
        # Get dormant accounts from the fully filtered set
        dormant_accounts = fully_filtered_accounts.filtered(
            lambda a: a.days_idle >= dormancy_period
        )
        
        # Prepare account details for display (respecting all filters)
        account_details = []
        for account in fully_filtered_accounts:
            account_details.append({
                'id': account.id,
                'member_id': account.member_id,
                'member_name': account.member_name,
                'product_type': account.product_type,
                'portfolio': account.portfolio_id.portfolio_code,
                'balance': account.balance,
                'days_idle': account.days_idle,
                'last_transaction_date': account.last_transaction_date.strftime('%Y-%m-%d') if account.last_transaction_date else '',
                'is_dormant': account.days_idle >= dormancy_period,
                'meets_balance_threshold': account.balance >= balance_threshold
            })
        
        # Calculate balance by product type for the filtered accounts
        product_balances = {}
        for account in fully_filtered_accounts:
            product_type = account.product_type
            if product_type not in product_balances:
                product_balances[product_type] = 0
            product_balances[product_type] += account.balance
        
        return {
            # Unfiltered totals (entire database)
            'total_accounts': len(all_accounts),
            'total_balances': sum(all_accounts.mapped('balance')),
            
            # Accounts matching member/product/portfolio filters
            'filtered_accounts': len(filtered_accounts),
            
            # Accounts matching ALL filters (including dormancy and balance)
            'fully_filtered_accounts': len(fully_filtered_accounts),
            'filtered_dormant_accounts': len(dormant_accounts),
            'filtered_dormant_balances': sum(dormant_accounts.mapped('balance')),
            'filtered_dormant_percentage': (len(dormant_accounts) / len(all_accounts)) * 100 if all_accounts else 0,
            
            # For backward compatibility
            'dormant_accounts': len(dormant_accounts),
            'dormant_balances': sum(dormant_accounts.mapped('balance')),
            'low_balance_accounts': len(fully_filtered_accounts),
            
            # For client-side display
            'account_details': account_details,
            'product_balances': product_balances
        }
        
        
    def generate_svg_chart(self, product_balances):
        """Generate SVG chart showing Balance by Product Type without matplotlib"""
        if not product_balances:
            return None
        
        try:
            # Sort products by balance (descending)
            sorted_products = sorted(
                product_balances.items(),
                key=lambda item: item[1],
                reverse=True
            )
            
            # Chart dimensions
            chart_width = 600
            chart_height = 400
            bar_height = 40
            gap = 20
            left_margin = 200  # Space for product labels
            top_margin = 50
            bottom_margin = 50
            
            # Calculate maximum balance for scaling
            max_balance = max(bal for _, bal in sorted_products) or 1
            
            # Product type display names
            product_names = {
                'ordinary': 'Ordinary Savings',
                'fixed_deposit': 'Fixed Deposit',
                'premium': 'Premium Savings',
                'regular': 'Regular Savings',
                'youth': 'Youth Savings',
            }
            
            # Generate SVG content
            svg_content = f"""
            <svg width="100%" height="{chart_height}" viewBox="0 0 {chart_width} {chart_height}" font-family="Arial, sans-serif">
                <!-- Background -->
                <rect width="100%" height="100%" fill="#f8f9fa"/>
                
                <!-- Chart title -->
                <text x="{chart_width/2}" y="{top_margin/2}" text-anchor="middle" font-size="16" font-weight="bold">
                    Balance by Product Type
                </text>
                
                <!-- X-axis line -->
                <line x1="{left_margin}" y1="{chart_height - bottom_margin}" 
                    x2="{chart_width}" y2="{chart_height - bottom_margin}" 
                    stroke="#495057" stroke-width="2"/>
            """
            
            # Colors for each bar
            colors = ['#36A2EB', '#FF6384', '#FFCE56', '#4BC0C0', '#9966FF']
            
            # Add bars for each product
            for i, (product_type, balance) in enumerate(sorted_products):
                y_pos = top_margin + i * (bar_height + gap)
                bar_width = (balance / max_balance) * (chart_width - left_margin - 20)
                
                # Product label
                svg_content += f"""
                <text x="{left_margin - 10}" y="{y_pos + bar_height/2}" 
                    text-anchor="end" font-size="12" fill="#212529">
                    {product_names.get(product_type, product_type)}
                </text>
                """
                
                # Bar
                svg_content += f"""
                <rect x="{left_margin}" y="{y_pos}" 
                    width="{bar_width}" height="{bar_height}" 
                    fill="{colors[i % len(colors)]}" rx="3" ry="3"/>
                """
                
                # Value label
                svg_content += f"""
                <text x="{left_margin + bar_width + 10}" y="{y_pos + bar_height/2}" 
                    text-anchor="start" font-size="11" fill="#212529">
                    {balance:,.0f} UGX
                </text>
                """
            
            # Add Y-axis indicators
            svg_content += f"""
                <!-- Y-axis indicators -->
                <line x1="{left_margin}" y1="{top_margin}" 
                    x2="{left_margin}" y2="{chart_height - bottom_margin}" 
                    stroke="#495057" stroke-width="1" stroke-dasharray="5,5"/>
                    
                <text x="{left_margin - 10}" y="{top_margin + 15}" 
                    text-anchor="end" font-size="10" fill="#495057">
                    {max_balance:,.0f}
                </text>
                
                <text x="{left_margin - 10}" y="{chart_height - bottom_margin}" 
                    text-anchor="end" font-size="10" fill="#495057">
                    0
                </text>
            """
            
            svg_content += "</svg>"
            return svg_content
            
        except Exception as e:
            _logger.error("Failed to generate SVG chart: %s", str(e))
            return None

    def _generate_chart(self, product_balances):
        """Generate SVG chart showing Balance by Product Type"""
        if not plt or not product_balances:
            return None
            
        try:
            # Convert product balances to a sorted list for consistent ordering
            sorted_products = sorted(
                product_balances.items(),
                key=lambda item: item[1],  # Sort by balance
                reverse=True
            )
            
            product_type_names = {
                'ordinary': 'Ordinary Savings',
                'fixed_deposit': 'Fixed Deposit',
                'premium': 'Premium Savings',
                'regular': 'Regular Savings',
                'youth': 'Youth Savings',
            }
            
            products = []
            balances = []
            
            for product_type, balance in sorted_products:
                products.append(product_type_names.get(product_type, product_type))
                balances.append(balance)
            
            if not balances:  # No data to display
                return None
                
            fig, ax = plt.subplots(figsize=(10, 6))
            
            # Use a colormap for better visual distinction
            colors = plt.cm.tab20c(range(len(balances)))
            
            bars = ax.barh(products, balances, color=colors)
            
            # Add value labels
            for bar, balance in zip(bars, balances):
                width = bar.get_width()
                ax.text(
                    width + (max(balances) * 0.01), 
                    bar.get_y() + bar.get_height()/2,
                    f'{balance:,.0f} UGX',
                    ha='left', 
                    va='center',
                    fontsize=10
                )
            
            ax.set_title(
                'Balance by Product Type', 
                fontsize=16, 
                fontweight='bold', 
                pad=20
            )
            ax.set_xlabel('Balance (UGX)', fontsize=12)
            ax.set_ylabel('Product Type', fontsize=12)
            
            # Format x-axis as currency
            ax.xaxis.set_major_formatter(
                plt.FuncFormatter(lambda x, p: f'{x:,.0f}')
            )
            
            # Adjust layout
            plt.tight_layout()
            
            # Save as SVG
            buffer = io.StringIO()
            plt.savefig(
                buffer, 
                format='svg', 
                bbox_inches='tight', 
                facecolor='white',
                transparent=False
            )
            plt.close()
            
            svg_content = buffer.getvalue()
            buffer.close()
            
            return svg_content
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return None

    @api.model
    def generate_pdf_report(self, member_filter=None, product_filter=None, portfolio_filter=None, 
                        dormancy_period=90, balance_threshold=None):
        """Generate PDF report for savings dashboard"""
        report_data = self.get_filtered_metrics(
            member_filter, product_filter, portfolio_filter, 
            dormancy_period, balance_threshold
        )
        
        # Generate chart using the new SVG method
        svg_chart = self.generate_svg_chart(report_data.get('product_balances', {}))
        
        return {
            'type': 'ir.actions.report',
            'report_name': 'my_hostel.savings_portfolio_report_template',
            'report_type': 'qweb-pdf',
            'data': {
                'report_data': report_data,
                'member_filter': member_filter,
                'product_filter': product_filter,
                'portfolio_filter': portfolio_filter,
                'dormancy_period': dormancy_period,
                'balance_threshold': balance_threshold,
                'svg_chart': svg_chart,
                'datetime': datetime,
            },
            'context': {
                'active_model': 'saving.portfolio',
                'report_data': report_data,
                'member_filter': member_filter,
                'product_filter': product_filter,
                'portfolio_filter': portfolio_filter,
                'dormancy_period': dormancy_period,
                'balance_threshold': balance_threshold,
                'svg_chart': svg_chart,
                'datetime': datetime,
            }
        }


class SavingDetails(models.Model):
    _name = 'saving.details'
    _description = 'Individual Saving Account Details'
    _rec_name = 'member_name'
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