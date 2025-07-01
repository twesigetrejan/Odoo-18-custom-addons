import os
import glob
import pandas as pd
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

# Configure logging to write to both a file and the terminal
_logger = logging.getLogger(__name__)

# Ensure the logger has both a file handler and a stream handler
log_file_path = r"D:\code part 2\OMNI-TECH\Timesheets\Contract Period Jan - June 2025\Ysave Data Transfer\member_statement_scripts\General migration\TheadId_Groups\theadid_import.log"
if not any(isinstance(handler, logging.FileHandler) for handler in _logger.handlers):
    file_handler = logging.FileHandler(log_file_path)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    _logger.addHandler(file_handler)
# Ensure terminal output (StreamHandler) is present
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
    folder_path = fields.Char(
        string='Folder Path',
        default=r"E:\code part 2\OMNI-TECH\Timesheets\Contract Period Jan - June 2025\Ysave Data Transfer\member_statement_scripts\General migration\TheadId_Groups",
        help="Path to the folder containing Excel files for TheadId groups."
    )

    def action_import(self):
        """
        Import journal entries from all Excel files in the specified folder.
        Each Excel file represents a single journal entry.
        """
        _logger.info("Starting TheadId grouped journal entries import process")

        # Validate folder path
        if not self.folder_path or not os.path.isdir(self.folder_path):
            raise ValidationError(_("The specified folder path '%s' is invalid or does not exist.") % self.folder_path)

        # Get all Excel files in the folder
        excel_files = glob.glob(os.path.join(self.folder_path, "*.xlsx")) + glob.glob(os.path.join(self.folder_path, "*.xls"))
        if not excel_files:
            raise ValidationError(_("No Excel files found in the folder '%s'.") % self.folder_path)

        # Define required columns based on the new column names
        required_columns = ['ACODE', 'AMOUNT', 'VDATE', 'TTYPE', 'PAYDET', 'MemberID', 'ProductID']
        account_product_types = [
            'savings', 'savings_interest', 'shares', 'investments',
            'investments_cash', 'investments_cash_profit', 'loans', 'loans_interest'
        ]

        # Track the number of successfully processed files and any errors
        processed_files = 0
        error_messages = []

        for file_path in excel_files:
            _logger.info("Processing Excel file: %s", file_path)

            # Initialize the journal entry values
            move_vals = None
            move = None
            try:
                # Read the Excel file
                df = pd.read_excel(file_path)

                # Validate required columns
                if not all(col in df.columns for col in required_columns):
                    missing_cols = [col for col in required_columns if col not in df.columns]
                    _logger.error("Missing required columns in %s: %s", file_path, missing_cols)
                    error_messages.append(
                        _("Excel file '%s' is missing required columns: %s") % (file_path, ', '.join(missing_cols))
                    )
                    continue

                # Get the first row's VDATE and PAYDET for the journal entry
                vdate = df['VDATE'].iloc[0]
                paydet = df['PAYDET'].iloc[0] if pd.notna(df['PAYDET'].iloc[0]) else f"TheadId Transaction - {os.path.basename(file_path)}"

                # Initialize the journal entry
                move_vals = {
                    'date': vdate,
                    'ref': paydet,
                    'journal_id': self.journal_id.id,
                    'company_id': self.journal_id.company_id.id,
                    'line_ids': [],
                }

                # Process each row in the Excel file to create journal entry lines
                for index, row in df.iterrows():
                    try:
                        amount = float(row['AMOUNT']) if pd.notna(row['AMOUNT']) else 0.0
                        ttype = str(row['TTYPE']).strip().upper() if pd.notna(row['TTYPE']) else ''
                        # Normalize MemberID to handle numeric/float values and leading zeros
                        member_id_raw = row['MemberID']
                        member_id = False
                        if pd.notna(member_id_raw):
                            # Convert to string, handle float/int, and strip leading zeros for comparison
                            if isinstance(member_id_raw, (int, float)):
                                member_id = str(int(member_id_raw))  # Convert 122.0 or 122 to '122'
                            else:
                                member_id = str(member_id_raw).strip()  # Handle string input
                        product_id = str(row['ProductID']).strip() if pd.notna(row['ProductID']) else False
                        name = str(row['PAYDET']).strip() if pd.notna(row['PAYDET']) else f"Line {index + 1}"

                        # Find or create the member if MemberID is provided
                        member = False
                        if member_id:
                            try:
                                # Search for the member, comparing the normalized MemberID
                                members = self.env['res.partner'].search([('member_id', '=', member_id)], limit=1)
                                if not members:
                                    # If not found, try searching with leading zeros stripped in the database
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
                                    # Member not found, create a new res.partner record with default values
                                    _logger.info("Member with ID %s not found for row %d in file %s. Creating new SACCO member.", member_id, index, file_path)
                                    member_vals = {
                                        'is_sacco_member': True,
                                        'member_id': member_id,
                                        'first_name': 'Unknown',
                                        'last_name': f"Member {member_id}",
                                        'name': f"Unknown Member {member_id}",  # Will be overridden by _onchange_sacco_names in res.partner
                                        'email': f"member_{member_id}@example.com",  # Default email to satisfy constraint
                                        'phone': '0000000000',  # Default phone to satisfy constraint
                                        'member_type': 'individual',
                                        'role': 'member',
                                        'membership_status': 'inactive',
                                    }
                                    member = self.env['res.partner'].create(member_vals)
                                    _logger.info("Created new SACCO member with ID %s for row %d in file %s", member_id, index, file_path)
                            except Exception as e:
                                _logger.error("Failed to create SACCO member with ID %s for row %d in file %s: %s", member_id, index, file_path, str(e))
                                error_messages.append(
                                    _("Failed to create SACCO member with ID %s for row %d in file '%s': %s") % (member_id, index, file_path, str(e))
                                )
                                continue  # Skip this row if member creation fails

                        # Determine the account to use
                        account = False
                        if member_id and product_id:
                            try:
                                # Look for an account matching the ProductID and account_product_type
                                account = self.env['account.account'].search([
                                    ('code', '=', product_id),
                                    ('account_product_type', 'in', account_product_types),
                                    ('deprecated', '=', False)
                                ], limit=1)
                                if not account:
                                    _logger.warning(
                                        "No account found for ProductID %s with account_product_type in %s for row %d in file %s",
                                        product_id, account_product_types, index, file_path
                                    )
                            except Exception as e:
                                _logger.error("Error searching for account for ProductID %s in file %s: %s", product_id, file_path, str(e))
                                error_messages.append(
                                    _("Error searching for account for ProductID %s in file '%s': %s") % (product_id, file_path, str(e))
                                )

                        # If no account is found or MemberID/ProductID is missing, use the default collection account
                        if not account:
                            account = self.collection_account_id
                            member = False  # Don't set member if using the default account

                        # Create the journal entry line based on TTYPE
                        line_vals = {
                            'account_id': account.id,
                            'partner_id': member.id if member else False,
                            'name': name,
                        }

                        if ttype == 'D':
                            line_vals.update({
                                'debit': amount,
                                'credit': 0.0,
                            })
                        elif ttype == 'C':
                            line_vals.update({
                                'debit': 0.0,
                                'credit': amount,
                            })
                        else:
                            _logger.warning("Invalid TTYPE '%s' for row %d in file %s. Skipping line.", ttype, index, file_path)
                            continue

                        # Set member_id if the account has an account_product_type and a member is found
                        if account.account_product_type in account_product_types and member:
                            line_vals['member_id'] = member.member_id
                        else:
                            line_vals['member_id'] = False

                        move_vals['line_ids'].append((0, 0, line_vals))

                    except Exception as e:
                        _logger.error("Error processing row %d in file %s: %s", index, file_path, str(e))
                        error_messages.append(
                            _("Error processing row %d in file '%s': %s") % (index, file_path, str(e))
                        )
                        continue  # Skip this row but continue with the next row

                # Create the journal entry if there are any lines
                if move_vals['line_ids']:
                    try:
                        move = self.env['account.move'].create(move_vals)
                        _logger.info("Created journal entry for file %s: %s", file_path, move.name)

                        # Check if the journal entry balances
                        total_debit = sum(line.debit for line in move.line_ids)
                        total_credit = sum(line.credit for line in move.line_ids)
                        if abs(total_debit - total_credit) >= 0.01:  # Allow for small rounding differences
                            _logger.warning(
                                "Journal entry %s for file %s does not balance (Debit: %s, Credit: %s). Adding balancing line.",
                                move.name, file_path, total_debit, total_credit
                            )
                            # Add a balancing line using the balancing_account_id
                            difference = total_debit - total_credit
                            balancing_line_vals = {
                                'account_id': self.balancing_account_id.id,
                                'name': f"Balancing adjustment for {move.name}",
                                'partner_id': False,
                                'member_id': False,
                            }
                            if difference > 0:
                                # Debit exceeds credit, add a credit line
                                balancing_line_vals.update({
                                    'debit': 0.0,
                                    'credit': difference,
                                })
                            else:
                                # Credit exceeds debit, add a debit line
                                balancing_line_vals.update({
                                    'debit': abs(difference),
                                    'credit': 0.0,
                                })
                            # Update the journal entry with the balancing line
                            move.write({'line_ids': [(0, 0, balancing_line_vals)]})
                            _logger.info(
                                "Added balancing line to journal entry %s: %s to account %s",
                                move.name, difference, self.balancing_account_id.code
                            )

                        # Try to post the journal entry
                        try:
                            move.action_post()
                            _logger.info("Posted journal entry %s for file %s", move.name, file_path)
                        except Exception as e:
                            _logger.warning(
                                "Failed to post journal entry %s for file %s: %s. Keeping in draft state.",
                                move.name, file_path, str(e)
                            )
                            # Ensure the move is in draft state
                            if move.state != 'draft':
                                move.button_draft()
                            error_messages.append(
                                _("Failed to post journal entry %s for file '%s': %s. Saved as draft.") % (move.name, file_path, str(e))
                            )

                        processed_files += 1

                    except Exception as e:
                        _logger.error("Error creating journal entry for file %s: %s", file_path, str(e))
                        error_messages.append(
                            _("Error creating journal entry for file '%s': %s") % (file_path, str(e))
                        )
                        # If the move was created but an error occurred, ensure it's in draft
                        if move and move.state != 'draft':
                            try:
                                move.button_draft()
                            except Exception as draft_error:
                                _logger.error("Failed to revert journal entry %s to draft: %s", move.name, str(draft_error))
                                error_messages.append(
                                    _("Failed to revert journal entry %s to draft: %s") % (move.name, str(draft_error))
                                )
                        continue

                else:
                    _logger.warning("No valid lines to create journal entry for file %s", file_path)
                    error_messages.append(
                        _("No valid lines to create journal entry for file '%s'") % file_path
                    )
                    continue

            except Exception as e:
                _logger.error("Error processing file %s: %s", file_path, str(e))
                error_messages.append(
                    _("Error processing file '%s': %s") % (file_path, str(e))
                )
                # If the move was created but an error occurred, ensure it's in draft
                if move and move.state != 'draft':
                    try:
                        move.button_draft()
                    except Exception as draft_error:
                        _logger.error("Failed to revert journal entry %s to draft: %s", move.name, str(draft_error))
                        error_messages.append(
                            _("Failed to revert journal entry %s to draft: %s") % (move.name, str(draft_error))
                        )
                continue

        # Log the summary of the import process
        _logger.info("TheadId grouped journal entries import process completed. Processed %d files.", processed_files)
        if error_messages:
            _logger.warning("Encountered errors during import:\n%s", "\n".join(error_messages))

        # Return a notification with the summary
        message = _(
            "TheadId grouped journal entries import completed. Processed %d files successfully.\n"
        ) % processed_files
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