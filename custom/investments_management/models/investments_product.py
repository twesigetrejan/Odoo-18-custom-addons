from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)

class InvestmentsProduct(models.Model):
    _name = 'sacco.investments.product'
    _description = 'SACCO Investments Product'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Product Name', required=True)
    product_code = fields.Char(string='Product Code', required=True, copy=False, readonly=False,
                              default=lambda self: self._get_investment_unique_code())
    interest_rate = fields.Float(string='Annual Interest Rate (%)', digits=(5, 2), required=True, default=0.0)
    description = fields.Text(string='Description', help='Detailed description of the investments product')
    period = fields.Selection(
        [
            ('daily', 'Daily'),
            ('weekly', 'Weekly'),
            ('monthly', 'Monthly'),
            ('annually', 'Annually'),
        ], string='Interest Period')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                 default=lambda self: self.env.company.currency_id)
    minimum_balance = fields.Float(string='Minimum Balance', default=0.0, digits='Account', required=True,
                                  help='Minimum balance required to be maintained in investments accounts of this product')
    investment_risk = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High')
    ], string='Risk Level', default='low')
    maturity_period = fields.Integer('Maturity Period (Months)')
    is_pooled_investment = fields.Boolean('Is Pooled Investment')
    minimum_pool_amount = fields.Float('Minimum Pool Amount', default=0.0)
    default_receiving_account_id = fields.Many2one('sacco.receiving.account',
                                                   string='Default Receiving Account', required=True, tracking=True)
    default_paying_account_id = fields.Many2one('sacco.paying.account',
                                                string='Default Paying Account', required=True, tracking=True)
    investments_product_cash_account_id = fields.Many2one('account.account', string='Investments Product Cash Account',
                                                         domain="[('account_type', '=like', 'liability%'), "
                                                                "('requires_member', '=', True), "
                                                                "('account_product_type', '=', 'investments_cash')]")
    investments_product_cash_profit_account_id = fields.Many2one('account.account', string='Investments Product Cash Profit Account',
                                                         domain="[('account_type', '=like', 'liability%'), "
                                                                "('requires_member', '=', True), "
                                                                "('account_product_type', '=', 'investments_cash_profit')]")
    investments_product_cash_journal_id = fields.Many2one('account.journal', string='Member Journal',
                                                         default=lambda self: self.env['sacco.helper'].get_member_journal_id())
    investments_product_account_id = fields.Many2one('account.account', string='Investments Product Account',
                                                    domain="[('account_type', '=like', 'asset%'), "
                                                           "('requires_member', '=', True), "
                                                           "('account_product_type', '=', 'investments')]")
    investments_product_journal_id = fields.Many2one('account.journal', string='Investments Product Journal',
                                                    default=lambda self: self.env['sacco.helper'].get_member_journal_id())
    createdBy = fields.Char(string='Created By')
    mongo_db_id = fields.Char(string='Mongo DB ID', readonly=True)
    ref_id = fields.Char(string='Reference ID')
    has_journal_entries = fields.Boolean(string='Has Journal Entries', compute='_compute_has_journal_entries', store=True)

    _sql_constraints = [
        ('product_code_unique', 'UNIQUE(product_code)', 'Product Code must be unique!'),
        ('investments_product_cash_account_id_unique', 'UNIQUE(investments_product_cash_account_id)',
         'Investments Product Cash Account must be unique across all investment products!'),
        ('investments_product_cash_profit_account_id_unique', 'UNIQUE(investments_product_cash_profit_account_id)',
         'Investments Product Cash Profit Account must be unique across all investment products!'),
        ('investments_product_account_id_unique', 'UNIQUE(investments_product_account_id)',
         'Investments Product Account must be unique across all investment products!')
    ]

    def _get_investment_unique_code(self):
        sequence = self.env['ir.sequence'].next_by_code('sacco.investment.product.code')
        if not sequence:
            _logger.error("Failed to generate unique investment code. Sequence not found.")
            raise UserError(_("Please configure sequence for investment product codes"))
        return sequence

    @api.depends('investments_product_cash_account_id', 'investments_product_cash_profit_account_id', 'investments_product_account_id')
    def _compute_has_journal_entries(self):
        for record in self:
            account_ids = [
                record.investments_product_cash_account_id.id,
                record.investments_product_cash_profit_account_id.id,
                record.investments_product_account_id.id,
            ]
            account_ids = [aid for aid in account_ids if aid]
            if account_ids:
                entry_count = self.env['account.move.line'].search_count([
                    ('account_id', 'in', account_ids),
                    ('parent_state', '=', 'posted')
                ])
                record.has_journal_entries = entry_count > 0
            else:
                record.has_journal_entries = False

    def action_create_account_journals(self):
        AccountAccount = self.env['account.account']
        sacco_helper = self.env['sacco.helper']

        for record in self:
            if record.investments_product_cash_account_id or record.investments_product_account_id or record.investments_product_cash_profit_account_id:
                raise UserError(_("Accounts and journals are already created for this product"))

            account_code_prefix = self._get_investment_unique_code()

            # Create cash account
            cash_account = AccountAccount.create({
                'name': f"{record.name} Investment Cash Account",
                'code': f"{account_code_prefix}1",
                'account_type': 'liability_current',
                'reconcile': True,
                'requires_member': True,
                'account_product_type': 'investments_cash',
            })
            
            # Create cash profit account
            cash_profit_account = AccountAccount.create({
                'name': f"{record.name} Investment Cash Profit Account",
                'code': f"{account_code_prefix}1",
                'account_type': 'liability_current',
                'reconcile': True,
                'requires_member': True,
                'account_product_type': 'investments_cash_profit',
            })

            # Create investment account
            investment_account = AccountAccount.create({
                'name': f"{record.name} Investment Fund Account",
                'code': f"{account_code_prefix}2",
                'account_type': 'asset_current',
                'reconcile': True,
                'requires_member': True,
                'account_product_type': 'investments',
            })

            # Use Member Journal
            member_journal = sacco_helper.get_member_journal_id()

            # Update record
            record.write({
                'investments_product_cash_account_id': cash_account.id,
                'investments_product_cash_profit_account_id': cash_profit_account.id,
                'investments_product_cash_journal_id': member_journal,
                'investments_product_account_id': investment_account.id,
                'investments_product_journal_id': member_journal,
            })
            _logger.info(f"Created accounts and journals for investment product: {record.name}")

    def unlink(self):
        for record in self:
            if record.has_journal_entries:
                raise UserError(_(
                    "Cannot delete investment product '%s' because it has associated journal entries."
                ) % record.name)
            investment_count = self.env['sacco.investments.account'].search_count([('product_id', '=', record.id)])
            if investment_count > 0:
                raise UserError(_(
                    "Cannot delete investment product '%s' because it has %d associated investment accounts."
                ) % (record.name, investment_count))
        return super().unlink()

    def write(self, vals):
        for record in self:
            if record.has_journal_entries and 'product_code' in vals:
                raise ValidationError(_(
                    "Cannot modify the Product Code for product '%s' because it has associated journal entries."
                ) % record.name)
        return super().write(vals)

    @api.constrains('investments_product_cash_account_id','investments_product_cash_profit_account_id','investments_product_account_id')
    def _check_account_constraints(self):
        for record in self:
            # Check cash account
            if record.investments_product_cash_account_id:
                cash_acc = record.investments_product_cash_account_id
                if not cash_acc.requires_member:
                    raise ValidationError(_("The investments product cash account must require a member."))
                if cash_acc.account_type not in ['liability_current', 'liability_non_current']:
                    raise ValidationError(_("The investments product cash account must be of liability type."))
                if cash_acc.account_product_type != 'investments_cash':
                    raise ValidationError(_("The investments product cash account must be of type 'investments_cash'."))
                
            # Check cash profit account
            if record.investments_product_cash_profit_account_id:
                cash_profit_acc = record.investments_product_cash_profit_account_id
                if not cash_profit_acc.requires_member:
                    raise ValidationError(_("The investments product cash profit account must require a member."))
                if cash_profit_acc.account_type not in ['liability_current', 'liability_non_current']:
                    raise ValidationError(_("The investments product cash profit account must be of liability type."))
                if cash_profit_acc.account_product_type != 'investments_cash_profit':
                    raise ValidationError(_("The investments product cash profit account must be of type 'investments_cash_profit'."))

            # Check investment account
            if record.investments_product_account_id:
                inv_acc = record.investments_product_account_id
                if not inv_acc.requires_member:
                    raise ValidationError(_("The investments product account must require a member."))
                if inv_acc.account_type not in ['asset_current', 'asset_non_current']:
                    raise ValidationError(_("The investments product account must be of asset type."))
                if inv_acc.account_product_type != 'investments':
                    raise ValidationError(_("The investments product account must be of type 'investments'."))