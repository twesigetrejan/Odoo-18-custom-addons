from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging
_logger = logging.getLogger(__name__)

class SavingsProduct(models.Model):
    _name = 'sacco.savings.product'
    _description = 'SACCO Savings Product'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Product Name', required=True)
    product_code = fields.Char(string='Product Code', required=True, copy=False, readonly=False,
                              default=lambda self: self._get_unique_code())
    interest_rate = fields.Float(string='Annual Interest Rate (%)', digits=(5, 2), required=True)
    description = fields.Text(string='Description', help='Detailed description of the savings product')
    period = fields.Selection(
        [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('semi_annually', 'Semi Annually (6 months)'),
        ('annually', 'Annually'),
                               ], string='Interest Period', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
        default=lambda self: self.env.company.currency_id)
    minimum_balance = fields.Float(string='Minimum Balance', default=0.0, digits='Account', required=True,
                                  help='Minimum balance required to be maintained in savings accounts of this product')
    savings_account_count = fields.Integer(
        string='Related Savings Accounts',
        compute='_compute_savings_account_count'
    )
    has_journal_entries = fields.Boolean(
        string='Has Journal Entries',
        compute='_compute_has_journal_entries',
        store=True
    )
    default_receiving_account_id = fields.Many2one('sacco.receiving.account', 
        string='Default Receiving Account', required=True, tracking=True,
        help="Default account to receive savings deposits")
    default_paying_account_id = fields.Many2one('sacco.paying.account', 
        string='Default Paying Account', required=True, tracking=True,
        help="Default account to receive savings deposits")    
    withdrawal_account_id = fields.Many2one('account.account', string='Withdrawal Disburse Account', 
        compute='_compute_withdrawal_fields', store=True)
    disburse_journal_id = fields.Many2one('account.journal', string='Withdrawal Disburse Journal',
        compute='_compute_withdrawal_fields', store=True)
    interest_account_id = fields.Many2one('account.account', string='Interest Expense Account', required=True)
    interest_disbursement_account_id = fields.Many2one(
        'account.account',
        string='Interest Disbursement Account',
        required=True,
        domain="[('account_product_type', '=', 'savings_interest'), ('requires_member', '=', True)]",
        help="Account used to disburse interest to members' savings accounts."
    )
    savings_product_account_id = fields.Many2one('account.account', string='Savings Product Account',
        domain="[('account_type', '=like', 'liability%'), ('requires_member', '=', True), "
               "('account_product_type', 'in', ['savings', 'savings_interest'])]", required=True)
    savings_product_journal_id = fields.Many2one('account.journal', string='Savings Product Journal',
        default=lambda self: self.env['sacco.helper'].get_member_journal_id())
    
    mongo_db_id = fields.Char(string='Mongo DB ID', readonly=True)
    
    _sql_constraints = [
        ('product_code_unique', 'UNIQUE(product_code)', 'Product Code must be unique!'),
        ('savings_product_account_id_unique', 'UNIQUE(savings_product_account_id)', 
         'Savings Product Account must be unique across all savings products!'),
        ('interest_disbursement_account_id_unique', 'UNIQUE(interest_disbursement_account_id)', 
         'Interest Disbursement Account must be unique across all savings products!')
    ]
    
    def _get_unique_code(self):
        """
        Generates a unique account code using Odoo's sequence mechanism.
        """
        sequence = self.env['ir.sequence'].next_by_code('sacco.savings.product.code')
        if not sequence:
            _logger.error("Failed to generate unique account code. Sequence not found.")
            raise UserError(_("Please configure sequence for investment product codes"))
        return sequence   

    @api.depends('name')
    def _compute_savings_account_count(self):
        for record in self:
            record.savings_account_count = self.env['sacco.savings.account'].search_count([
                ('product_id', '=', record.id)
            ])

    @api.depends('savings_product_account_id')
    def _compute_has_journal_entries(self):
        """
        Compute whether the product has associated journal entries by checking if there are
        any account.move.line records tied to the product's accounts (savings_product_account_id,
        withdrawal_account_id, or interest_account_id).
        """
        for record in self:
            # Collect all account IDs associated with the product
            account_ids = [
                record.savings_product_account_id.id,
            ]
            # Remove False/None values (in case any account is not set)
            account_ids = [account_id for account_id in account_ids if account_id]

            if account_ids:
                # Search for journal entry lines (account.move.line) where the account_id
                # matches any of the product's associated accounts
                entry_count = self.env['account.move.line'].search_count([
                    ('account_id', 'in', account_ids),
                    ('parent_state', '=', 'posted')  # Only count posted journal entries
                ])
                record.has_journal_entries = entry_count > 0
            else:
                # If no accounts are associated with the product, there can't be journal entries
                record.has_journal_entries = False

    def write(self, vals):
            """Override write to restrict modification of product_code when journal entries exist"""
            for record in self:
                if record.has_journal_entries and 'product_code' in vals:
                    raise ValidationError(_(
                        "Cannot modify the Product Code for product '%s' "
                        "because it has associated journal entries."
                    ) % record.name)
            return super().write(vals)
        
    @api.depends('savings_product_account_id', 'savings_product_journal_id')
    def _compute_withdrawal_fields(self):
        for record in self:
            record.withdrawal_account_id = record.savings_product_account_id
            record.disburse_journal_id = record.savings_product_journal_id

    @api.constrains('savings_product_account_id')
    def _check_savings_account(self):
        for record in self:
            if record.savings_product_account_id:
                account = record.savings_product_account_id
                if not account.requires_member:
                    raise ValidationError(_("The savings product account must require a member."))
                if account.account_type not in ['liability_current', 'liability_non_current']:
                    raise ValidationError(_("The savings product account must be of liability type."))
                if account.account_product_type not in ['savings', 'savings_interest']:
                    raise ValidationError(_("The savings product account must be of type savings or savings_interest."))
                
    @api.constrains('savings_product_account_id', 'interest_account_id', 'interest_disbursement_account_id')
    def _check_account_constraints(self):
        for record in self:
            # Check savings product account
            if record.savings_product_account_id:
                account = record.savings_product_account_id
                if not account.requires_member:
                    raise ValidationError(_("The savings product account must require a member."))
                if account.account_type not in ['liability_current', 'liability_non_current']:
                    raise ValidationError(_("The savings product account must be of liability type."))
                if account.account_product_type not in ['savings', 'savings_interest']:
                    raise ValidationError(_("The savings product account must be of type savings or savings_interest."))
                
                # Check if account is already used in another savings product
                existing_products = self.env['sacco.savings.product'].search([
                    ('savings_product_account_id', '=', account.id),
                    ('id', '!=', record.id)
                ])
                if existing_products:
                    raise ValidationError(_(
                        "The account '%s' is already used in savings product '%s'. "
                        "Please select a different account."
                    ) % (account.name, existing_products[0].name))

            # Check interest account
            if record.interest_account_id:
                account = record.interest_account_id
                if account.account_type != 'expense':
                    raise ValidationError(_("The interest account must be of expense type."))
                if account.requires_member:
                    raise ValidationError(_("The interest account should not require a member."))
                    
            if record.interest_disbursement_account_id:
                account = record.interest_disbursement_account_id
                if not account.requires_member:
                    raise ValidationError(_("The interest disbursement account must require a member."))
                if account.account_product_type != 'savings_interest':
                    raise ValidationError(_("The interest disbursement account must be of type 'Savings Interest'."))
                # Check uniqueness
                existing_products = self.env['sacco.savings.product'].search([
                    ('interest_disbursement_account_id', '=', account.id),
                    ('id', '!=', record.id)
                ])
                if existing_products:
                    raise ValidationError(_(
                        "The interest disbursement account '%s' is already used in savings product '%s'. "
                        "Please select a different account."
                    ) % (account.name, existing_products[0].name))
                    
    def action_create_account_journals(self):
        AccountAccount = self.env['account.account']
        AccountJournal = self.env['account.journal']
        sacco_helper = self.env['sacco.helper']

        for record in self:
            if record.interest_account_id:
                raise UserError(_("Accounts and journals are already created for this product"))

            account_code_prefix = self._get_unique_code()
            
            # Create savings product account
            savings_product_account = AccountAccount.create({
                'name': f"{record.name} Savings Account",
                'code': f"{account_code_prefix}1",
                'account_type': 'liability_current',
                'reconcile': True,
                'requires_member': True,
                'account_product_type': 'savings',
            })

            # Use Member Journal by default
            member_journal = sacco_helper.ensure_member_journal()

            # Create interest account
            interest_account = AccountAccount.create({
                'name': f"Interest Expense for {record.name} Savings",
                'code': f"{account_code_prefix}3",
                'account_type': 'expense',
                'reconcile': True,
            })

            # Update record
            record.write({
                'savings_product_account_id': savings_product_account.id,
                'savings_product_journal_id': member_journal,
                'interest_account_id': interest_account.id,
            })
    
    def action_create_account_journals(self):
        # Extend the existing method to create the interest disbursement account
        res = super().action_create_account_journals()
        for record in self:
            if not record.interest_disbursement_account_id:
                account_code_prefix = self._get_unique_code()
                interest_disbursement_account = self.env['account.account'].create({
                    'name': f"{record.name} Interest Disbursement Account",
                    'code': f"{account_code_prefix}4",
                    'account_type': 'liability_current',
                    'reconcile': True,
                    'requires_member': True,
                    'account_product_type': 'savings_interest',
                })
                record.interest_disbursement_account_id = interest_disbursement_account.id
        return res
            

    def unlink(self):
        """
        Prevent deletion of savings products that have associated journal entries
        tied to the savings_product_account_id.
        """
        for record in self:
            if record.has_journal_entries:
                raise UserError(_(
                    "Cannot delete savings product '%s' because it has associated "
                    "journal entries tied to its savings account. Please archive the "
                    "product instead if you want to discontinue it."
                ) % record.name)
        if record.savings_account_count > 0:
                raise UserError(_(
                    "Cannot delete savings product '%s' because it has %d associated "
                    "savings accounts. Please archive the product instead if you want "
                    "to discontinue it."
                ) % (record.name, record.savings_account_count))
        return super().unlink()