from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)
BATCH_SIZE = 500

class SharesAccount(models.Model):
    _name = 'sacco.shares.account'
    _description = 'SACCO Shares Account'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('ID', default='/', copy=False)
    member_id = fields.Many2one('res.partner', string='Member', required=True, domain=[('is_sacco_member', '=', True)])
    product_id = fields.Many2one('sacco.shares.product', string='Shares Product', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, tracking=True, default=lambda self: self._get_default_currency())
    share_number = fields.Float(string='Share Number', default=0.0, digits='Account', compute='_compute_share_number', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
    ], string='State', default='draft')
    last_interest_date = fields.Date(string='Last Interest Computation Date')
    
    statement_mongo_db_id = fields.Char('Shares Statement Mongodb Id', copy=False)
    last_statement_sync_date = fields.Date(
        string='Last Statement Sync Date',
        readonly=True,
        help='Tracks the last time a statement was synced with the external system'
    )
    update_statement = fields.Boolean(
        string='Allow Statement Update',
        default=False,
        tracking=True,
        help='Toggle to allow statement update to external system'
    )
    shares_journal_account_lines = fields.One2many('sacco.shares.journal.account.line', 'shares_account_id', string='Journal Account Lines')
    
    @api.model
    def create(self, vals):
        if vals.get('name', '/') == '/':
            member = self.env['res.partner'].browse(vals['member_id'])
            print(member)
            if not member.member_id:
                raise ValidationError("Member Id is required to create a shares account.")
            seq = self.env['ir.sequence'].next_by_code('sacco.shares.account')
            if not seq:
                raise ValidationError("Could not retrieve sequence for 'sacco.shares.account'.")
            year = fields.Date.today().year
            vals['name'] = f"SHAR/{member.member_id}/{year}/{seq.split('/')[-1]}"
        
        existing_account = self.search([
            ('member_id', '=', vals.get('member_id')),
            ('product_id', '=', vals.get('product_id')),
            ('currency_id', '=', vals.get('currency_id')),
        ])
        if vals.get('product_id') and not vals.get('currency_id'):
            product = self.env['sacco.shares.product'].browse(vals['product_id'])
            vals['currency_id'] = product.currency_id.id
        if existing_account:
            raise ValidationError(_("A shares account with this product already exists for this member."))
            
        return super(SharesAccount, self).create(vals)
    
    @api.depends('shares_journal_account_lines', 'shares_journal_account_lines.number_of_shares')
    def _compute_share_number(self):
        """Compute total number of shares from journal entries"""
        for account in self:
            # Using SQL for better performance with large datasets
            self.env.cr.execute("""
                SELECT COALESCE(SUM(number_of_shares), 0) 
                FROM sacco_shares_journal_account_line
                WHERE shares_account_id = %s
            """, (account.id,))
            
            result = self.env.cr.fetchone()
            account.share_number = result[0] if result else 0.0

    def action_refresh_journal_lines(self):
        """Refresh shares journal account line view and update share number"""
        self.action_refresh_shares_journal_lines()
        self._compute_share_number()
        return True
       
    def action_refresh_shares_journal_lines(self):
        """Refresh shares journal account line view"""
        self.env.cr.execute("SELECT 1 FROM pg_matviews WHERE matviewname = 'sacco_shares_journal_account_line'")
        if self.env.cr.fetchone():
            self.env.cr.execute("REFRESH MATERIALIZED VIEW sacco_shares_journal_account_line")
            _logger.info("Successfully refreshed sacco_shares_journal_account_line materialized view")
        else:
            _logger.warning("Materialized view sacco_shares_journal_account_line does not exist")
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }   
 
    @api.model
    def _get_default_currency(self):
        """Get default currency from product if available, otherwise company currency"""
        if self._context.get('default_product_id'):
            product = self.env['sacco.shares.product'].browse(self._context.get('default_product_id'))
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
            
    @api.constrains('member_id', 'product_id')
    def check_unique_product_for_member(self):
        for record in self:
            existing_accounts = self.search([
                ('member_id', '=', record.member_id.id),
                ('product_id', '=', record.product_id.id),
                ('id', '!=', record.id)
            ])
            if existing_accounts:
                raise ValidationError(_("A shares account with this product already exists for this member."))
            
    def action_activate_shares_account(self):
        self.state = 'active'
        
    def action_deactivate_shares_account(self):
        self.state = 'inactive'

    
    def unlink(self):
        for account in self:
            if account.state != 'draft':
                raise ValidationError(_("You can only delete draft shares accounts."))
        return super(SharesAccount, self).unlink()
