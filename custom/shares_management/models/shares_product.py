from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging
_logger = logging.getLogger(__name__)

class SharesProduct(models.Model):
    _name = 'sacco.shares.product'
    _description = 'SACCO Shares Product'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Product Name', required=True)
    product_code = fields.Char(string='Product Code', required=True, copy=False, readonly=False,
                              default=lambda self: self._get_unique_code())
    original_shares_amount = fields.Float('Original Shares Amount', required=True)
    current_shares_amount = fields.Float('Current Shares Amount', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
        default=lambda self: self.env.company.currency_id)
    shares_account_count = fields.Integer(
        string='Related Shares Accounts',
        compute='_compute_shares_account_count'
    )
    has_journal_entries = fields.Boolean(
        string='Has Journal Entries',
        compute='_compute_has_journal_entries',
        store=True
    )
    default_receiving_account_id = fields.Many2one('sacco.receiving.account', 
        string='Default Receiving Account', required=True, tracking=True,
        help="Default account to receive shares deposits")
    default_paying_account_id = fields.Many2one('sacco.paying.account', 
        string='Default Paying Account', required=True, tracking=True,
        help="Default account to receive shares deposits")    
    original_shares_product_account_id = fields.Many2one('account.account', string='Original Shares Product Account')
    original_shares_product_journal_id = fields.Many2one('account.journal', string='Original Shares Product Journal')
    current_shares_product_account_id = fields.Many2one('account.account', string='Current Shares Product Account')
    current_shares_product_journal_id = fields.Many2one('account.journal', string='Current Shares Product Journal')
    
    createdBy = fields.Char(string='Created By')
    mongo_db_id = fields.Char(string='Mongo DB ID', readonly=True)
    ref_id = fields.Char(string='Reference ID')
    
    _sql_constraints = [
        ('product_code_unique', 'UNIQUE(product_code)', 'Product Code must be unique!')
    ]
    
    def _get_unique_code(self):
        """
        Generates a unique account code using Odoo's sequence mechanism.
        """
        sequence = self.env['ir.sequence'].next_by_code('sacco.shares.product.code')
        if not sequence:
            _logger.error("Failed to generate unique account code. Sequence not found.")
            raise UserError(_("Please configure sequence for investment product codes"))
        return sequence  


    @api.depends('current_shares_product_journal_id', 'original_shares_product_journal_id')
    def _compute_has_journal_entries(self):
        for record in self:
            journal_ids = [record.current_shares_product_journal_id.id, record.original_shares_product_journal_id.id]
            journal_ids = [j for j in journal_ids if j]  # Remove False/None values
            if journal_ids:
                entry_count = self.env['account.move.line'].search_count([
                    ('journal_id', 'in', journal_ids)
                ])
                record.has_journal_entries = entry_count > 0
            else:
                record.has_journal_entries = False

    @api.constrains('original_shares_product_account_id', 'original_shares_amount')
    def _check_original_shares_account(self):
        for record in self:
            if record.original_shares_product_account_id:
                account = record.original_shares_product_account_id
                # Check if account is equity type
                if not account.account_type.startswith('equity'):
                    raise ValidationError(
                        _("The Original Shares Product Account '%s' must be of equity type.")
                        % account.name
                    )
                # Check if account_product_type is 'shares'
                if account.account_product_type != 'shares':
                    raise ValidationError(
                        _("The Original Shares Product Account '%s' must have account product type 'Shares'.")
                        % account.name
                    )
                # Check if amounts match
                if account.original_shares_amount != record.original_shares_amount:
                    raise ValidationError(
                        _("The Original Shares Amount (%s) does not match the amount defined in account '%s' (%s). "
                          "Please update the amount in the Chart of Accounts if needed.") 
                        % (record.original_shares_amount, account.name, account.original_shares_amount)
                    )

    def write(self, vals):
        """Override write to restrict modifications when journal entries exist"""
        for record in self:
            if record.has_journal_entries:
                # Only allow current_shares_amount to be modified
                allowed_fields = {'current_shares_amount', 'period'}
                restricted_fields = set(vals.keys()) - allowed_fields
                if restricted_fields:
                    raise ValidationError(_(
                        "Cannot modify fields other than Current Shares Amount "
                        "for product '%s' because it has associated journal entries."
                    ) % record.name)
        return super().write(vals) 

    
    def action_create_account_journals(self):
        AccountAccount = self.env['account.account']
        AccountJournal = self.env['account.journal']

        for record in self:
            if record.original_shares_product_account_id:
                raise UserError(_("Accounts and journals are already created for this product"))

            account_code_prefix = self._get_unique_code()
            _logger.info(f"Generated unique account code prefix: {account_code_prefix}")

            original_shares_product_account = AccountAccount.create({
                'name': f"{record.name} Shares Account",
                'code': f"{account_code_prefix}1",
                'account_type': 'equity',
                'reconcile': False,
                'requires_member': True,
                'account_product_type': 'shares',
                'original_shares_amount': record.original_shares_amount
            })
            _logger.info(f"Created shares product account: {original_shares_product_account.name}")

            current_shares_product_account = AccountAccount.create({
                'name': f"{record.name} Current Shares Account",
                'code': f"{account_code_prefix}2",
                'account_type': 'equity',
                'reconcile': False,
                'requires_member': False,
            })
            _logger.info(f"Created current shares account: {current_shares_product_account.name}")

            original_shares_product_journal = AccountJournal.create({
                'name': f"{record.name} Shares Journal",
                'code': f"{account_code_prefix}SP",
                'type': 'general',
            })
            _logger.info(f"Created shares product journal: {original_shares_product_journal.name}")
            
            current_shares_product_journal = AccountJournal.create({
                'name': f"{record.name} Current Shares Journal",
                'code': f"{account_code_prefix}CS",
                'type': 'general',
            })
            _logger.info(f"Created current shares journal: {current_shares_product_journal.name}")
            
            record.write({
                'original_shares_product_account_id': original_shares_product_account.id,
                'current_shares_product_account_id': current_shares_product_account.id,
                'original_shares_product_journal_id': original_shares_product_journal.id,
                'current_shares_product_journal_id': current_shares_product_journal.id,
            })