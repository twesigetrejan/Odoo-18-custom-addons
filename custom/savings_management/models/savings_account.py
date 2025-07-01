from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)
BATCH_SIZE = 500

class SavingsAccount(models.Model):
    _name = 'sacco.savings.account'
    _description = 'SACCO Savings Account'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('ID', default='/', copy=False)
    member_id = fields.Many2one('res.partner', string='Member', required=True, domain=[('is_sacco_member', '=', True)])
    product_id = fields.Many2one('sacco.savings.product', string='Savings Product', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, tracking=True, default=lambda self: self._get_default_currency())
    balance = fields.Float(string='Current Balance', default=0.0, digits='Account', compute='_compute_balance')
    minimum_balance = fields.Float(related='product_id.minimum_balance', string='Minimum Balance', readonly=True)
    bypass_minimum_balance = fields.Boolean(
        string='Bypass Minimum Balance',
        default=False,
        help='When enabled, minimum balance constraints are ignored for withdrawal requests.'
    )
    account_journal_lines = fields.One2many('sacco.journal.account.line', 'savings_account_id', string='Account Journal lines')
    period = fields.Selection(related='product_id.period', string='Interest Period')
    interest_rate = fields.Float(related='product_id.interest_rate', string='Annual Interest Rate (%)')
    initial_deposit_date = fields.Date('Initial Deposit Date', default=fields.Date.today() , copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ], string='State', default='draft')
    last_interest_date = fields.Date(string='Last Interest Computation Date')
    
    statement_mongo_db_id = fields.Char('Savings Statement Mongodb Id', copy=False)
    last_statement_sync_date = fields.Date(
        string='Last Statement Sync Date',
        readonly=True,
        help='Tracks the last time a statement was synced with the external system'
    )
    journal_account_lines = fields.One2many('sacco.journal.account.line', 'savings_account_id', string='Journal Account Lines')
    
    @api.model
    def create(self, vals):
        if vals.get('name', '/') == '/':
            member = self.env['res.partner'].browse(vals['member_id'])
            print(member)
            if not member.member_id:
                raise ValidationError("Member Id is required to create a savings account.")
            seq = self.env['ir.sequence'].next_by_code('sacco.savings.account')
            if not seq:
                raise ValidationError("Could not retrieve sequence for 'sacco.savings.account'.")
            year = fields.Date.today().year
            vals['name'] = f"SAV/{member.member_id}/{year}/{seq.split('/')[-1]}"
        
        existing_account = self.search([
            ('member_id', '=', vals.get('member_id')),
            ('product_id', '=', vals.get('product_id')),
            ('currency_id', '=', vals.get('currency_id')),
        ])
        if vals.get('product_id') and not vals.get('currency_id'):
            product = self.env['sacco.savings.product'].browse(vals['product_id'])
            vals['currency_id'] = product.currency_id.id
        if existing_account:
            raise ValidationError(_("A savings account with this product already exists for this member."))
            
        return super(SavingsAccount, self).create(vals)
    
    def action_refresh_journal_lines(self):
        """Refresh journal account line view"""
        self.env.cr.execute("SELECT 1 FROM pg_matviews WHERE matviewname = 'sacco_journal_account_line'")
        if self.env.cr.fetchone():
            self.env.cr.execute("REFRESH MATERIALIZED VIEW sacco_journal_account_line")
            _logger.info("Successfully refreshed sacco_journal_account_line materialized view")
        else:
            _logger.warning("Materialized view sacco_journal_account_line does not exist")
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }   
 
    @api.model
    def _get_default_currency(self):
        """Get default currency from product if available, otherwise company currency"""
        if self._context.get('default_product_id'):
            product = self.env['sacco.savings.product'].browse(self._context.get('default_product_id'))
            return product.currency_id
        return self.env.company.currency_id
       
    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.currency_id = self.product_id.currency_id

    @api.depends('product_id.currency_id')
    def _compute_currency_id(self):
        for record in self:
            if record.product_id:
                record.currency_id = record.product_id.currency_id   
            
    @api.depends('account_journal_lines')
    def _compute_balance(self):
        """Compute current balance from most recent journal line"""
        for account in self:
            # Using SQL for better performance with large datasets
            self.env.cr.execute("""
                SELECT closing_balance FROM sacco_journal_account_line
                WHERE savings_account_id = %s
                ORDER BY date DESC, id DESC
                LIMIT 1
            """, (account.id,))
            
            result = self.env.cr.fetchone()
            account.balance = result[0] if result else 0.0
    
    def compute_next_interest_line(self):
        self.ensure_one()
        if self.state != 'active':
            raise ValidationError(_("Interest can only be computed for active accounts."))
        
        today = fields.Date.today()
        if not self.last_interest_date:
            self.last_interest_date = self.initial_deposit_date or today
            
        if self.period == 'daily':
            next_date = self.last_interest_date + relativedelta(days=1)
        elif self.period == 'weekly':
            next_date = self.last_interest_date + relativedelta(weeks=1)
        elif self.period == 'monthly':
            next_date = self.last_interest_date + relativedelta(months=1)
        elif self.period == 'semi_annually':
            next_date = self.last_interest_date + relativedelta(months=6)
        elif self.period == 'annually':
            next_date = self.last_interest_date + relativedelta(years=1)
            
        print(f"The next interest date is {next_date}")
            
        if next_date > today:
            raise ValidationError(_(f"Next interest computation date is on {next_date}."))
        
        days = (today - self.last_interest_date).days
        
        print(f"The number of days since the last interest is {days}")
        
        interest_amount = self._calculate_interest(days)
        
        transaction = self.env['savings.transaction'].create({
            'savings_account_id': self.id,
            'transaction_type': 'interest',
            'amount': interest_amount,
            'transaction_date': today,
            'status': 'pending',
        })
        
        transaction.action_confirm_transaction()
        
        self.last_interest_date = today
        return True
    
    def _calculate_interest(self, days):
        if self.period == 'daily':
            interest = self.balance * (self.interest_rate / 100 / 365) * days
        elif self.period == 'weekly':
            number_of_weeks = (days / 7)
            interest = self.balance * (self.interest_rate /100 / 52) * number_of_weeks
        elif self.period == 'monthly':
            number_of_months = (days / 30)  # Using 30 days as approximation for a month
            interest = self.balance * (self.interest_rate /100 / 12) * number_of_months
        elif self.period == 'semi_annually':
            number_of_half_years = (days / 182.5)  # Using 365/2 days as approximation for 6 months
            interest = self.balance * (self.interest_rate /100 / 2) * number_of_half_years
        elif self.period == 'annually':
            number_of_years = (days / 365)
            interest = self.balance * (self.interest_rate /100) * number_of_years
        return round(interest, 2)
            
    @api.constrains('member_id', 'product_id')
    def check_unique_product_for_member(self):
        for record in self:
            existing_accounts = self.search([
                ('member_id', '=', record.member_id.id),
                ('product_id', '=', record.product_id.id),
                ('id', '!=', record.id)
            ])
            if existing_accounts:
                raise ValidationError(_("A savings account with this product already exists for this member."))
            
    def action_activate_savings_account(self):
        self.state = 'active'
        
    def action_deactivate_savings_account(self):
        self.state = 'inactive'
    
    def action_deactivate_minimum_balance(self):
        """Set bypass_minimum_balance to True to ignore minimum balance constraints."""
        self.ensure_one()
        self.bypass_minimum_balance = True

    def action_activate_minimum_balance(self):
        """Set bypass_minimum_balance to False to enforce minimum balance constraints."""
        self.ensure_one()
        self.bypass_minimum_balance = False
        
    @api.model    
    def compute_all_next_interest_line(self):
        _logger.info("Starting compute_all_next_interest_line")
        active_accounts = self.search([('state', '=', 'active')])
        for account in active_accounts:
            try:
                _logger.info(f"Processing account {account.name}")
                account.compute_next_interest_line()
                self.env.cr.commit()  
                _logger.info(f"Successfully processed account {account.name}")
            except ValidationError as ve:
                _logger.warning(f"ValidationError for account {account.name}: {str(ve)}")
                self.env.cr.rollback()  
            except Exception as e:
                _logger.error(f"Error processing account {account.name}: {str(e)}")
                self.env.cr.rollback()  
        _logger.info("Finished compute_all_next_interest_line")
        return True  
    
    
    def unlink(self):
        for account in self:
            if account.state != 'draft':
                raise ValidationError(_("You can only delete draft savings accounts."))
        return super(SavingsAccount, self).unlink()
    
    def _post_statement_to_external_system(self, start_date=None, end_date=None):
        """Posts or updates statement in the external system."""
        try:
            _logger.info(f"Starting statement sync for account {self.name}")

            if not start_date:
                start_date = fields.Date.today() - timedelta(days=360)
            end_date = end_date or fields.Date.today()

            wizard_obj = self.env['sacco.savings.statement.wizard']
            wizard = wizard_obj.create({
                'partner_id': self.member_id.id,
                'product_id': self.product_id.id,
                'currency_id': self.currency_id.id,
                'start_date': start_date,
                'end_date': end_date,
                'request_date': end_date,
            })

            token = wizard._get_authentication_token()
            if not token:
                _logger.error(f"Failed to get auth token for account {self.name}")
                return False

            transactions = wizard._get_transactions_in_batches(self)
            _logger.info(f"Found {len(transactions)} transactions for account {self.name}")

            if transactions:
                statement_data = wizard._prepare_statement_data(self, transactions)
                headers = wizard._get_request_headers()
                
                result = wizard._post_or_update_statement(self, statement_data, token)

                if isinstance(result, dict) and result.get('type') == 'ir.actions.client':
                    self.last_statement_sync_date = fields.Date.today()
                    self.env.cr.commit() 
                    _logger.info(f"Successfully synced statement for account {self.name}")
                    return True

            _logger.info(f"No transactions to sync for account {self.name}")
            return True
        
        except Exception as e:
            _logger.error(f"Error syncing statement for account {self.name}: {str(e)}")
            return False
        
    
    def _trigger_statement_sync(self):
        """ Triggers statement sync """
        try:
            self._post_statement_to_external_system()
        except Exception as e:
            _logger.error(f"Error syncing statement for account {self.name}: {str(e)}")
            
    @api.model
    def sync_all_pending_statements(self):
        """Sync all pending statements for active accounts in batches."""
        _logger.info("================ Starting sync of pending statements ================")

        offset = 0
        total_accounts = self.search_count([('state', '=', 'active')])

        _logger.info(f"Total active accounts to process: {total_accounts}")

        while offset < total_accounts:
            accounts = self.search(
                [('state', '=', 'active')],
                offset=offset,
                limit=BATCH_SIZE
            )

            _logger.info(f"Processing batch: {offset + 1} to {offset + len(accounts)}")

            for account in accounts:
                try:
                    account._post_statement_to_external_system()
                    self.env.cr.commit()  
                    _logger.info(f"Successfully synced statement for account: {account.name}")
                except Exception as e:
                    self.env.cr.rollback() 
                    _logger.error(f"Failed to sync statement for account {account.name}: {str(e)}")

            offset += len(accounts)

        _logger.info("================ Completed sync of pending statements ================")

    def refresh_journal_account_lines(self):
        """Refresh the journal account lines materialized view"""
        self.env.cr.execute("REFRESH MATERIALIZED VIEW sacco_journal_account_line")
        return True
    
    def action_mass_sync_statements(self):
        """Mass action to sync statements for selected records"""
        if not self:
            raise ValidationError(_("No records selected for statement synchronization."))
        
        _logger.info(f"Starting mass statement sync for {len(self)} accounts")
        
        for account in self:
            try:
                if account.state == 'active':
                    account._post_statement_to_external_system()
                    self.env.cr.commit()
                    _logger.info(f"Successfully synced statement for account {account.name}")
                else:
                    _logger.warning(f"Skipping account {account.name} - not active")
            except Exception as e:
                self.env.cr.rollback()
                _logger.error(f"Failed to sync statement for account {account.name}: {str(e)}")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Statement Sync'),
                'message': _('%d statements processed successfully') % len(self),
                'type': 'success',
                'sticky': False,
            }
        }