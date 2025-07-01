import os
import base64
import pandas as pd
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime

# Configure logging to write to both a file and the terminal
_logger = logging.getLogger(__name__)

log_file_path = r"D:\code part 2\OMNI-TECH\Timesheets\Contract Period Jan - June 2025\Ysave Data Transfer\member_statement_scripts\General migration 3\Scd_import.log"
if not any(isinstance(handler, logging.FileHandler) for handler in _logger.handlers):
    file_handler = logging.FileHandler(log_file_path)
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
    file = fields.Binary(
        string='Upload Excel File',
        required=True,
        help="Upload the Excel file containing journal entry data."
    )
    filename = fields.Char(
        string='Filename',
        help="Name of the uploaded file."
    )

    def action_import_external(self):
        """Import journal entries from the uploaded Excel file, one entry per row."""
        if not self.file:
            raise UserError(_("Please upload an Excel file."))

        error_messages = []  # Initialize error_messages list
        processed_entries = 0  # Track processed entries
        _logger.info("Starting journal entries import process from uploaded file: %s", self.filename)

        try:
            file_data = base64.b64decode(self.file)
            df = pd.read_excel(file_data, engine='openpyxl', parse_dates=['VDATE'])

            # Define required columns
            required_columns = ['Cat', 'ACODE', 'AmtUSD', 'AMOUNT', 'VDATE', 'TTYPE', 'PAYDET', 'MemberID', 'ProductID', 'LoanID']
            account_product_types = [
                'savings', 'savings_interest', 'shares', 'investments',
                'investments_cash', 'investments_cash_profit', 'loans', 'loans_interest'
            ]

            # Validate required columns
            if not all(col in df.columns for col in required_columns):
                missing_cols = [col for col in required_columns if col not in df.columns]
                _logger.error("Missing required columns in %s: %s", self.filename, missing_cols)
                error_messages.append(
                    _("Excel file '%s' is missing required columns: %s") % (self.filename, ', '.join(missing_cols))
                )
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Import Error'),
                        'message': "\n".join(error_messages),
                        'type': 'warning',
                        'sticky': True,
                    }
                }

            # Process each row in the Excel file
            for index, row in df.iterrows():
                try:
                    amount = float(row['AMOUNT']) if pd.notna(row['AMOUNT']) else 0.0
                    amt_usd = float(row['AmtUSD']) if pd.notna(row['AmtUSD']) else 0.0
                    ttype = str(row['TTYPE']).strip().upper() if pd.notna(row['TTYPE']) else ''
                    # Handle VDATE conversion, supporting both datetime and string inputs
                    if pd.notna(row['VDATE']):
                        if isinstance(row['VDATE'], datetime):
                            vdate = row['VDATE'].strftime('%Y-%m-%d')
                        else:
                            # Try common date formats if it's a string
                            vdate_str = str(row['VDATE'])
                            try:
                                vdate = datetime.strptime(vdate_str, '%Y-%m-%d %H:%M:%S').strftime('%Y-%m-%d')
                            except ValueError:
                                try:
                                    vdate = datetime.strptime(vdate_str, '%m/%d/%Y').strftime('%Y-%m-%d')
                                except ValueError:
                                    try:
                                        vdate = datetime.strptime(vdate_str, '%d-%m-%Y').strftime('%Y-%m-%d')
                                    except ValueError:
                                        raise ValueError(f"Unable to parse VDATE '{vdate_str}' for row {index}")
                    else:
                        raise ValueError("VDATE is missing or invalid for row %d" % index)
                    paydet = str(row['PAYDET']).strip() if pd.notna(row['PAYDET']) else f"Transaction Line {index + 1}"
                    member_id_raw = row['MemberID']
                    member_id = str(int(member_id_raw)) if pd.notna(member_id_raw) and isinstance(member_id_raw, (int, float)) else str(member_id_raw).strip() if pd.notna(member_id_raw) else False
                    loan_id_raw = row['LoanID']
                    loan_id = str(int(loan_id_raw)) if pd.notna(loan_id_raw) and isinstance(loan_id_raw, (int, float)) else str(loan_id_raw).strip() if pd.notna(loan_id_raw) else False
                    product_id = str(row['ProductID']).strip() if pd.notna(row['ProductID']) else False
                    acode = str(row['ACODE']).strip() if pd.notna(row['ACODE']) else False

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
                                _logger.info("Member with ID %s not found for row %d. Creating new SACCO member.", member_id, index)
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
                                _logger.info("Created new SACCO member with ID %s for row %d", member_id, index)
                        except Exception as e:
                            _logger.error("Failed to create SACCO member with ID %s for row %d: %s", member_id, index, str(e))
                            error_messages.append(
                                _("Failed to create SACCO member with ID %s for row %d: %s") % (member_id, index, str(e))
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
                                _logger.warning("No account found for ProductID %s for row %d", product_id, index)
                        except Exception as e:
                            _logger.error("Error searching for account for ProductID %s in row %d: %s", product_id, index, str(e))
                            error_messages.append(
                                _("Error searching for account for ProductID %s in row %d: %s") % (product_id, index, str(e))
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

                    # Initialize the journal entry for this row
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

                    # Create the primary journal entry line
                    line_vals = {
                        'account_id': account.id,
                        'partner_id': member.id if member else False,
                        'name': paydet,
                    }
                    if has_amt_usd and usd_currency:
                        line_vals['currency_id'] = usd_currency.id
                        if ttype == 'D':
                            line_vals.update({
                                'debit': abs(amount),
                                'credit': 0.0,
                                'amount_currency': abs(amt_usd),
                            })
                            # Add matching credit to collection account
                            collection_line_vals = {
                                'account_id': self.collection_account_id.id,
                                'name': f"Matching credit for {paydet}",
                                'debit': 0.0,
                                'credit': abs(amount),
                                'amount_currency': -abs(amt_usd) if has_amt_usd else 0.0,
                                'currency_id': usd_currency.id if has_amt_usd else False,
                            }
                            move_vals['line_ids'].append((0, 0, collection_line_vals))
                        elif ttype == 'C':
                            line_vals.update({
                                'debit': 0.0,
                                'credit': abs(amount),
                                'amount_currency': -abs(amt_usd),
                            })
                            # Add matching debit to collection account
                            collection_line_vals = {
                                'account_id': self.collection_account_id.id,
                                'name': f"Matching debit for {paydet}",
                                'debit': abs(amount),
                                'credit': 0.0,
                                'amount_currency': abs(amt_usd) if has_amt_usd else 0.0,
                                'currency_id': usd_currency.id if has_amt_usd else False,
                            }
                            move_vals['line_ids'].append((0, 0, collection_line_vals))
                        else:
                            _logger.warning("Invalid TTYPE '%s' for row %d. Skipping entry.", ttype, index)
                            error_messages.append(_("Invalid TTYPE '%s' in row %d of file '%s'") % (ttype, index, self.filename))
                            continue
                    else:
                        if ttype == 'D':
                            line_vals.update({
                                'debit': abs(amount),
                                'credit': 0.0,
                            })
                            # Add matching credit to collection account
                            collection_line_vals = {
                                'account_id': self.collection_account_id.id,
                                'name': f"Matching credit for {paydet}",
                                'debit': 0.0,
                                'credit': abs(amount),
                            }
                            move_vals['line_ids'].append((0, 0, collection_line_vals))
                        elif ttype == 'C':
                            line_vals.update({
                                'debit': 0.0,
                                'credit': abs(amount),
                            })
                            # Add matching debit to collection account
                            collection_line_vals = {
                                'account_id': self.collection_account_id.id,
                                'name': f"Matching debit for {paydet}",
                                'debit': abs(amount),
                                'credit': 0.0,
                            }
                            move_vals['line_ids'].append((0, 0, collection_line_vals))
                        else:
                            _logger.warning("Invalid TTYPE '%s' for row %d. Skipping entry.", ttype, index)
                            error_messages.append(_("Invalid TTYPE '%s' in row %d of file '%s'") % (ttype, index, self.filename))
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
                    _logger.info("Created journal entry for row %d in file %s: %s", index, self.filename, move.name)

                    total_debit = sum(line.debit for line in move.line_ids)
                    total_credit = sum(line.credit for line in move.line_ids)
                    if abs(total_debit - total_credit) >= 0.01:
                        _logger.warning(
                            "Journal entry %s for row %d does not balance (Debit: %s, Credit: %s). Adding balancing line.",
                            move.name, index, total_debit, total_credit
                        )
                        difference = total_debit - total_credit
                        balancing_line_vals = {
                            'account_id': self.balancing_account_id.id,
                            'name': f"Balancing adjustment for {move.name}",
                            'partner_id': False,
                            'member_id': False,
                            'loan_id': False,
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
                        _logger.info("Posted journal entry %s for row %d in file %s", move.name, index, self.filename)
                        processed_entries += 1
                    except Exception as e:
                        _logger.warning("Failed to post journal entry %s for row %d: %s. Keeping in draft state.", move.name, index, str(e))
                        if move.state != 'draft':
                            move.button_draft()
                        error_messages.append(
                            _("Failed to post journal entry %s for row %d: %s. Saved as draft.") % (move.name, index, str(e))
                        )

                except Exception as e:
                    _logger.error("Error processing row %d in file %s: %s", index, self.filename, str(e))
                    error_messages.append(
                        _("Error processing row %d in file '%s': %s") % (index, self.filename, str(e))
                    )
                    if 'move' in locals() and move.state != 'draft':
                        try:
                            move.button_draft()
                        except Exception as draft_error:
                            _logger.error("Failed to revert journal entry %s to draft: %s", move.name, str(draft_error))
                            error_messages.append(
                                _("Failed to revert journal entry %s to draft: %s") % (move.name, str(draft_error))
                            )

        except Exception as e:
            _logger.error("Error processing file %s: %s", self.filename, str(e))
            error_messages.append(
                _("Error processing file '%s': %s") % (self.filename, str(e))
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