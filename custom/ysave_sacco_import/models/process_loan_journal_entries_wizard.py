import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

class ProcessLoanJournalEntriesWizard(models.TransientModel):
    _name = 'process.loan.journal.entries.wizard'
    _description = 'Process Loan Journal Entries Wizard'

    def action_process_loan_journal_entries(self):
        """Process all posted journal entries related to loans and update or create loans."""
        _logger.info("Starting loan journal entries processing")

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
                    # Skip if no member_id or not a loan-related account_product_type
                    if not line.member_id or line.account_product_type not in ('loans', 'loans_interest'):
                        continue

                    # Skip if line.loan_id is already populated
                    if line.loan_id:
                        _logger.info("Skipping journal line %s as loan_id is already set to %s", line.id, line.loan_id)
                        continue

                    member = self.env['res.partner'].search([('member_id', '=', line.member_id)], limit=1)
                    if not member:
                        _logger.warning("Member with ID %s not found for journal line %s", line.member_id, line.id)
                        continue

                    self._process_loan_line(line, member)
                    processed_count += 1

                except Exception as e:
                    _logger.error("Error processing loan journal line %s: %s", line.id, str(e))
                    error_messages.append(
                        _("Error processing journal line %s in entry %s: %s") % (line.id, move.name, str(e))
                    )
                    self.env.cr.rollback()
                    continue

        # Log summary and return notification
        _logger.info("Completed processing %d loan journal lines", processed_count)
        message = _("Processed %d loan journal lines successfully.") % processed_count
        if error_messages:
            message += _("\nThe following errors occurred:\n%s") % "\n".join(error_messages)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Loan Journal Entries Processing Summary'),
                'message': message,
                'sticky': True,
            }
        }

    def _process_loan_line(self, line, member):
        """Process a loan journal line, update loan_id or create a new loan as needed."""
        # Step 1: Check for loan based on loan_account_id or interest_account_id
        domain = [
            ('state', 'in', ['open', 'disburse', 'approve', 'close']),
            ('client_id', '=', member.id),
            '|',  # Use OR condition to match either loan_account_id or interest_account_id
            ('loan_account_id', '=', line.account_id.id),
            ('loan_type_id.interest_account_id', '=', line.account_id.id)
        ]

        # Search for an existing loan for this member
        loan = self.env['sacco.loan.loan'].search(domain, limit=1)

        if loan:
            # If loan exists and line.loan_id is empty, update it
            if not line.loan_id:
                line.write({'loan_id': loan.name})
                _logger.info("Updated journal line %s with existing loan %s for member %s", 
                            line.id, loan.name, member.member_id)
            return  # Exit early since we found a loan

        # Step 2: If no loan exists, determine the loan type based on account_product_type
        if line.account_product_type == 'loans':
            loan_type = self.env['sacco.loan.type'].search([
                ('loan_account_id', '=', line.account_id.id)
            ], limit=1)
        elif line.account_product_type == 'loans_interest':
            loan_type = self.env['sacco.loan.type'].search([
                ('interest_account_id', '=', line.account_id.id)
            ], limit=1)
        else:
            _logger.warning("Unsupported account_product_type %s for journal line %s", 
                           line.account_product_type, line.id)
            return

        if not loan_type:
            _logger.warning("No loan product found for account %s in line %s", line.account_id.code, line.id)
            return

        # Step 3: If this is a disbursement line (account_product_type = 'loans'), create a new loan
        if line.account_product_type == 'loans':
            if not loan_type.default_paying_account_id:
                raise ValidationError(
                    _("Loan type '%s' has no default paying account configured. Please set one.") % loan_type.name
                )
            if not loan_type.default_paying_account_id.account_id:
                raise ValidationError(
                    _("Default paying account for loan type '%s' has no linked accounting account.") % loan_type.name
                )

            amount = line.debit if line.debit > 0 else line.credit  # Assuming disbursement is positive
            vdate = line.move_id.date

            # Create a new loan
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
                'paying_account_id': loan_type.default_paying_account_id.id,
                'pay_account': loan_type.default_paying_account_id.account_id.id,
            }
            loan = self.env['sacco.loan.loan'].create(loan_vals)
            loan.action_confirm_loan()
            loan.action_approve_loan()
            loan.action_disburse_loan()
            loan.action_open_loan()
            loan.compute_installment(vdate)
            _logger.info("Created loan %s for member %s", loan.name, member.member_id)

            # Update the journal line with the new loan_id
            line.write({'loan_id': loan.name})
        else:
            # For 'loans_interest' lines, if no loan exists, log a warning (we don't create a loan for interest lines)
            _logger.warning("No existing loan found for interest line %s (account %s) for member %s. A loan must be created first.",
                           line.id, line.account_id.code, member.member_id)