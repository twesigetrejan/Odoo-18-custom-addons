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
                        dormancy_period=90, balance_threshold=None, as_of_date=None):
        """Get filtered metrics with date filtering"""
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
        
        # Apply date filtering if specified
        if as_of_date:
            as_of_date = fields.Date.from_string(as_of_date)
            filtered_accounts = filtered_accounts.filtered(
                lambda a: not a.last_transaction_date or a.last_transaction_date.date() <= as_of_date
            )
        
        # Apply dormancy and balance filters
        fully_filtered_accounts = filtered_accounts.filtered(
            lambda a: a.days_idle >= dormancy_period and 
                    a.balance >= balance_threshold
        )
         # Get dormant accounts from the fully filtered set
        dormant_accounts = fully_filtered_accounts.filtered(
            lambda a: a.days_idle >= dormancy_period
        )
        # Prepare account details
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
        
    # ... rest of your existing method ...
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
        """Generate SVG chart for savings products similar to loan model approach"""
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
            chart_height = 500  # Increased height to accommodate title
            bar_width = 100
            gap = 40
            top_margin = 40  # Space for title
            bottom_margin = 80  # Space for x-axis labels
            
            # Calculate maximum balance for scaling
            max_value = max(bal for _, bal in sorted_products) if sorted_products else 1
            
            # Calculate available height for bars
            available_height = chart_height - top_margin - bottom_margin
            
            # Base Y position (chart bottom minus bottom margin)
            base_y = chart_height - bottom_margin
            
            # Product display names
            product_names = {
                'ordinary': 'Ordinary',
                'fixed_deposit': 'Fixed Deposit',
                'premium': 'Premium',
                'regular': 'Regular',
                'youth': 'Youth',
            }
            
            # Colors for each product type
            colors = ['#36A2EB', '#FF6384', '#FFCE56', '#4BC0C0', '#9966FF']
            
            # Generate SVG content
            svg_content = f"""
            <svg width="100%" height="{chart_height}" viewBox="0 0 {chart_width} {chart_height}" font-family="Arial, sans-serif">
                <!-- Background -->
                <rect width="100%" height="100%" fill="#f8f9fa"/>
                
                <!-- Chart title -->
                <text x="{chart_width/2}" y="{top_margin/2}" 
                    text-anchor="middle" font-size="16" font-weight="bold">
                    Balance by Product Type
                </text>
                
                <!-- X-axis line -->
                <line x1="50" y1="{base_y}" x2="{chart_width - 50}" y2="{base_y}" 
                    stroke="#495057" stroke-width="2"/>
            """
            
            # Add bars for each product
            for i, (product_type, balance) in enumerate(sorted_products):
                # Calculate bar height
                bar_height = (balance / max_value) * available_height
                
                # Calculate x position (centered with gaps)
                x_pos = 50 + i * (bar_width + gap)
                
                # Add bar
                svg_content += f"""
                <!-- {product_type} bar -->
                <rect x="{x_pos}" y="{base_y - bar_height}" 
                    width="{bar_width}" height="{bar_height}" 
                    fill="{colors[i % len(colors)]}" rx="5" ry="5"/>
                """
                
                # Add product label above bar
                svg_content += f"""
                <!-- {product_type} label -->
                <text x="{x_pos + bar_width/2}" y="{base_y - bar_height - 15}" 
                    text-anchor="middle" fill="#212529" font-size="12" font-weight="bold">
                    {product_names.get(product_type, product_type)}
                </text>
                """
                
                # Add value label below bar
                svg_content += f"""
                <!-- {product_type} value -->
                <text x="{x_pos + bar_width/2}" y="{base_y + 20}" 
                    text-anchor="middle" fill="#212529" font-size="12">
                    {'{:,.0f}'.format(balance)} UGX
                </text>
                """
            
            # Add Y-axis indicators
            svg_content += f"""
                <!-- Y-axis indicators -->
                <line x1="50" y1="{top_margin}" x2="50" y2="{base_y}" 
                    stroke="#495057" stroke-width="1" stroke-dasharray="5,5"/>
                <text x="40" y="{top_margin + 15}" text-anchor="end" 
                    fill="#495057" font-size="10">
                    {'{:,.0f}'.format(max_value)}
                </text>
                <text x="40" y="{base_y}" text-anchor="end" 
                    fill="#495057" font-size="10">
                    0
                </text>
            </svg>
            """
            
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
                        dormancy_period=90, balance_threshold=None,  as_of_date=None):
        """Generate PDF report for savings dashboard"""
        report_data = self.get_filtered_metrics(
            member_filter, product_filter, portfolio_filter, 
            dormancy_period, balance_threshold, as_of_date
        )
        
        # Generate chart using the same approach as loans model
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
        # Use context date if provided, otherwise use today's date
        context_date = self.env.context.get('as_of_date')
        reference_date = fields.Date.from_string(context_date) if context_date else date.today()
        
        for rec in self:
            if rec.last_transaction_date:
                rec.days_idle = (reference_date - rec.last_transaction_date.date()).days
            else:
                rec.days_idle = 0

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