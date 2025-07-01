import psycopg2
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime

# Configure logging to write to both a file and the terminal
_logger = logging.getLogger(__name__)

log_file_path = r"D:\code part 2\OMNI-TECH\Timesheets\Contract Period Jan - June 2025\Ysave Data Transfer\member_statement_scripts\General migration 3\Scd_import.log"
if not any(isinstance(handler, logging.FileHandler) for handler in _logger.handlers):
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setLevel(logging.WARNING)  # Capture WARNING and above
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    _logger.addHandler(file_handler)

if not any(isinstance(handler, logging.StreamHandler) for handler in _logger.handlers):
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    _logger.addHandler(stream_handler)

class TheadIdImportWizard(models.TransientModel):
    _name = 'theadid.import.wizard'
    _description = 'Import Wizard for TheadId Grouped Journal Entries'

    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        required=True,
        help="Select the journal to use for the journal entries."
    )
    collection_account_id = fields.Many2one(
        'account.account',
        string='Default Collection Account',
        domain="[('deprecated', '=', False)]",
        required=True,
        help="Default account to use when MemberID or ProductID is missing."
    )
    balancing_account_id = fields.Many2one(
        'account.account',
        string='Default Balancing Account',
        domain="[('deprecated', '=', False)]",
        required=True,
        help="Account to use for balancing journal entries that do not balance."
    )
    years = fields.Char(
        string='Years to Import',
        default='2022,2023,2024,2025',
        required=True,
        help="Comma-separated list of years to import transactions (e.g., 2022,2023,2024,2025)."
    )

    def get_date_range(self, year):
        first_date = datetime(year, 1, 1).date()
        last_date = datetime(year, 12, 31).date()
        return first_date, last_date

    def action_import_transactions_by_year(self):
        """Import journal entries from transml_clean table based on selected years."""
        error_messages = []
        processed_entries = 0
        _logger.info("Starting journal entries import process from transml_clean table")

        try:
            # Parse years from the field
            years = [int(year.strip()) for year in self.years.split(',')]
            _logger.info("Processing transactions for years: %s", years)

            # Connect to the external ysave_data database
            conn = psycopg2.connect(
                dbname="ysave_data",
                user="postgres",
                password="123",
                host="localhost"
            )
            cursor = conn.cursor()

            account_product_types = [
                'savings', 'savings_interest', 'shares', 'investments',
                'investments_cash', 'investments_cash_profit', 'loans', 'loans_interest'
            ]

            for year in years:
                first_date, last_date = self.get_date_range(year)
                _logger.info("Processing data for year %d, date range: %s to %s", year, first_date, last_date)

                # Fetch data from transml_clean for the current year
                select_query = """
                SELECT memberid, productid, vdate, ttype, amount, amtusd, paydet, collacc, loanid_new, idno, child_number
                FROM transml_clean
                WHERE vdate >= %s AND vdate <= %s
                """
                cursor.execute(select_query, (first_date, last_date))
                rows = cursor.fetchall()
                _logger.info("Found %d records for year %d", len(rows), year)

                for row in rows:
                    try:
                        memberid, productid, vdate, ttype, amount, amtusd, paydet, collacc, loanid_new, idno, child_number = row

                        amount = float(amount) if amount is not None else 0.0
                        amt_usd = float(amtusd) if amtusd is not None else 0.0
                        ttype = str(ttype).strip().upper() if ttype is not None else ''
                        vdate = vdate.strftime('%Y-%m-%d') if vdate else datetime.now().strftime('%Y-%m-%d')
                        paydet = str(paydet).strip() if paydet is not None else f"Transaction {idno}"
                        member_id = str(memberid).strip() if memberid is not None else False
                        loan_id = str(loanid_new).strip() if loanid_new is not None else False
                        product_id = str(productid).strip() if productid is not None else False
                        acode = str(collacc).strip() if collacc is not None else False

                        # Find or create the member if MemberID is provided
                        member = False
                        if member_id:
                            try:
                                members = self.env['res.partner'].search([('member_id', '=', member_id)], limit=1)
                                if not members:
                                    self.env.cr.execute("""
                                        SELECT id
                                        FROM res_partner
                                        WHERE CAST(REGEXP_REPLACE("member_id", '^0+', '') AS TEXT) = %s
                                        LIMIT 1
                                    """, (member_id,))
                                    member_id_result = self.env.cr.fetchone()
                                    if member_id_result:
                                        member = self.env['res.partner'].browse(member_id_result[0])
                                else:
                                    member = members

                                if not member:
                                    _logger.info("Member with ID %s not found for idno %s. Creating new SACCO member.", member_id, idno)
                                    member_vals = {
                                        'is_sacco_member': True,
                                        'member_id': member_id,
                                        'first_name': 'Unknown',
                                        'last_name': f"Member {member_id}",
                                        'name': f"Unknown Member {member_id}",
                                        'email': f"member_{member_id}@example.com",
                                        'phone': '0000000000',
                                        'member_type': 'individual',
                                        'role': 'member',
                                        'membership_status': 'inactive',
                                    }
                                    member = self.env['res.partner'].create(member_vals)
                                    _logger.info("Created new SACCO member with ID %s for idno %s", member_id, idno)
                            except Exception as e:
                                _logger.error("Failed to create SACCO member with ID %s for idno %s: %s", member_id, idno, str(e))
                                error_messages.append(
                                    _("Failed to create SACCO member with ID %s for idno %s: %s") % (member_id, idno, str(e))
                                )
                                continue

                        # Determine the account to use
                        account = False
                        if member_id and product_id:
                            try:
                                account = self.env['account.account'].search([
                                    ('code', '=', product_id),
                                    ('account_product_type', 'in', account_product_types),
                                    ('deprecated', '=', False)
                                ], limit=1)
                                if not account:
                                    _logger.warning("No account found for ProductID %s for idno %s", product_id, idno)
                            except Exception as e:
                                _logger.error("Error searching for account for ProductID %s in idno %s: %s", product_id, idno, str(e))
                                error_messages.append(
                                    _("Error searching for account for ProductID %s in idno %s: %s") % (product_id, idno, str(e))
                                )

                        if not account:
                            if acode:
                                account = self.env['account.account'].search([
                                    ('code', '=', acode),
                                    ('deprecated', '=', False)
                                ], limit=1)
                            if not account:
                                account = self.collection_account_id
                            member = False

                        # Initialize the journal entry
                        move_vals = {
                            'date': vdate,
                            'ref': paydet,
                            'journal_id': self.journal_id.id,
                            'company_id': self.journal_id.company_id.id,
                            'line_ids': [],
                        }

                        # Handle currency and amount in USD if AmtUSD is provided
                        has_amt_usd = amt_usd != 0.0
                        usd_currency = self.env['res.currency'].search([('name', '=', 'USD')], limit=1) if has_amt_usd else False

                        # Create the primary journal entry line with idno as id
                        line_vals = {
                            'id': idno,  # Use idno as the ID of the move line
                            'account_id': account.id,
                            'partner_id': member.id if member else False,
                            'name': paydet,
                            'child_number': child_number,  # Add child_number field
                        }
                        if has_amt_usd and usd_currency:
                            line_vals['currency_id'] = usd_currency.id
                            if ttype == 'D':
                                line_vals.update({
                                    'debit': abs(amount),
                                    'credit': 0.0,
                                    'amount_currency': abs(amt_usd),
                                })
                                collection_line_vals = {
                                    'id': f"{idno}_coll",  # Unique ID for collection line
                                    'account_id': self.collection_account_id.id,
                                    'name': f"Matching credit for {paydet}",
                                    'debit': 0.0,
                                    'credit': abs(amount),
                                    'amount_currency': -abs(amt_usd) if has_amt_usd else 0.0,
                                    'currency_id': usd_currency.id if has_amt_usd else False,
                                    'child_number': child_number,
                                }
                                move_vals['line_ids'].append((0, 0, collection_line_vals))
                            elif ttype == 'C':
                                line_vals.update({
                                    'debit': 0.0,
                                    'credit': abs(amount),
                                    'amount_currency': -abs(amt_usd),
                                })
                                collection_line_vals = {
                                    'id': f"{idno}_coll",  # Unique ID for collection line
                                    'account_id': self.collection_account_id.id,
                                    'name': f"Matching debit for {paydet}",
                                    'debit': abs(amount),
                                    'credit': 0.0,
                                    'amount_currency': abs(amt_usd) if has_amt_usd else 0.0,
                                    'currency_id': usd_currency.id if has_amt_usd else False,
                                    'child_number': child_number,
                                }
                                move_vals['line_ids'].append((0, 0, collection_line_vals))
                            else:
                                _logger.warning("Invalid TTYPE '%s' for idno %s. Skipping entry.", ttype, idno)
                                error_messages.append(_("Invalid TTYPE '%s' for idno %s") % (ttype, idno))
                                continue
                        else:
                            if ttype == 'D':
                                line_vals.update({
                                    'debit': abs(amount),
                                    'credit': 0.0,
                                })
                                collection_line_vals = {
                                    'id': f"{idno}_coll",  # Unique ID for collection line
                                    'account_id': self.collection_account_id.id,
                                    'name': f"Matching credit for {paydet}",
                                    'debit': 0.0,
                                    'credit': abs(amount),
                                    'child_number': child_number,
                                }
                                move_vals['line_ids'].append((0, 0, collection_line_vals))
                            elif ttype == 'C':
                                line_vals.update({
                                    'debit': 0.0,
                                    'credit': abs(amount),
                                })
                                collection_line_vals = {
                                    'id': f"{idno}_coll",  # Unique ID for collection line
                                    'account_id': self.collection_account_id.id,
                                    'name': f"Matching debit for {paydet}",
                                    'debit': abs(amount),
                                    'credit': 0.0,
                                    'child_number': child_number,
                                }
                                move_vals['line_ids'].append((0, 0, collection_line_vals))
                            else:
                                _logger.warning("Invalid TTYPE '%s' for idno %s. Skipping entry.", ttype, idno)
                                error_messages.append(_("Invalid TTYPE '%s' for idno %s") % (ttype, idno))
                                continue

                        if account.account_product_type in account_product_types and member:
                            line_vals['member_id'] = member.member_id
                        else:
                            line_vals['member_id'] = False

                        if account.account_product_type in ('loans', 'loans_interest') and loan_id:
                            line_vals['loan_id'] = loan_id
                        else:
                            line_vals['loan_id'] = False

                        move_vals['line_ids'].append((0, 0, line_vals))

                        # Create and post the journal entry
                        move = self.env['account.move'].create(move_vals)
                        _logger.info("Created journal entry for idno %s: %s", idno, move.name)

                        total_debit = sum(line.debit for line in move.line_ids)
                        total_credit = sum(line.credit for line in move.line_ids)
                        if abs(total_debit - total_credit) >= 0.01:
                            _logger.warning(
                                "Journal entry %s for idno %s does not balance (Debit: %s, Credit: %s). Adding balancing line.",
                                move.name, idno, total_debit, total_credit
                            )
                            difference = total_debit - total_credit
                            balancing_line_vals = {
                                'id': f"{idno}_bal",  # Unique ID for balancing line
                                'account_id': self.balancing_account_id.id,
                                'name': f"Balancing adjustment for {move.name}",
                                'partner_id': False,
                                'member_id': False,
                                'loan_id': False,
                                'child_number': child_number,
                            }
                            if difference > 0:
                                balancing_line_vals.update({
                                    'debit': 0.0,
                                    'credit': difference,
                                })
                            else:
                                balancing_line_vals.update({
                                    'debit': abs(difference),
                                    'credit': 0.0,
                                })
                            move.write({'line_ids': [(0, 0, balancing_line_vals)]})
                            _logger.info(
                                "Added balancing line to journal entry %s: %s to account %s",
                                move.name, difference, self.balancing_account_id.code
                            )

                        try:
                            move.action_post()
                            _logger.info("Posted journal entry %s for idno %s", move.name, idno)
                            processed_entries += 1
                        except Exception as e:
                            _logger.warning("Failed to post journal entry %s for idno %s: %s. Keeping in draft state.", move.name, idno, str(e))
                            if move.state != 'draft':
                                move.button_draft()
                            error_messages.append(
                                _("Failed to post journal entry %s for idno %s: %s. Saved as draft.") % (move.name, idno, str(e))
                            )

                    except Exception as e:
                        _logger.error("Error processing idno %s: %s", idno, str(e))
                        error_messages.append(
                            _("Error processing idno %s: %s") % (idno, str(e))
                        )
                        if 'move' in locals() and move.state != 'draft':
                            try:
                                move.button_draft()
                            except Exception as draft_error:
                                _logger.error("Failed to revert journal entry %s to draft: %s", move.name, str(draft_error))
                                error_messages.append(
                                    _("Failed to revert journal entry %s to draft: %s") % (move.name, str(draft_error))
                                )

            conn.close()

        except Exception as e:
            _logger.error("Error processing years from transml_clean: %s", str(e))
            error_messages.append(
                _("Error processing years from transml_clean: %s") % str(e)
            )

        _logger.info("Journal entries import process completed. Processed %d entries.", processed_entries)
        if error_messages:
            _logger.warning("Encountered errors during import:\n%s", "\n".join(error_messages))

        message = _(
            "Journal entries import completed. Processed %d entries successfully.\n"
        ) % processed_entries
        if error_messages:
            message += _("The following errors occurred during the import:\n%s") % "\n".join(error_messages)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Import Summary'),
                'message': message,
                'sticky': True,
            }
        }