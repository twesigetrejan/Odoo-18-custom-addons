from odoo import models, fields, api
from datetime import date
import base64
import io
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
    def get_idle_distribution(self, dormancy_period=None, balance_threshold=None, 
                            member_filter=None, product_filter=None, portfolio_filter=None):
        """Get distribution of accounts by idle days with filters"""
        domain = []
        
        if member_filter:
            domain.append(('member_name', '=', member_filter))
        if product_filter:
            domain.append(('product_type', '=', product_filter))
        if portfolio_filter:
            domain.append(('portfolio_id.portfolio_code', '=', portfolio_filter))
            
        accounts = self.env['saving.details'].search(domain)
        
        distribution = {'30': 0, '60': 0, '120': 0, '160+': 0}
        
        for acc in accounts:
            # Apply dormancy and balance filters for counting
            if dormancy_period and acc.days_idle < dormancy_period:
                continue
            if balance_threshold and acc.balance >= balance_threshold:
                continue
                
            if acc.days_idle >= 160:
                distribution['160+'] += 1
            elif acc.days_idle >= 120:
                distribution['120'] += 1
            elif acc.days_idle >= 60:
                distribution['60'] += 1
            elif acc.days_idle >= 30:
                distribution['30'] += 1
        
        return distribution

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
    def get_overview_metrics(self, dormancy_period=90, balance_threshold=None):
        """Get overview metrics for dashboard"""
        accounts = self.env['saving.details'].search([])
        
        total_accounts = len(accounts)
        total_balances = sum(accounts.mapped('balance'))
        dormant_accounts = len(accounts.filtered(lambda a: a.days_idle >= dormancy_period))
        dormant_balances = sum(a.balance for a in accounts.filtered(lambda a: a.days_idle >= dormancy_period))
        
        metrics = {
            'total_accounts': total_accounts,
            'total_balances': total_balances,
            'dormant_accounts': dormant_accounts,
            'dormant_balances': dormant_balances,
            'dormant_percentage': (dormant_accounts / total_accounts) * 100 if total_accounts else 0
        }
        
        if balance_threshold is not None:
            low_balance_accounts = len(accounts.filtered(lambda a: a.balance < balance_threshold))
            metrics['low_balance_accounts'] = low_balance_accounts
            
        return metrics

    @api.model
    def get_filtered_metrics(self, member_filter=None, product_filter=None, portfolio_filter=None, dormancy_period=1, balance_threshold=10000):
        """Get filtered metrics for dashboard with all filters properly applied"""
        domain = []
        
        # Apply member/product/portfolio filters
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
        for account in fully_filtered_accounts:  # Changed to use fully_filtered_accounts
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

    def _generate_chart(self, report_data):
        """Generate SVG chart showing Balance by Product Type"""
        if not plt:
            return None
            
        try:
            # Get product balances from report data
            product_balances = report_data.get('product_balances', {})
            
            if not product_balances:
                return None
            
            # Product type display names
            product_type_names = {
                'ordinary': 'Ordinary Savings',
                'fixed_deposit': 'Fixed Deposit',
                'premium': 'Premium Savings',
                'regular': 'Regular Savings',
                'youth': 'Youth Savings',
            }
            
            # Prepare data for chart
            products = []
            balances = []
            
            for product_type, balance in product_balances.items():
                products.append(product_type_names.get(product_type, product_type))
                balances.append(balance)
            
            # Create horizontal bar chart for better readability
            fig, ax = plt.subplots(figsize=(10, 6))
            
            bars = ax.barh(products, balances, color=['#36A2EB', '#FF6384', '#FFCE56', '#4BC0C0', '#9966FF'])
            
            # Add value labels on bars
            for bar, balance in zip(bars, balances):
                width = bar.get_width()
                ax.text(width + max(balances) * 0.01, bar.get_y() + bar.get_height()/2,
                    f'{balance:,.0f} UGX',
                    ha='left', va='center', fontweight='bold')
            
            ax.set_title('Balance by Product Type', fontsize=16, fontweight='bold', pad=20)
            ax.set_xlabel('Balance (UGX)', fontsize=12)
            ax.set_ylabel('Product Type', fontsize=12)
            
            # Format x-axis to show currency
            ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:,.0f}'))
            
            # Adjust layout to prevent label cutoff
            plt.tight_layout()
            
            # Convert to SVG
            buffer = io.StringIO()
            plt.savefig(buffer, format='svg', bbox_inches='tight', facecolor='white')
            buffer.seek(0)
            svg_content = buffer.getvalue()
            buffer.close()
            plt.close()
            
            return svg_content
            
        except Exception as e:
            return None
    
    @api.model
    def generate_pdf_report(self, member_filter=None, product_filter=None, portfolio_filter=None, dormancy_period=90, balance_threshold=None):
        """Generate PDF report for savings dashboard"""
        # Get filtered data
        report_data = self.get_filtered_metrics(member_filter, product_filter, portfolio_filter, dormancy_period, balance_threshold)
        
        # Generate chart
        svg_chart = self._generate_chart(report_data)
        
        # Prepare report context
        context = {
            'report_data': report_data,
            'member_filter': member_filter,
            'product_filter': product_filter,
            'portfolio_filter': portfolio_filter,
            'dormancy_period': dormancy_period,
            'balance_threshold': balance_threshold,
            'svg_chart': svg_chart,
        }
        
        return self.env.ref('my_hostel.savings_portfolio_report').report_action([], data=context)

    def _generate_chart(self, report_data):
        """Generate SVG chart for the report"""
        if not plt:
            return None
            
        try:
            # Create a simple bar chart
            fig, ax = plt.subplots(figsize=(8, 6))
            
            categories = ['Total Accounts', 'Dormant Accounts', 'Low Balance Accounts']
            values = [
                report_data.get('total_accounts', 0),
                report_data.get('dormant_accounts', 0),
                report_data.get('low_balance_accounts', 0)
            ]
            
            bars = ax.bar(categories, values, color=['#36A2EB', '#FF6384', '#FFCE56'])
            
            # Add value labels on bars
            for bar, value in zip(bars, values):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{int(value)}',
                       ha='center', va='bottom')
            
            ax.set_title('Savings Account Distribution', fontsize=16, fontweight='bold')
            ax.set_ylabel('Number of Accounts')
            
            # Rotate x-axis labels for better readability
            plt.xticks(rotation=45, ha='right')
            plt.tight_layout()
            
            # Convert to SVG
            buffer = io.StringIO()
            plt.savefig(buffer, format='svg', bbox_inches='tight')
            buffer.seek(0)
            svg_content = buffer.getvalue()
            buffer.close()
            plt.close()
            
            return svg_content
            
        except Exception as e:
            return None


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