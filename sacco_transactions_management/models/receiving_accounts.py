from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import re

class SaccoReceivingAccount(models.Model):
    _name = 'sacco.receiving.account'
    _description = 'SACCO Receiving Account Configuration'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    account_type = fields.Selection([
        ('bank', 'Bank'),
        ('mobile', 'Mobile')
    ], string='Account Type', required=True, default='bank', tracking=True)
    name = fields.Char(string='Account Name', required=True, tracking=True,
                      help="External account name (e.g. Bank of Africa)")
    bank_name = fields.Char(string='Bank Name', tracking=True)
    branch = fields.Char(string='Branch', tracking=True)
    mobile_money_number = fields.Char(string='Mobile Money Number', tracking=True)
    account_id = fields.Many2one('account.account', string='Internal Account', required=True, 
                                tracking=True)
    account_number = fields.Char(string='Account Number', readonly=True, store=True, 
                              compute='_compute_account_number', tracking=True)
    status = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('inactive', 'Inactive')
    ], string='Status', default='draft', required=True, tracking=True)
    default = fields.Boolean(string='Default', tracking=True)
    
    _sql_constraints = [
        ('name_unique', 'UNIQUE(name)', 'The account name must be unique!'),
        ('account_id_unique', 'UNIQUE(account_id)', 'This Internal account is already linked to another receiving account!'),
        ('mobile_money_number_unique', 'UNIQUE(mobile_money_number)', 'The mobile money number must be unique!'),
    ]
    
    @api.depends('account_id', 'account_type')
    def _compute_account_number(self):
        for record in self:
            if record.account_type == 'bank' and record.account_id:
                record.account_number = record.account_id.code
            else:
                record.account_number = False
    
    @api.constrains('account_id')
    def _check_account_requires_member(self):
        for record in self:
            if record.account_id.requires_member:
                raise ValidationError(_("You cannot select an account that requires member assignment for receiving accounts."))
    
    @api.constrains('account_type', 'branch', 'mobile_money_number', 'status')
    def _check_required_fields(self):
        mobile_number_pattern = r'^\+?[1-9]\d{1,14}$'
        for record in self:
            if record.status == 'draft':
                continue  # Skip validation for draft status
            if record.account_type == 'bank' and not record.branch:
                raise ValidationError(_("Branch is required for bank accounts."))
            if record.account_type == 'mobile':
                if not record.mobile_money_number:
                    raise ValidationError(_("Mobile Money Number is required for mobile accounts."))
                if not re.match(mobile_number_pattern, record.mobile_money_number):
                    raise ValidationError(_("Mobile Money Number must follow the international format (e.g., +1234567890, up to 15 digits)."))
    
    @api.constrains('default', 'account_type')
    def _check_default_unique(self):
        for record in self:
            if record.default:
                # Check for other default records of the same account_type
                other_defaults = self.search([
                    ('default', '=', True),
                    ('account_type', '=', record.account_type),
                    ('id', '!=', record.id)
                ])
                if other_defaults:
                    raise ValidationError(_("Only one %s account can be set as default." % record.account_type))
    
    def action_activate(self):
        for record in self:
            if record.status == 'draft':
                record.status = 'active'
    
    def action_reset_to_draft(self):
        for record in self:
            if record.status == 'active' or record.status == 'inactive':
                record.status = 'draft'
    
    def action_deactivate(self):
        for record in self:
            if record.status == 'active':
                record.status = 'inactive'