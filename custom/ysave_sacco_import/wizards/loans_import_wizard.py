import os
import glob
import pandas as pd
import logging
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime

_logger = logging.getLogger(__name__)

# Set the logger level to ERROR
_logger = logging.getLogger('loan_import_logger')
_logger.setLevel(logging.ERROR)
    
# Configure custom error logger
log_file_path = os.path.join(os.path.dirname(__file__), 'OdooLogs', 'Loans_import.log')  # Adjust path as needed
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)  # Ensure directory exists
error_logger = logging.getLogger('Loans_import')
error_logger.setLevel(logging.ERROR)
if not error_logger.handlers:  # Prevent duplicate handlers
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    error_logger.addHandler(file_handler)

_logger = logging.getLogger(__name__)

class LoansImportWizard(models.TransientModel):
    _name = 'loans.import.wizard'
    _description = 'Import Wizard for Loans'

    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        required=True,
        help="Select the journal to use for loan disbursements."
    )
    collection_account_id = fields.Many2one(
        'account.account',
        string='Default Collection Account',
        domain="[('deprecated', '=', False)]",
        required=True,
        help="Default account to use when MemberID or ProductID is missing."
    )
    folder_path = fields.Char(
        string='Folder Path',
        default=r"E:\code part 2\OMNI-TECH\Timesheets\Contract Period Jan - June 2025\Ysave Data Transfer\member_statement_scripts\General migration 2\Loans",
        help="Path to the folder containing Excel files for loan data."
    )

    def action_import(self):
        """
        Import loan records from Excel files in the specified folder.
        Each row in an Excel file represents a loan to be created in the 'disbursed' state.
        """
        _logger.info("Starting loan import process")

        # Validate folder path
        if not self.folder_path or not os.path.isdir(self.folder_path):
            raise ValidationError(_("The specified folder path '%s' is invalid or does not exist.") % self.folder_path)

        # Get all Excel files in the folder
        excel_files = glob.glob(os.path.join(self.folder_path, "*.xlsx")) + glob.glob(os.path.join(self.folder_path, "*.xls"))
        if not excel_files:
            raise ValidationError(_("No Excel files found in the folder '%s'.") % self.folder_path)

        # Define required columns based on the provided Excel format
        required_columns = [
            'memberId', 'productId', 'LoanId', 'PayDate', 'Remarks', 'requestDate', 'LOANPURPOSE', 'disbursementDate','Remarks', 'amount', 'PayPeriod'
        ]

        # Track processing statistics
        processed_loans = 0
        error_messages = []

        for file_path in excel_files:
            _logger.info("Processing Excel file: %s", file_path)

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

                # Process each row in the Excel file
                for index, row in df.iterrows():
                    try:
                        # Extract and validate data
                        member_id = str(int(row['memberId'])) if pd.notna(row['memberId']) else False
                        product_id = str(row['productId']).strip() if pd.notna(row['productId']) else False
                        loan_id = str(int(row['LoanId'])) if pd.notna(row['LoanId']) and row['LoanId'] != 0.0 else False
                        remarks = str(row['LOANPURPOSE']).strip() if pd.notna(row['LOANPURPOSE']) else False
                        reason = str(row['Remarks']).strip() if pd.notna(row['Remarks']) else False
                        request_date = pd.to_datetime(row['requestDate']) if pd.notna(row['requestDate']) else False
                        disbursement_date = pd.to_datetime(row['disbursementDate']) if pd.notna(row['disbursementDate']) else False
                        amount = float(row['amount']) if pd.notna(row['amount']) else 0.0
                        pay_period = int(row['PayPeriod']) if pd.notna(row['PayPeriod']) else 0.0

                        # Convert disbursement_date to Python date
                        if disbursement_date:
                            disbursement_date = disbursement_date.date()
                            
                        # Convert disbursement_date to Python date
                        if request_date:
                            request_date = request_date.date()

                        # Find or create the member
                        member = False
                        if member_id:
                            members = self.env['res.partner'].search([
                                ('member_id', '=', member_id),
                                ('is_sacco_member', '=', True),
                                ('is_allow_loan', '=', True)
                            ], limit=1)
                            if not members:
                                self.env.cr.execute("""
                                    SELECT id
                                    FROM res_partner
                                    WHERE CAST(REGEXP_REPLACE("member_id", '^0+', '') AS TEXT) = %s
                                    AND is_sacco_member = TRUE
                                    AND is_allow_loan = TRUE
                                    LIMIT 1
                                """, (member_id,))
                                member_id_result = self.env.cr.fetchone()
                                if member_id_result:
                                    member = self.env['res.partner'].browse(member_id_result[0])
                            else:
                                member = members

                            if not member:
                                _logger.info("Creating new SACCO member with ID %s for row %d in file %s", member_id, index, file_path)
                                member_vals = {
                                    'is_sacco_member': True,
                                    'is_allow_loan': True,
                                    'member_id': member_id,
                                    'first_name': 'Unknown Loan Member',
                                    'last_name': f"Member {member_id}",
                                    'name': f"Unknown Loan Member {member_id}",
                                    'email': f"member_{member_id}@example.com",
                                    'phone': '0000000000',
                                    'member_type': 'individual',
                                    'role': 'member',
                                    'membership_status': 'inactive',
                                }
                                member = self.env['res.partner'].create(member_vals)
                                _logger.info("Created new SACCO member with ID %s", member_id)

                        if not member:
                            _logger.error("No valid member found for memberId %s in row %d of file %s", member_id, index, file_path)
                            error_messages.append(
                                _("No valid member found for memberId %s in row %d of file '%s'") % (member_id, index, file_path)
                            )
                            continue

                        # Find the loan product
                        loan_type = False
                        if product_id:
                            loan_type = self.env['sacco.loan.type'].search([
                                ('product_code', '=', product_id)
                            ], limit=1)
                            if not loan_type:
                                _logger.error("No loan product found for productid %s in row %d of file %s", product_id, index, file_path)
                                error_messages.append(
                                    _("No loan product found for productid %s in row %d of file '%s'") % (product_id, index, file_path)
                                )
                                continue

                        # Check if loan already exists
                        # if loan_id:
                        #     existing_loan = self.env['sacco.loan.loan'].search([
                        #         ('name', '=', loan_id)
                        #     ], limit=1)
                        #     if existing_loan:
                        #         _logger.info("Loan %s already exists. Skipping row %d in file %s", loan_id, index, file_path)
                        #         continue

                        # Prepare loan values
                        loan_vals = {
                            'name': loan_id or self.env['ir.sequence'].next_by_code('sacco.loan.loan') or '/',
                            'client_id': member.id,
                            'request_date': request_date,
                            'disbursement_date': disbursement_date,
                            'approve_date': disbursement_date,
                            'loan_type_id': loan_type.id,
                            'loan_amount': amount,
                            'interest_rate': loan_type.rate or 0.0,
                            'loan_term': pay_period,
                            'notes': remarks or '',
                            'state': 'disburse',
                            'specify': reason or '',
                            'currency_id': loan_type.currency_id.id if loan_type else self.env.company.currency_id.id,
                            'company_id': self.env.company.id,
                            'loan_account_id': loan_type.loan_account_id.id if loan_type else False,
                            'disburse_journal_id': self.journal_id.id,
                            'paying_account_id': loan_type.default_paying_account_id.id if loan_type else False,
                        }

                        # Create the loan
                        loan = self.env['sacco.loan.loan'].create(loan_vals)
                        loan.write({'name': loan_id or loan.name})
                        _logger.info("Created loan %s for member %s in file %s", loan.name, member_id, file_path)

                        # Compute installments
                        loan.compute_installment(disbursement_date)                        


                        loan.action_refresh_journal_lines()

                        processed_loans += 1

                    except Exception as e:
                        _logger.error("Error processing row %d in file %s: %s", index, file_path, str(e))
                        error_messages.append(
                            _("Error processing row %d in file '%s': %s") % (index, file_path, str(e))
                        )
                        continue

            except Exception as e:
                _logger.error("Error processing file %s: %s", file_path, str(e))
                error_messages.append(
                    _("Error processing file '%s': %s") % (file_path, str(e))
                )
                continue

        _logger.info("Loan import process completed. Processed %d loans.", processed_loans)
        if error_messages:
            _logger.warning("Encountered errors during import:\n%s", "\n".join(error_messages))

        message = _("Loan import completed. Processed %d loans successfully.\n") % processed_loans
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