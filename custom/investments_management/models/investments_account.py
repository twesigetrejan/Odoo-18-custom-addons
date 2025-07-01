from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from dateutil.relativedelta import relativedelta
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

class InvestmentsAccount(models.Model):
    _name = 'sacco.investments.account'
    _description = 'SACCO Investments Account'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('ID', default='/', copy=False)
    member_id = fields.Many2one('res.partner', string='Member', required=True, domain=[('is_sacco_member', '=', True)])
    product_id = fields.Many2one('sacco.investments.product', string='Investments Product', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, 
        default=lambda self: self.env.company.currency_id,
        tracking=True)
    # Compute balances based on transactions
    cash_balance = fields.Float(string='Cash Balance', compute='_compute_balances', store=True, 
                              digits='Account', help="Uninvested funds available in the account")
    investment_balance = fields.Float(string='Investment Balance', compute='_compute_balances', store=True,
                                    digits='Account', help="Current market value of invested assets")
    total_profit = fields.Float(string='Total Profit Gained', compute='_compute_profit', store=True,
                                    digits='Account', help="Current market value of invested assets")
    total_balance = fields.Float(string='Total Account Value', compute='_compute_total_balance', store=True,
                               help="Total account value (cash + investments)")
    unrealized_gains = fields.Float(string='Unrealized Gains/Losses', compute='_compute_unrealized_gains',
                                  help="Current profit or loss on investments that haven't been sold")
    balance = fields.Float(string='Current Balance', default=0.0, digits='Account') 
    minimum_balance = fields.Float(related='product_id.minimum_balance', string='Minimum Balance', readonly=True)
    bypass_minimum_balance = fields.Boolean(
        string='Bypass Minimum Balance',
        default=False,
        help='When enabled, minimum balance constraints are ignored for withdrawal requests.'
    )
    transaction_ids = fields.One2many('sacco.investments.transaction', 'investments_account_id', string='Transactions')
    period = fields.Selection(related='product_id.period', string='Interest Period')
    interest_rate = fields.Float(related='product_id.interest_rate', string='Annual Interest Rate (%)')
    initial_deposit_date = fields.Date('Initial Deposit Date', default=fields.Date.today() , copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ], string='State', default='draft')
    last_interest_date = fields.Date(string='Last Interest Computation Date')
    update_statement = fields.Boolean(
        string='Allow Statement Update',
        default=False,
        tracking=True,
        help='Toggle to allow statement update to external system'
    )
    journal_account_lines = fields.One2many('sacco.investment.account.journal.line', 'investment_account_id',
                                            string='Journal Account Lines', readonly=True)
    
    
    statement_mongo_db_id = fields.Char('Investments Statement Mongodb Id', copy=False)
    last_statement_sync_date = fields.Date(
        string='Last Statement Sync Date',
        readonly=True,
        help='Tracks the last time a statement was synced with the external system'
    )
    
    @api.depends('pool_participant_ids.actual_invested_amount')
    def _compute_total_invested(self):
        for account in self:
            account.total_invested_amount = sum(account.pool_participant_ids.mapped('actual_invested_amount'))

    @api.depends('balance', 'total_invested_amount')
    def _compute_available_balance(self):
        for account in self:
            account.available_balance = account.balance - account.total_invested_amount   
            
    @api.depends('transaction_ids.amount', 'transaction_ids.status', 'transaction_ids.transaction_type')
    def _compute_profit(self):
        """Compute various profit metrics from confirmed transactions"""
        for account in self:
            interest_earned = 0.0
            
            # Get confirmed transactions
            confirmed_transactions = account.transaction_ids.filtered(
                lambda t: t.status == 'confirmed'
            )
            
            for transaction in confirmed_transactions:
                if transaction.transaction_type == 'interest':
                    interest_earned += transaction.amount
                    
            account.total_profit = interest_earned 
 
    
    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id and self.product_id.currency_id:
            self.currency_id = self.product_id.currency_id

    @api.depends('product_id.currency_id')
    def _compute_currency_id(self):
        for record in self:
            if record.product_id:
                record.currency_id = record.product_id.currency_id   
                        
    @api.model
    def create(self, vals):
        if vals.get('name', '/') == '/':
            member = self.env['res.partner'].browse(vals['member_id'])
            print(member)
            if not member.member_id:
                raise ValidationError("Member Id is required to create a investments account.")
            seq = self.env['ir.sequence'].next_by_code('sacco.investments.account')
            if not seq:
                raise ValidationError("Could not retrieve sequence for 'sacco.investments.account'.")
            year = fields.Date.today().year
            vals['name'] = f"INV/{member.member_id}/{year}/{seq.split('/')[-1]}"
        
        existing_account = self.search([
            ('member_id', '=', vals.get('member_id')),
            ('product_id', '=', vals.get('product_id')),
            ('currency_id', '=', vals.get('currency_id')),
        ])
        if existing_account:
            raise ValidationError(_("A investments account with this product already exists for this member."))
            
        return super(InvestmentsAccount, self).create(vals)
    
            
    @api.constrains('member_id', 'product_id')
    def check_unique_product_for_member(self):
        for record in self:
            existing_accounts = self.search([
                ('member_id', '=', record.member_id.id),
                ('product_id', '=', record.product_id.id),
                ('id', '!=', record.id)
            ])
            if existing_accounts:
                raise ValidationError(_("A investments account with this product already exists for this member."))
            
    def action_activate_investments_account(self):
        self.state = 'active'
        
    def action_deactivate_investments_account(self):
        self.state = 'inactive'

    def action_deactivate_minimum_balance(self):
        """Set bypass_minimum_balance to True to ignore minimum balance constraints."""
        self.ensure_one()
        self.bypass_minimum_balance = True

    def action_activate_minimum_balance(self):
        """Set bypass_minimum_balance to False to enforce minimum balance constraints."""
        self.ensure_one()
        self.bypass_minimum_balance = False   
    
    def unlink(self):
        for account in self:
            # Check for existing transactions
            transactions = self.env['sacco.investments.transaction'].search_count([
                ('investments_account_id', '=', account.id)
            ])
            
            if transactions > 0:
                raise UserError(_(
                    "This account cannot be deleted as it has associated transactions."
                ))
            # if account.state != 'draft':
            #     raise ValidationError(_("You can only delete draft investments accounts."))
        return super(InvestmentsAccount, self).unlink()
    
    @api.depends('journal_account_lines')
    def _compute_balances(self):
        for account in self:
            last_line = account.journal_account_lines[-1] if account.journal_account_lines else None
            account.cash_balance = last_line.closing_cash_balance if last_line else 0.0
            account.investment_balance = last_line.closing_investment_balance if last_line else 0.0
            account.total_profit = sum(line.amount for line in account.journal_account_lines if line.type == 'interest')

    @api.depends('cash_balance', 'investment_balance')
    def _compute_total_balance(self):
        for account in self:
            account.total_balance = account.cash_balance + account.investment_balance
            
            
    def _post_statement_to_external_system(self, start_date=None, end_date=None):
        """Posts or updates statement in external system"""
        try:
            _logger.info(f"Starting statement sync for investment account {self.name}")
            
            if not start_date:
                start_date = fields.Date.today() - timedelta(days=360)
            end_date = end_date or fields.Date.today()         
            
            wizard_obj = self.env['sacco.investments.statement.wizard']
            wizard = wizard_obj.create({
                'partner_id': self.member_id.id,
                'product_id': self.product_id.id,
                'currency_id': self.currency_id.id,
                'start_date': start_date or (fields.Date.today() - timedelta(days=90)),
                'end_date': end_date,
                'request_date': end_date,
            })
            
            token = wizard._get_authentication_token()
            if not token:
                _logger.error(f"Failed to get auth token for investment account {self.name}")
                return False
            
            transactions = wizard._get_transactions(self)
            
            # Log actual transaction count for debugging
            _logger.info(f"Found {len(transactions)} transactions for investment account {self.name}")

            if transactions:
                # Prepare and post/update statement
                statement_data = wizard._prepare_statement_data(self, transactions)
                
                headers = wizard._get_request_headers()
                
                result = wizard._post_or_update_statement(self, statement_data, token)
                                
                if isinstance(result, dict) and result.get('type') == 'ir.actions.client':
                    # Statement was posted/updated successfully
                    self.last_statement_sync_date = fields.Date.today()
                    self.env.cr.commit()  # Commit the date update
                    _logger.info(f"Successfully synced statement for investment account {self.name}")
                    return True
            
            _logger.info(f"No transactions to sync for investment account {self.name}")
            return True 
        except Exception as e:
            _logger.error(f"Error syncing statement for investment account {self.name}: {str(e)}")
            return False      
        
    
    def _trigger_statement_sync(self):
        """ Triggers statement sync """
        try:
            self._post_statement_to_external_system()
        except Exception as e:
            _logger.error(f"Error syncing statement for account {self.name}: {str(e)}")
            
    @api.model
    def sync_all_pending_statements(self):
        """ Syncs all pending statements for all accounts in the system """
        
        _logger.info("====================== Starting sync of pending investments statements ============================")
        
        accounts = self.search([
            ('state', '=', 'active'),
        ])
        
        for account in accounts:
            try:
                account._post_statement_to_external_system()
            except Exception as e:
                _logger.error(f"Failed to sync statement for account {account.name}: {str(e)}")
                continue
            
        _logger.info("===================== Completed sync of pending statements =========================")
        

    def action_refresh_journal_lines(self):
        """Refresh the materialized view"""
        self.env.cr.execute("REFRESH MATERIALIZED VIEW sacco_investment_account_journal_line")
        self._compute_balances()
        

    def action_mass_sync_statements(self):
        """Mass action to sync statements for selected records"""
        if not self:
            raise ValidationError(_("No records selected for statement synchronization."))
        
        _logger.info(f"Starting mass statement sync for {len(self)} investment accounts")
        
        for account in self:
            try:
                if account.state == 'active':
                    account._post_statement_to_external_system()
                    self.env.cr.commit()
                    _logger.info(f"Successfully synced statement for investment account {account.name}")
                else:
                    _logger.warning(f"Skipping investment account {account.name} - not active")
            except Exception as e:
                self.env.cr.rollback()
                _logger.error(f"Failed to sync statement for investment account {account.name}: {str(e)}")
        
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