from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import requests
from datetime import datetime
import logging
import base64
from ..config import (get_config, GET_APPROVED_LOAN_APPLICATIONS_ENDPOINT, UPDATE_LOAN_APPLICATION_COLLECTION_ENDPOINT, CREATE_NOTIFICATIONS_COLLECTION_ENDPOINT, CREATE_UPDATE_LOANS_STATEMENT_COLLECTION_ENDPOINT, DOWNLOAD_FILE_ENDPOINT)

_logger = logging.getLogger(__name__)

class SaccoLoanApplication(models.TransientModel):
    _name = 'sacco.loan.application'
    _description = 'SACCO Loan Application Sync'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'api.token.mixin']

    # Minimal fields needed for sync process
    member_id = fields.Many2one('res.partner', string='Member')
    loan_product_id = fields.Many2one('sacco.loan.type', string='Loan Product')
    amount_requested = fields.Float(string='Amount Requested')
    loan_period = fields.Integer(string='Loan Period (months)')
    loan_ref_id = fields.Char('Reference ID', readonly=True)
    loan_mongo_db_id = fields.Char('MongoDB ID', readonly=True)
    last_sync_date = fields.Datetime(string='Last Sync Date', readonly=True)

    # Field mapping from external system to local Odoo fields
    EXTERNAL_FIELD_MAPPING = {
        'memberId': 'client_id',
        'loanProduct': 'loan_type_id',
        'amountRequested': 'loan_amount',
        'loanPeriod': 'loan_term',
        '_id': 'loan_mongo_db_id',
        'refID': 'loan_ref_id',
        'lastUpdated': 'last_sync_date',
        'specify': 'specify',
        'accountName': 'account_name',
        'accountNumber': 'account_number',
        'bankName': 'bank_name',
        'branch': 'branch',
    }

    def _get_currency(self, currency_code='UGX'):
        """Get currency record from currency code, default to UGX"""
        currency = self.env['res.currency'].search([('name', '=', currency_code)], limit=1)
        if not currency:
            raise ValidationError(_(f"Currency {currency_code} not found in the system"))
        return currency

    def _get_latest_local_sync_date(self):
        """Get the latest last_sync_date from sacco.loan.loan records."""
        latest_loan = self.env['sacco.loan.loan'].search([
            ('last_sync_date', '!=', False)
        ], order='last_sync_date desc', limit=1)
        return latest_loan.last_sync_date if latest_loan else None

    def _download_attachment(self, attachment_file, attachment_label):
        """Download an attachment from the external system and return its data."""
        if not attachment_file:
            raise ValidationError(_(f"Attachment file path missing for {attachment_label}"))

        # Extract filename (e.g., 'IMG_0023.png' from 'SACCO-00002/IMG_0023.png')
        filename = attachment_file.split('/')[-1] if '/' in attachment_file else attachment_file
        file_id = attachment_file  # Use full path as fileID for the endpoint

        config = get_config(self.env)
        api_url = f"{config['BASE_URL']}/{DOWNLOAD_FILE_ENDPOINT}/{filename}/download"
        headers = self._get_request_headers()

        _logger.info(f"Attempting to download attachment: {filename} (file_id: {file_id}) from {api_url}")

        try:
            response = requests.get(api_url, headers=headers, stream=True)
            _logger.info(f"Download response status: {response.status_code} for {filename}")
            response.raise_for_status()
            content = response.content
            if not content:
                _logger.error(f"Empty file received for {filename}")
                raise ValidationError(_(f"Empty file received for {filename}"))
            _logger.info(f"Downloaded {len(content)} bytes for {filename}")
            # Encode content as base64 for Odoo attachment
            encoded_content = base64.b64encode(content).decode('utf-8')
            return {
                'name': filename,
                'datas': encoded_content,
                'type': 'binary',
                'description': attachment_label,
            }
        except requests.RequestException as e:
            _logger.error(f"Failed to download attachment {filename}: {str(e)}")
            raise ValidationError(_(f"Failed to download attachment {filename}: {str(e)}"))

    def _prepare_loan_values(self, external_data):
        """Prepare values for direct loan creation using field mapping."""
        member = self.env['res.partner'].search([
            '|',
            ('member_id', '=', external_data.get('memberId')),
            ('username', '=', external_data.get('memberId'))
        ], limit=1)
        if not member:
            raise ValidationError(_(f"Member with ID or Username {external_data.get('memberId')} not found"))

        loan_type = self.env['sacco.loan.type'].search([('name', '=', external_data.get('loanProduct'))], limit=1)
        if not loan_type:
            raise ValidationError(_(f"Loan product {external_data.get('loanProduct')} not found"))

        currency = self._get_currency()

        # Initialize loan values
        loan_values = {
            'client_id': member.id,
            'loan_type_id': loan_type.id,
            'loan_amount': float(external_data.get('amountRequested', 0.0)),
            'loan_term': int(external_data.get('loanPeriod', 0)),
            'interest_rate': loan_type.rate or 0.0,
            'currency_id': currency.id,
            'request_date': fields.Date.today(),
            'user_id': self.env.user.id,
            'state': 'draft',
        }

        # Map additional fields from external data
        for external_field, local_field in self.EXTERNAL_FIELD_MAPPING.items():
            if external_field in external_data and local_field not in loan_values:
                value = external_data.get(external_field)
                if value is not None:
                    if external_field == 'lastUpdated':
                        try:
                            value = datetime.fromisoformat(value)
                        except (ValueError, TypeError):
                            _logger.warning(f"Invalid lastUpdated format: {value}")
                            value = None
                    loan_values[local_field] = value

        # Prepare guarantor values if guarantor_member_id is available
        guarantor_member_id = external_data.get('guarantor_member_id') or external_data.get('guarantorMemberId')
        if guarantor_member_id:
            guarantor_member = self.env['res.partner'].search([
            '|',
            ('member_id', '=', guarantor_member_id),
            ('username', '=', guarantor_member_id)
            ], limit=1)
            if guarantor_member:
                pledge_type = external_data.get('pledge_type') or external_data.get('pledgeType')
                pledge_amount = external_data.get('pledge_amount') or external_data.get('pledgeAmount', 0.0)
                loan_values['guarantor_ids'] = [(0, 0, {
                    'guarantor_member_id': guarantor_member.id,
                    'pledge_type': pledge_type,
                    'pledge_amount': float(pledge_amount) if pledge_amount else 0.0,
                })]

        return loan_values

    def _create_draft_loan(self, loan_values, external_data):
        """Create a loan, move to confirmed state, attach files, create security if applicable, and update last_sync_date."""
        with self.env.cr.savepoint():
            loan = self.env['sacco.loan.loan'].create(loan_values)
            _logger.info(f"Created loan with ID {loan.id} for refID: {external_data.get('refID', 'Unknown')}")

            # Process attachments if present
            attachments = external_data.get('attachments', {})
            _logger.info("Attachments data for loan received")
            attachment_rows = attachments.get('rows', [])
            _logger.info(f"Attachment rows for loan {loan.id}: {len(attachment_rows)} rows found")

            security_attachments = []
            loan_attachments = []

            if attachment_rows:  # Check if rows list is non-empty
                for row in attachment_rows:
                    attachment_file = row.get('attachment_file')
                    attachment_label = row.get('select_attachment', 'Attachment')
                    _logger.info(f"Processing attachment: file={attachment_file}, label={attachment_label}")
                    if attachment_file:
                        attachment_data = self._download_attachment(attachment_file, attachment_label)
                        attachment = self.env['ir.attachment'].create({
                            'name': attachment_data['name'],
                            'datas': attachment_data['datas'],
                            'type': attachment_data['type'],
                            'res_model': 'sacco.loan.loan',  # Temporary model, will update for security if needed
                            'res_id': loan.id,
                            'description': attachment_data['description'],
                        })
                        _logger.info(f"Created attachment {attachment_data['name']} (ID: {attachment.id}) for loan {loan.id}")
                        # Categorize attachment based on select_attachment
                        if attachment_label in ["Collateral Title Document", "Collateral / Security Valuation Report"]:
                            security_attachments.append(attachment.id)
                        else:
                            loan_attachments.append(attachment.id)
                    else:
                        _logger.warning(f"No attachment_file found in row: {row}")

            # Create security if collateral is present
            collateral = external_data.get('collateral') or external_data.get('Collateral')
            security_type = external_data.get('security_type') or external_data.get('securityType')
            
            if collateral == 'Yes' and security_type:
                _logger.info(f"Attempting to create security for loan {loan.id} with collateral: {collateral} and security_type: {security_type}")
                try:
                    with self.env.cr.savepoint():
                        # Handle both camelCase and snake_case field names
                        first_name = external_data.get('name') or external_data.get('Name', '')
                        other_name = external_data.get('otherName') or external_data.get('other_name', '')
                        owner_name = f"{first_name} {other_name}".strip()
                        
                        asset_description = external_data.get('asset_description') or external_data.get('assetDescription', 'No description provided')
                        registered_asset_no = external_data.get('registered_asset_no') or external_data.get('registeredAssetNo', 'N/A')
                        branch = external_data.get('branch') or external_data.get('Branch', 'Unknown')
                        market_value = float(external_data.get('market_value') or external_data.get('marketValue', 0.0))
                        valuation_date = external_data.get('valuation_date') or external_data.get('valuationDate', fields.Date.today())
                        
                        security_vals = {
                            'loan_id': loan.id,
                            'security_type': security_type.lower(),  # Ensure lowercase for consistency
                            'description': asset_description,
                            'owner_name': owner_name or first_name or 'Unknown',
                            'registered_asset_no': registered_asset_no,
                            'location': branch,
                            'market_value': market_value,
                            'valuation_date': valuation_date,
                            'security_status': 'pending_verification',
                        }
                        if security_attachments:
                            security_vals['ownership_proof_ref'] = [(6, 0, security_attachments)]
                        _logger.debug(f"Security values: {security_vals}")
                        security = self.env['sacco.loan.security'].create(security_vals)
                        _logger.info(f"Created security {security.name} (ID: {security.id}) for loan {loan.id}")
                        # Update attachment res_model and res_id for security attachments
                        if security_attachments:
                            self.env['ir.attachment'].browse(security_attachments).write({
                                'res_model': 'sacco.loan.security',
                                'res_id': security.id,
                            })
                except Exception as e:
                    _logger.error(f"Failed to create security for loan {loan.id}: {str(e)}")
                    # Continue with loan creation despite security failure

            # Link loan attachments
            if loan_attachments:
                loan.loan_document_ids = [(6, 0, loan_attachments)]
                _logger.info(f"Linked {len(loan_attachments)} attachments to loan {loan.id}")

            # Update last_sync_date only after successful creation
            last_updated = external_data.get('lastUpdated')
            try:
                if last_updated:
                    loan.last_sync_date = datetime.fromisoformat(last_updated)
                    _logger.info(f"Updated last_sync_date for loan {loan.id} to {last_updated}")
            except (ValueError, TypeError) as e:
                _logger.warning(f"Invalid lastUpdated format: {last_updated}, error: {str(e)}")
            return

    def _prepare_sync_policy(self, last_updated_date=None):
        """Prepare domain for sync query."""
        domain = {
            "status": "$text_filter:equals Pending"
        }
        if last_updated_date:
            date_str = last_updated_date.strftime('%Y-%m-%dT%H:%M:%S')
            domain["lastUpdated"] = f"$date_filter:gt {date_str}"
            _logger.info(f"Fetching loans since: {date_str}")
        return domain

    @api.model
    def _cron_sync_loans(self):
        """Sync loans with in_sync=False to the external system."""
        _logger.info("Starting sync of unsynced loans")
        loans = self.env['sacco.loan.loan'].search([
            ('in_sync', '=', False),
            ('state', 'in', ['approve', 'disburse', 'open', 'reject', 'cancel'])
        ])
        for loan in loans:
            try:
                if loan.state == 'approve':
                    loan.upload_loan_status('Approved', 'approve')
                elif loan.state == 'disburse':
                    loan.upload_loan_status('Disbursed', 'disburse')
                elif loan.state == 'open':
                    loan.upload_loan_status('Disbursed', 'open')
                    if loan.update_statement:
                        loan.post_or_update_statement()
                elif loan.state == 'reject':
                    loan.upload_loan_status('Rejected', 'reject', loan.reject_reason)
                elif loan.state == 'cancel':
                    loan.upload_loan_status('Cancelled', 'cancel')
                self.env.cr.commit()
                _logger.info(f"Successfully synced loan {loan.name}")
            except Exception as e:
                _logger.error(f"Failed to sync loan {loan.name}: {str(e)}")
                self.env.cr.rollback()
        _logger.info(f"Completed sync of {len(loans)} unsynced loans")

    @api.model
    def action_sync_loan_applications(self):
        """Sync approved loan applications from external system and create confirmed loans."""
        _logger.info("Starting loan application sync process")
        # Step 1: Sync out-of-sync loans first
        self._cron_sync_loans()

        # Step 2: Fetch and sync new/updated loan applications
        config = get_config(self.env)
        if not config.get('USERNAME') or not config.get('PASSWORD'):
            _logger.info("External system not configured, skipping loan application sync.")
            return self._show_notification(
                'Warning',
                'External system not configured. Loan sync skipped.',
                'warning'
            )

        token, account_id = self._get_authentication_token()
        if not token:
            _logger.error("Failed to obtain authentication token")
            return self._show_notification('Error', 'Failed to obtain authentication token', 'danger')

        api_url = f"{config['BASE_URL']}/{GET_APPROVED_LOAN_APPLICATIONS_ENDPOINT}"
        headers = self._get_request_headers()
        _logger.info(f"Fetching loan applications from {api_url}")

        # Determine sync strategy
        last_sync_date = self._get_latest_local_sync_date()
        sync_domain = self._prepare_sync_policy(last_sync_date)
        _logger.info(f"Sync domain: {sync_domain}")

        try:
            response = requests.post(api_url, headers=headers, json=sync_domain)
            _logger.info(f"API response status: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            rows = data.get('rows', [])
            _logger.info(f"Received {len(rows)} loan application rows")
            
            # # Log the entire rows data for debugging
            # import json
            # _logger.info(f"Rows data: {json.dumps(rows, indent=2, default=str)}")
        except requests.RequestException as e:
            _logger.error(f"Failed to fetch data from API: {str(e)}")
            return self._show_notification('Error', f'Failed to fetch data from API: {str(e)}', 'danger')

        if not data.get('rows'):
            _logger.info("No new loan applications to sync")
            return self._show_notification('Info', 'No new loan applications to sync', 'info')

        success_count = 0
        error_count = 0

        for row in data.get('rows', []):
            ref_id = row.get('refID', 'Unknown')
            _logger.info(f"Processing loan application: {ref_id}")
            try:
                # Skip if not Pending
                if row.get('status') != 'Pending':
                    _logger.info(f"Skipping non-Pending loan: {ref_id}, status: {row.get('status')}")
                    continue

                # Check if loan already exists using loan_mongo_db_id or loan_ref_id
                existing_loan = self.env['sacco.loan.loan'].search([
                    '|',
                    ('loan_mongo_db_id', '=', row.get('_id')),
                    ('loan_ref_id', '=', row.get('refID'))
                ], limit=1)
                if existing_loan:
                    _logger.info(f"Skipping existing loan: {ref_id}, loan ID: {existing_loan.id}")
                    continue

                # Prepare and create loan with attachments
                loan_values = self._prepare_loan_values(row)
                self._create_draft_loan(loan_values, row)
                _logger.info(f"Successfully synced loan: {ref_id}")

                success_count += 1
            except Exception as e:
                error_count += 1
                _logger.error(f"Error processing loan {ref_id}: {str(e)}")
                continue

        _logger.info(f"Sync complete: {success_count} loans created, {error_count} errors")
        return self._show_notification(
            'Sync Complete',
            f'Successfully created {success_count} confirmed loans. Errors encountered: {error_count}',
            'success' if error_count == 0 else 'warning'
        )