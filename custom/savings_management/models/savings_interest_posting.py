from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
import logging
from datetime import datetime, timedelta
_logger = logging.getLogger(__name__)

class InterestPosting(models.Model):
    _name = 'sacco.interest.posting'
    _description = 'Interest Posting'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Reference', default='/', copy=False, readonly=True)
    savings_product_id = fields.Many2one(
        'sacco.savings.product',
        string='Savings Product',
        required=True,
        readonly=True
    )
    interest_to_post = fields.Float(
        string='Interest to Post',
        compute='_compute_interest_to_post',
        store=True,
        readonly=True,
        digits='Account'
    )
    posting_date = fields.Date(
        string='Posting Date',
        required=True,
        default=fields.Date.today,
        readonly=True,
        help="Date used for the accounting journal entry."
    )
    state = fields.Selection([
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], string='State', default='pending', tracking=True)
    journal_entry_id = fields.Many2one(
        'account.move',
        string='Journal Entry',
        readonly=True,
        help="Associated journal entry for this interest posting."
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        readonly=True
    )

    @api.model
    def create(self, vals):
        if vals.get('name', '/') == '/':
            vals['name'] = self.env['ir.sequence'].next_by_code('sacco.interest.posting') or '/'
        return super().create(vals)

    @api.depends('savings_product_id', 'posting_date')
    def _compute_interest_to_post(self):
        for record in self:
            if record.savings_product_id and record.posting_date:
                # Calculate total interest based on all active savings accounts with non-zero balance
                savings_accounts = self.env['sacco.savings.account'].search([
                    ('product_id', '=', record.savings_product_id.id),
                    ('state', '=', 'active'),
                    ('balance', '>', 0.0),
                ])
                total_interest = 0.0
                for account in savings_accounts:
                    days = (record.posting_date - (account.last_interest_date or account.initial_deposit_date)).days
                    if days <= 0:
                        _logger.warning(
                            f"Non-positive days ({days}) for account {account.name}. "
                            f"last_interest_date: {account.last_interest_date}, "
                            f"initial_deposit_date: {account.initial_deposit_date}, "
                            f"posting_date: {record.posting_date}"
                        )
                        continue
                    interest = account._calculate_interest(days)
                    _logger.debug(
                        f"Account {account.name}: days={days}, balance={account.balance}, "
                        f"interest_rate={account.interest_rate}, period={account.period}, "
                        f"interest={interest}"
                    )
                    total_interest += interest
                record.interest_to_post = round(total_interest, 2)
                _logger.info(
                    f"Computed interest_to_post for posting {record.name}: {record.interest_to_post} "
                    f"based on {len(savings_accounts)} accounts"
                )
            else:
                record.interest_to_post = 0.0

    def action_confirm(self):
        self.ensure_one()
        if self.state != 'pending':
            raise ValidationError(_("Only pending interest postings can be confirmed."))

        # Fetch all active savings accounts with non-zero balance
        savings_accounts = self.env['sacco.savings.account'].search([
            ('product_id', '=', self.savings_product_id.id),
            ('state', '=', 'active'),
            ('balance', '>', 0.0),
        ])

        if not savings_accounts:
            raise ValidationError(_("No eligible savings accounts found for interest posting."))

        # Prepare journal entry
        move_vals = {
            'date': self.posting_date,
            'ref': f"Interest Posting - {self.name}",
            'journal_id': self.savings_product_id.savings_product_journal_id.id,
            'company_id': self.company_id.id,
        }
        move = self.env['account.move'].create(move_vals)

        # Journal entry lines
        lines = []
        total_interest = 0.0

        # Debit: Interest Expense Account (single line)
        if self.interest_to_post > 0:
            lines.append((0, 0, {
                'account_id': self.savings_product_id.interest_account_id.id,
                'debit': self.interest_to_post,
                'name': f"Interest Expense - {self.savings_product_id.name}",
                'date_maturity': self.posting_date,
            }))
        else:
            _logger.warning(f"No interest to post for {self.name}: interest_to_post={self.interest_to_post}")
            raise ValidationError(_("No interest to post. Interest amount must be greater than zero."))

        # Credit: Interest Disbursement Account (one line per member)
        for account in savings_accounts:
            days = (self.posting_date - (account.last_interest_date or account.initial_deposit_date)).days
            if days <= 0:
                _logger.warning(
                    f"Skipping account {account.name} due to non-positive days ({days}). "
                    f"last_interest_date: {account.last_interest_date}, "
                    f"initial_deposit_date: {account.initial_deposit_date}, "
                    f"posting_date: {self.posting_date}"
                )
                continue
            interest_amount = account._calculate_interest(days)
            interest_amount = round(interest_amount, 2)
            if interest_amount > 0:
                total_interest += interest_amount
                lines.append((0, 0, {
                    'account_id': self.savings_product_id.interest_disbursement_account_id.id,
                    'credit': interest_amount,
                    'partner_id': account.member_id.id,
                    'member_id': account.member_id.member_id,
                    'name': f"Interest Credit - {account.member_id.name}",
                    'date_maturity': self.posting_date,
                }))
                # Update last_interest_date
                account.last_interest_date = self.posting_date
                _logger.debug(
                    f"Added line for account {account.name}: interest_amount={interest_amount}"
                )
            else:
                _logger.debug(
                    f"Skipping account {account.name}: interest_amount={interest_amount} (not positive)"
                )

        total_interest = round(total_interest, 2)
        _logger.info(
            f"Total interest calculated during confirmation for {self.name}: {total_interest}, "
            f"interest_to_post: {self.interest_to_post}, lines created: {len(lines) - 1}"
        )

        # Allow for a small tolerance in floating-point comparison
        tolerance = 0.01
        if not lines[1:] or abs(total_interest - self.interest_to_post) > tolerance:
            _logger.error(
                f"Interest mismatch for {self.name}: "
                f"total_interest={total_interest}, interest_to_post={self.interest_to_post}, "
                f"difference={abs(total_interest - self.interest_to_post)}, "
                f"number of credit lines={len(lines) - 1}"
            )
            raise ValidationError(_(
                "Interest calculation mismatch: Total interest calculated (%s) does not match "
                "the expected interest to post (%s). Difference: %s. "
                "Please check the savings accounts and their interest calculations."
            ) % (total_interest, self.interest_to_post, abs(total_interest - self.interest_to_post)))

        move.line_ids = lines
        move.action_post()
        self.journal_entry_id = move.id
        self.state = 'confirmed'
        _logger.info(f"Successfully confirmed interest posting {self.name}")

    def action_cancel(self):
        self.ensure_one()
        if self.state == 'confirmed' and self.journal_entry_id:
            raise ValidationError(_("Cannot cancel a confirmed posting with a journal entry. Delete the journal entry first."))
        self.state = 'cancelled'

    def unlink(self):
        for posting in self:
            if posting.state == 'confirmed' and posting.journal_entry_id:
                if self.env.context.get('force_delete'):
                    posting.journal_entry_id.unlink()
                else:
                    raise UserError(_(
                        "Cannot delete a confirmed interest posting with a journal entry. "
                        "Set the journal entry to draft and delete it first, or use force delete."
                    ))
            elif posting.journal_entry_id:
                posting.journal_entry_id.unlink()
        return super().unlink()

    @api.model
    def cron_create_interest_postings(self):
        """Cron job to auto-create interest postings based on savings product period."""
        today = fields.Date.today()
        products = self.env['sacco.savings.product'].search([])
        for product in products:
            last_posting = self.search([
                ('savings_product_id', '=', product.id),
                ('state', '=', 'confirmed'),
            ], order='posting_date desc', limit=1)

            next_date = last_posting.posting_date if last_posting else today
            if product.period == 'daily':
                next_date += relativedelta(days=1)
            elif product.period == 'weekly':
                next_date += relativedelta(weeks=1)
            elif product.period == 'monthly':
                next_date += relativedelta(months=1)
            elif product.period == 'semi_annually':
                next_date += relativedelta(months=6)
            elif product.period == 'annually':
                next_date += relativedelta(years=1)

            if next_date <= today:
                self.create({
                    'savings_product_id': product.id,
                    'posting_date': today,
                })
                _logger.info(f"Created interest posting for product {product.name} on {today}")