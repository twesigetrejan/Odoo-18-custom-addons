from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class AccountAccount(models.Model):
    _inherit = 'account.account'
    
    requires_member = fields.Boolean(
        string='Requires Member Account', 
        default=False,
        help='When checked, journal entries using this account must be linked to a specific member account'
    )
    
    account_product_type = fields.Selection([
        ('savings', 'Savings Account'),
        ('savings_interest', 'Savings Interest'),
        ('shares', 'Shares Account'),
        ('investments', 'Investment Account'),
        ('investments_cash', 'Investment Cash Account'),
        ('investments_cash_profit', 'Investment Cash Profit Account'),
        ('loans', 'Loan Account'),
        ('loans_interest', 'Loans Interest'),
    ], string='Member Account Type',
        help='Specifies which type of member account must be selected when this account is used')
    
    original_shares_amount = fields.Float(
        string='Original Shares Amount',
        digits='Account',
        default=0.0,
        help='The original amount of shares for this account (required if account_product_type is "shares").'
    )
    interest_rate = fields.Float(
        string='Interest Rate (%)',
        digits=(5, 2),  # Allows for two decimal places, e.g., 5.75%
        default=0.0,
        help='The annual interest rate for this account (required if account_product_type is "loans" or "savings").'
    )    
    
    @api.onchange('requires_member')
    def _onchange_requires_member(self):
        if not self.requires_member:
            self.account_product_type = False
            self.original_shares_amount = 0.0
            self.interest_rate = 0.0


    @api.constrains('account_product_type', 'original_shares_amount', 'interest_rate')
    def _check_shares_amount_and_interest_rate(self):
        for record in self:
            if record.account_product_type == 'shares':
                if record.original_shares_amount <= 0:
                    raise ValidationError(
                        _("For account '%s' with type 'Shares', the Original Shares Amount must be greater than zero.")
                        % record.name
                    )
            elif record.account_product_type in ('loans', 'savings'):
                if record.interest_rate <= 0:
                    raise ValidationError(
                        _("For account '%s' with type '%s', the Interest Rate must be greater than zero.")
                        % (record.name, record.account_product_type)
                    )
                
class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'
    
    account_product_type = fields.Selection(
        selection=[  
            ('savings', 'Savings Account'),
            ('savings_interest', 'Savings Interest'),
            ('shares', 'Shares Account'),
            ('investments', 'Investment Account'),
            ('investments_cash', 'Investment Cash Account'),
            ('investments_cash_profit', 'Investment Cash Profit Account'),
            ('loans', 'Loan Account'),
            ('loans_interest', 'Loans Interest'),
        ],
        string='Account Product Type',
        compute='_compute_account_product_type',
        store=True,
        readonly=True
    )
    
    member_id = fields.Char(
        string='Member Id',
        compute='_compute_member_id',
        store=True,
        readonly=True,
        help='Member Id from the partner record'
    )
    
    loan_id = fields.Char(
        string='Loan Reference',
        help='Reference to the loan this journal entry relates to (e.g., LOAN/2025/001)'
    )
    
    @api.model
    def _is_loan_module_installed(self):
        return bool(self.env['ir.module.module'].search([
            ('name', '=', 'sacco_loan_management'),
            ('state', '=', 'installed')
        ]))
    
    @api.depends('partner_id', 'partner_id.member_id', 'account_id', 'account_id.requires_member')
    def _compute_member_id(self):
        for line in self:
            if line.account_id and line.account_id.requires_member:
                if line.partner_id and line.partner_id.member_id:
                    line.member_id = line.partner_id.member_id
                else:
                    line.member_id = False
            else:
                line.member_id = False
    
    @api.depends('account_id', 'account_id.account_product_type')
    def _compute_account_product_type(self):
        for line in self:
            line.account_product_type = line.account_id.account_product_type if line.account_id else False
    
    @api.onchange('account_id', 'partner_id', 'loan_id')
    def _onchange_account_id_partner_id(self):
        result = {}
        # Handle member requirements
        if self.account_id and self.account_id.requires_member:
            if not self.partner_id:
                result['warning'] = {
                    'title': _('Warning'),
                    'message': _('This account requires a member to be selected!')
                }
            elif not self.member_id:
                result['warning'] = {
                    'title': _('Warning'),
                    'message': _('The selected member does not have a Member Id, which is required for this account!')
                }
        
        # Handle loan_id logic
        is_loan_installed = self._is_loan_module_installed()
        if not self.account_id or self.account_product_type not in ('loans', 'loans_interest'):
            self.loan_id = False
        elif is_loan_installed and self.account_product_type in ('loans', 'loans_interest'):
            if self.partner_id:
                # Fetch valid loan names using SQL
                self.env.cr.execute("""
                    SELECT name
                    FROM sacco_loan_loan
                    WHERE client_id = %s
                    AND state NOT IN ('draft', 'reject', 'cancel')
                """, (self.partner_id.id,))
                valid_loan_ids = [row[0] for row in self.env.cr.fetchall()]
                if valid_loan_ids:
                    result['domain'] = {'loan_id': [('value', 'in', valid_loan_ids)]}
                else:
                    result['domain'] = {'loan_id': []}
            else:
                result['domain'] = {'loan_id': []}
        
        return result

    # @api.constrains('account_id', 'loan_id', 'partner_id')
    # def _check_loan_requirements(self):
    #     if not self._is_loan_module_installed():
    #         return
        
    #     for line in self:
    #         if line.account_id and line.account_product_type in ('loans', 'loans_interest'):
    #             if not line.loan_id:
    #                 raise ValidationError(
    #                     _("A Loan Reference is required for account '%s' with type '%s' in journal entry '%s'") % 
    #                     (line.account_id.name, line.account_product_type, line.move_id.name)
    #                 )
    #             if line.partner_id:
    #                 # Validate loan_id against sacco_loan_loan using SQL
    #                 self.env.cr.execute("""
    #                     SELECT COUNT(*)
    #                     FROM sacco_loan_loan
    #                     WHERE name = %s
    #                     AND client_id = %s
    #                     AND state NOT IN ('draft', 'reject', 'cancel')
    #                 """, (line.loan_id, line.partner_id.id))
    #                 count = self.env.cr.fetchone()[0]
    #                 if count == 0:
    #                     raise ValidationError(
    #                         _("The loan reference '%s' does not exist or does not belong to partner '%s'") % 
    #                         (line.loan_id, line.partner_id.name)
    #                     )

class AccountMove(models.Model):
    _inherit = 'account.move'
    
    def action_post(self):
        """Override the post action to enforce member and loan ID checks"""
        for move in self:
            for line in move.line_ids:
                # Check member requirements
                if line.account_id.requires_member:
                    if not line.partner_id:
                        raise ValidationError(
                            _("Cannot post journal entry '%s': Account '%s' requires a member to be selected.") % 
                            (move.name, line.account_id.name)
                        )
                    if not line.member_id:
                        raise ValidationError(
                            _("Cannot post journal entry '%s': Partner '%s' for account '%s' has no Member Id.") % 
                            (move.name, line.partner_id.name, line.account_id.name)
                        )
                    if line.member_id != line.partner_id.member_id:
                        raise ValidationError(
                            _("Cannot post journal entry '%s': Member Id '%s' for account '%s' does not match partner '%s''s Member Id '%s'.") % 
                            (move.name, line.member_id, line.account_id.name, line.partner_id.name, line.partner_id.member_id)
                        )
                
                # Check loan requirements if sacco_loan_management is installed
                # if line._is_loan_module_installed() and line.account_product_type in ('loans', 'loans_interest'):
                #     if not line.loan_id:
                #         raise ValidationError(
                #             _("Cannot post journal entry '%s': A Loan Reference is required for account '%s' with type '%s'.") % 
                #             (move.name, line.account_id.name, line.account_product_type)
                #         )
                #     if line.partner_id:
                #         # Validate loan_id using SQL
                #         self.env.cr.execute("""
                #             SELECT COUNT(*)
                #             FROM sacco_loan_loan
                #             WHERE name = %s
                #             AND client_id = %s
                #             AND state NOT IN ('draft', 'reject', 'cancel')
                #         """, (line.loan_id, line.partner_id.id))
                #         count = self.env.cr.fetchone()[0]
                #         if count == 0:
                #             raise ValidationError(
                #                 _("Cannot post journal entry '%s': Loan reference '%s' for account '%s' is invalid or does not belong to partner '%s'.") % 
                #                 (move.name, line.loan_id, line.account_id.name, line.partner_id.name)
                #             )
        
        # If all checks pass, proceed with posting
        return super(AccountMove, self).action_post()
    
    def _is_loan_module_installed(self):
        return bool(self.env['ir.module.module'].search([
            ('name', '=', 'sacco_loan_management'),
            ('state', '=', 'installed')
        ]))