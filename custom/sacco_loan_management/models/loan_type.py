from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)

class sacco_loan_type(models.Model):
    _name = "sacco.loan.type"
    _description = "Loan Product"
    
    name = fields.Char('Name', required=True, copy=False)
    product_code = fields.Char(string='Product Code', required=True, copy=False, readonly=False,
                              default=lambda self: self._get_loan_unique_code())
    is_interest_apply = fields.Boolean('Apply Interest')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
        default=lambda self: self.env.company.currency_id)
    description = fields.Text(string='Description', help='Detailed description of the loan product')
    interest_mode = fields.Selection([('flat', 'Flat'), ('reducing', 'Reducing')], string='Interest Mode')
    rate = fields.Float('Rate', required=True)
    proof_ids = fields.Many2many('sacco.loan.proof', string='Loan Proof')
    loan_amount = fields.Float('Loan Amount Limit', required=True, default=0.0)
    loan_term_by_month = fields.Integer('Loan Period By Month', required=True, default=12)
    has_journal_entries = fields.Boolean(
        string='Has Journal Entries',
        compute='_compute_has_journal_entries',
        store=True
    )
    loan_account_id = fields.Many2one(
        'account.account', 
        string='Disburse Account',
        domain="[('account_type', '=', 'asset_current'), ('requires_member', '=', True), ('account_product_type', '=', 'loans')]"
    )
    interest_account_id = fields.Many2one(
        'account.account', 
        string='Interest Account',
        domain="[('account_type', '=', 'asset_current'), ('requires_member', '=', True), ('account_product_type', '=', 'loans_interest')]"
    )
    installment_account_id = fields.Many2one(
        'account.account', 
        string='Installment Account', 
        readonly=True,
        domain="[('account_type', '=', 'asset_current'), ('requires_member', '=', True), ('account_product_type', '=', 'loans')]",
        compute='_compute_installment_account',
        store=True
    )
    disburse_journal_id = fields.Many2one(
        'account.journal', 
        string='Product Journal',  # Renamed from Disburse Journal
        default=lambda self: self.env['account.journal'].search([('name', '=', 'Member Journal')], limit=1)
    )
    loan_payment_journal_id = fields.Many2one(
        'account.journal', 
        string='Payment Journal', 
        invisible=True,
        default=lambda self: self.env['account.journal'].search([('name', '=', 'Member Journal')], limit=1)
    )
    none_interest_month = fields.Integer('None Interest Month')
    default_receiving_account_id = fields.Many2one(
        'sacco.receiving.account', 
        string='Default Receiving Account', 
        required=True, 
        tracking=True,
        help="Default account to receive loan payments"
    )
    default_paying_account_id = fields.Many2one(
        'sacco.paying.account', 
        string='Default Paying Account', 
        required=True, 
        tracking=True,
        help="Default account to receive savings deposits"
    )        
    createdBy = fields.Char(string='Created By')
    mongo_db_id = fields.Char(string='Mongo DB ID', readonly=True)
    ref_id = fields.Char(string='Reference ID')
    
    _sql_constraints = [
        ('loan_account_id_unique', 'UNIQUE(loan_account_id)', 'Disburse Account must be unique across all loan products!'),
        ('interest_account_id_unique', 'UNIQUE(interest_account_id)', 'Interest Account must be unique across all loan products!'),
    ]

    @api.onchange('is_interest_apply')
    def onchange_is_interest_apply(self):
        if self.is_interest_apply:
            self.interest_mode = 'flat'
        else:
            self.interest_mode = False
    
    @api.constrains('rate')
    def check_rate(self):
        if self.is_interest_apply and self.rate <= 0:
            raise ValidationError(_("Interest Rate Must be Positive!!!"))

    @api.constrains('loan_account_id')
    def _check_loan_account(self):
        for record in self:
            if record.loan_account_id:
                existing = self.env['sacco.loan.type'].search([
                    ('loan_account_id', '=', record.loan_account_id.id),
                    ('id', '!=', record.id)
                ])
                if existing:
                    raise ValidationError(_(
                        "The Disburse Account '%s' is already used in another loan product '%s'."
                    ) % (record.loan_account_id.name, existing[0].name))

    @api.constrains('interest_account_id')
    def _check_interest_account(self):
        for record in self:
            if record.interest_account_id:
                existing = self.env['sacco.loan.type'].search([
                    ('interest_account_id', '=', record.interest_account_id.id),
                    ('id', '!=', record.id)
                ])
                if existing:
                    raise ValidationError(_(
                        "The Interest Account '%s' is already used in another loan product '%s'."
                    ) % (record.interest_account_id.name, existing[0].name))

    @api.depends('loan_account_id')
    def _compute_installment_account(self):
        """Compute installment_account_id to always match loan_account_id"""
        for record in self:
            record.installment_account_id = record.loan_account_id

    def _get_loan_unique_code(self):
        sequence = self.env['ir.sequence'].next_by_code('sacco.loan.product.code')
        if not sequence:
            _logger.error("Failed to generate unique loan code. Sequence not found.")
            raise UserError(_("Please configure sequence for investment product codes"))
        return sequence
    
    @api.depends('loan_payment_journal_id', 'disburse_journal_id', 'loan_account_id', 'installment_account_id', 'interest_account_id')
    def _compute_has_journal_entries(self):
        for record in self:
            journal_ids = [record.loan_payment_journal_id.id, record.disburse_journal_id.id]
            journal_ids = [j for j in journal_ids if j]
            account_ids = [record.loan_account_id.id, record.installment_account_id.id, record.interest_account_id.id]
            account_ids = [a for a in account_ids if a]
            if journal_ids or account_ids:
                entry_count = self.env['account.move.line'].search_count([
                    '|',
                    ('journal_id', 'in', journal_ids),
                    ('account_id', 'in', account_ids)
                ])
                record.has_journal_entries = entry_count > 0
            else:
                record.has_journal_entries = False

    def write(self, vals):
        for record in self:
            if record.has_journal_entries:
                allowed_fields = {'interest_mode', 'rate', 'proof_ids', 'loan_term_by_month'}
                restricted_fields = set(vals.keys()) - allowed_fields
                if restricted_fields and 'product_code' in restricted_fields:
                    raise ValidationError(_(
                        "Cannot modify the Product Code for product '%s' because it has associated journal entries."
                    ) % record.name)
        return super().write(vals)

    def action_create_account_journals(self):
        AccountAccount = self.env['account.account']
        AccountJournal = self.env['account.journal']
        
        for record in self:
            if record.loan_account_id:
                raise UserError(_("Accounts and journals are already created for this product"))
                    
            account_code_prefix = self._get_loan_unique_code()
            _logger.info(f"Generated unique account code prefix: {account_code_prefix}")
            
            member_journal = AccountJournal.search([('name', '=', 'Member Journal')], limit=1)
            if not member_journal:
                raise UserError(_("Member Journal not found. Please create it first."))

            try:
                # Disburse Account (Loan Account)
                disburse_account = AccountAccount.create({
                    'name': f"{record.name} - Disbursements",
                    'code': f"{account_code_prefix}1",
                    'account_type': 'asset_current',
                    'reconcile': True,
                    'requires_member': True,
                    'account_product_type': 'loans',
                })
                _logger.info(f"Created loan disburse account: {disburse_account.name}")

                # Interest Account
                interest_account = AccountAccount.create({
                    'name': f"Interest Income from {record.name}",
                    'code': f"{account_code_prefix}2",
                    'account_type': 'asset_current',
                    'reconcile': True,
                    'requires_member': True,
                    'account_product_type': 'loans_interest',
                })
                _logger.info(f"Created loan interest account: {interest_account.name}")

                # Installment Account (set equal to Disburse Account)
                installment_account = disburse_account

            except Exception as e:
                _logger.error(f"Error creating loan accounts: {str(e)}")
                raise UserError(_(f"Error creating loan accounts: {str(e)}"))
        
            # Update record with created accounts/journals
            record.write({
                'loan_account_id': disburse_account.id,
                'interest_account_id': interest_account.id,
                'installment_account_id': installment_account.id,
                'disburse_journal_id': member_journal.id,
                'loan_payment_journal_id': member_journal.id,
            })
        
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Accounts and journals have been created successfully!'),
                    'sticky': False,
                }
            }
            
    def unlink(self):
        for loan_type in self:
            if loan_type.has_journal_entries:
                raise UserError(_(
                    "Cannot delete loan product '%s' because it has associated journal entries."
                ) % loan_type.name)
            loans = self.env['sacco.loan.loan'].search_count([('loan_type_id', '=', loan_type.id)])
            if loans > 0:
                raise UserError(_(
                    "This loan product cannot be deleted as it has associated loans."
                ))
        return super().unlink()