import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

class ProcessJournalEntriesWizard(models.TransientModel):
    _name = 'process.journal.entries.wizard'
    _description = 'Process Journal Entries Wizard'

    def action_process_journal_entries(self):
        """Process all posted journal entries and create savings, shares, or loan accounts."""
        _logger.info("Starting journal entries processing for savings, shares, and loans")

        # Fetch all posted journal entries, sorted by date
        journal_entries = self.env['account.move'].search(
            [('state', '=', 'posted')],
            order='date asc, id asc'
        )

        processed_count = 0
        error_messages = []

        for move in journal_entries:
            for line in move.line_ids:
                try:
                    # Skip if no member_id or not a relevant account_product_type
                    if not line.member_id or line.account_product_type not in ('savings', 'shares', 'loans'):
                        continue

                    member = self.env['res.partner'].search([('member_id', '=', line.member_id)], limit=1)
                    if not member:
                        _logger.warning("Member with ID %s not found for journal line %s", line.member_id, line.id)
                        continue

                    if line.account_product_type == 'savings':
                        self._process_savings_line(line, member)
                    elif line.account_product_type == 'shares':
                        self._process_shares_line(line, member)
                    elif line.account_product_type == 'loans':
                        self._process_loans_line(line, member)

                    processed_count += 1

                except Exception as e:
                    _logger.error("Error processing journal line %s: %s", line.id, str(e))
                    error_messages.append(
                        _("Error processing journal line %s in entry %s: %s") % (line.id, move.name, str(e))
                    )
                    self.env.cr.rollback()
                    continue

        # Log summary and return notification
        _logger.info("Completed processing %d journal lines", processed_count)
        message = _("Processed %d journal lines successfully.") % processed_count
        if error_messages:
            message += _("\nThe following errors occurred:\n%s") % "\n".join(error_messages)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Journal Entries Processing Summary'),
                'message': message,
                'sticky': True,
            }
        }

    def _process_savings_line(self, line, member):
        """Process a savings journal line and create a savings account if needed."""
        # Find the savings product linked to this account
        product = self.env['sacco.savings.product'].search([
            ('savings_product_account_id', '=', line.account_id.id)
        ], limit=1)

        if not product:
            _logger.warning("No savings product found for account %s in line %s", line.account_id.code, line.id)
            return

        # Check for existing savings account
        savings_account = self.env['sacco.savings.account'].search([
            ('member_id', '=', member.id),
            ('product_id', '=', product.id),
            ('currency_id', '=', product.currency_id.id)
        ], limit=1)

        if not savings_account:
            # Create a new savings account
            savings_vals = {
                'member_id': member.id,
                'product_id': product.id,
                'currency_id': product.currency_id.id,
                'state': 'active',
                'initial_deposit_date': line.move_id.date,
            }
            savings_account = self.env['sacco.savings.account'].create(savings_vals)
            _logger.info("Created savings account %s for member %s", savings_account.name, member.member_id)

    def _process_shares_line(self, line, member):
        """Process a shares journal line and create a shares account if needed."""
        # Find the shares product linked to this account
        product = self.env['sacco.shares.product'].search([
            ('original_shares_product_account_id', '=', line.account_id.id)
        ], limit=1)

        if not product:
            _logger.warning("No shares product found for account %s in line %s", line.account_id.code, line.id)
            return

        # Check for existing shares account
        shares_account = self.env['sacco.shares.account'].search([
            ('member_id', '=', member.id),
            ('product_id', '=', product.id),
            ('currency_id', '=', product.currency_id.id)
        ], limit=1)

        if not shares_account:
            # Create a new shares account
            shares_vals = {
                'member_id': member.id,
                'product_id': product.id,
                'currency_id': product.currency_id.id,
                'state': 'active',
            }
            shares_account = self.env['sacco.shares.account'].create(shares_vals)
            _logger.info("Created shares account %s for member %s", shares_account.name, member.member_id)

    def _process_loans_line(self, line, member):
        """Process a loans journal line, create a loan if needed, and update loan_id."""
        # Find the loan product linked to this account
        loan_type = self.env['sacco.loan.type'].search([
            ('loan_account_id', '=', line.account_id.id)
        ], limit=1)

        if not loan_type:
            _logger.warning("No loan product found for account %s in line %s", line.account_id.code, line.id)
            return

        # Check for existing loan
        loan = self.env['sacco.loan.loan'].search([
            ('client_id', '=', member.id),
            ('loan_type_id', '=', loan_type.id),
            ('state', 'in', ['open', 'disburse', 'approve', 'close']),
            ('loan_account_id', '=', line.account_id.id)
        ], limit=1)

        amount = line.debit if line.debit > 0 else line.credit  # Assuming disbursement is positive
        vdate = line.move_id.date

        if not loan:
            # Ensure paying_account_id and pay_account are set from the loan type
            if not loan_type.default_paying_account_id:
                raise ValidationError(
                    _("Loan type '%s' has no default paying account configured. Please set one.") % loan_type.name
                )
            if not loan_type.default_paying_account_id.account_id:
                raise ValidationError(
                    _("Default paying account for loan type '%s' has no linked accounting account.") % loan_type.name
                )

            # Create a new loan up to 'open' state
            loan_vals = {
                'client_id': member.id,
                'loan_type_id': loan_type.id,
                'loan_amount': amount,
                'loan_term': 60,  # Default as per requirement
                'interest_rate': loan_type.rate or 0.0,
                'currency_id': loan_type.currency_id.id,
                'state': 'draft',
                'request_date': vdate,
                'approve_date': vdate,
                'disbursement_date': vdate,
                'user_id': self.env.user.id,
                'company_id': self.env.company.id,
                'loan_account_id': loan_type.loan_account_id.id,
                'disburse_journal_id': loan_type.disburse_journal_id.id,
                'paying_account_id': loan_type.default_paying_account_id.id,  # Set the paying account
                'pay_account': loan_type.default_paying_account_id.account_id.id,  # Explicitly set pay_account
            }
            loan = self.env['sacco.loan.loan'].create(loan_vals)
            loan.action_confirm_loan()
            loan.action_approve_loan()
            loan.action_disburse_loan()
            loan.action_open_loan()
            loan.compute_installment(vdate)
            _logger.info("Created loan %s for member %s", loan.name, member.member_id)

            # Update the journal line with the loan_id
            line.write({'loan_id': loan.name})