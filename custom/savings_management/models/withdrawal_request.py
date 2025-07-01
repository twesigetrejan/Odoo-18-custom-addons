from ..config import (get_config, GET_PENDING_WITHDRAWAL_REQUESTS_ENDPOINT, UPDATE_WITHDRAWAL_REQUESTS_ENDPOINT, DOWNLOAD_FILE_ENDPOINT)
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import date, datetime
import logging
import requests
import base64

_logger = logging.getLogger(__name__)

class WithdrawalRequest(models.Model):
    _name = 'sacco.withdrawal.request'
    _description = 'Withdrawal request'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'api.token.mixin']
    _order = 'name desc'
    _rec_name = 'name'
    
    name = fields.Char('ID', default='/', copy=False)
    savings_account_id = fields.Many2one('sacco.savings.account', string='Savings Account', required=True, domain=[('state', '=', 'active')], store=True)
    request_date = fields.Date('Request Date', default=fields.Date.today(), required=True)
    approve_date = fields.Date('Approve Date', copy=False)
    disbursement_date = fields.Date('Disbursement Date', copy=False)
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    withdrawal_amount = fields.Float('Amount', required=True)
    account_balance = fields.Float(related='savings_account_id.balance', string='Account Balance', readonly=True, store=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirm', 'Confirmed'),
        ('approve', 'Approved'),
        ('reconcile', 'Reconciled'),
        ('disburse', 'Disbursed'),
        ('open', 'Open'),
        ('close', 'Close'),
        ('cancel', 'Cancel'),
        ('reject', 'Reject')
    ], string='State', required=True, default='draft', tracking=True)
    reject_reason = fields.Text('Reject Reason', copy=False)
    reject_user_id = fields.Many2one('res.users', 'Reject By', copy=False)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.user.company_id.id)
    withdrawal_request_url = fields.Char('URL', compute='get_withdrawal_request_url')
    attachment_document_ids = fields.One2many('ir.attachment', 'res_id', string='Attachment Document', domain=[('res_model', '=', 'sacco.withdrawal.request')])
    attachment_number = fields.Integer(compute='_compute_attachment_number', string='Number of Attachments')
    disburse_journal_entry_id = fields.Many2one('account.move', string='Disburse Account Entry', copy=False)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, 
        default=lambda self: self.env.company.currency_id.id,
        tracking=True, related='savings_account_id.currency_id', store=True)
    member_id = fields.Many2one('res.partner', string='Member', 
        domain=[('is_sacco_member', '=', True)], required=True)
    available_product_ids = fields.Many2many('sacco.savings.product', 
        compute='_compute_available_products')
    product_type = fields.Many2one('sacco.savings.product', string='Product')
    paying_account_id = fields.Many2one('sacco.paying.account', string='Paying Account',
        help="The account that received this withdrawal")
    pay_account = fields.Many2one('account.account', string='Pay Account')
    below_minimum_balance = fields.Boolean(
        string='Below Minimum Balance',
        compute='_compute_below_minimum_balance',
        help='Indicates if the withdrawal would result in a balance below the minimum required.'
    )
    
    # MIS Fields
    mongo_db_id = fields.Char(string='Mongo DB ID', readonly=True, copy=False)
    ref_id = fields.Char(string='Reference ID', readonly=True, copy=False)
    in_sync = fields.Boolean(string='In Sync', default=True, help='Indicates if the withdrawal is synchronized with the external system')
    last_sync_date = fields.Datetime(string='Last Sync Date', readonly=True)
    comment = fields.Text('Comment', help="Additional comments or notes about the withdrawal")
    account_name = fields.Char('Account Name', help="Name of the account holder")
    account_number = fields.Char('Account Number', help="Bank account number")
    bank_name = fields.Char('Bank Name', help="Name of the bank")
    branch = fields.Char('Bank Branch', help="Bank branch")

    # Field mapping for external system
    EXTERNAL_FIELD_MAPPING = {
        'memberId': 'member_id',
        'product': 'product_type',
        'withdrawAmount': 'withdrawal_amount',
        'currency': 'currency_id',
        '_id': 'mongo_db_id',
        'refID': 'ref_id',
        'dateCreated': 'request_date',
        'comment': 'comment',
        'accountName': 'account_name',
        'accountNumber': 'account_number',
        'bankName': 'bank_name',
        'branch': 'branch',
    }

    def _compute_attachment_number(self):
        for withdrawal_request in self:
            withdrawal_request.attachment_number = len(withdrawal_request.attachment_document_ids.ids)
    
    def action_get_attachment_view(self):
        self.ensure_one()
        res = self.env['ir.actions.act_window']._for_xml_id('base.action_attachment')
        res['domain'] = [('res_model', '=', 'sacco.withdrawal.request'), ('res_id', 'in', self.ids)]
        res['context'] = {'default_res_model': 'sacco.withdrawal.request', 'default_res_id': self.id}
        return res   
    
    @api.depends('savings_account_id')
    def get_withdrawal_request_url(self):
        for withdrawal_request in self:
            withdrawal_request.withdrawal_request_url = ''
            if withdrawal_request.savings_account_id:
                base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', default='http://localhost:8069')
                if base_url:
                    withdrawal_request.withdrawal_request_url = base_url + '/web/login?db=%s&login=%s&key=%s#id=%s&model=%s' % (
                        self._cr.dbname, '', '', withdrawal_request.id, 'sacco.withdrawal.request')

    @api.constrains('withdrawal_amount')
    def check_rate(self):
        for record in self:
            if record.withdrawal_amount <= 0:
                raise ValidationError(_("Withdrawal Amount Must be Positive !!!"))
            if record.withdrawal_amount > record.savings_account_id.balance:
                raise ValidationError(_("Withdrawal amount cannot exceed the available balance."))
            # Skip minimum balance check for synced requests or if bypass_minimum_balance is True
            if not (record.mongo_db_id or record.ref_id or record.savings_account_id.bypass_minimum_balance):
                if record.savings_account_id.balance - record.withdrawal_amount < record.savings_account_id.minimum_balance:
                    raise ValidationError(
                        _("Withdrawal would result in a balance below the minimum required balance of %s for this savings account.")
                        % record.savings_account_id.minimum_balance
                    )

    @api.depends('withdrawal_amount', 'savings_account_id.balance', 'savings_account_id.minimum_balance')
    def _compute_below_minimum_balance(self):
        for record in self:
            if record.savings_account_id and record.withdrawal_amount:
                record.below_minimum_balance = (
                    record.savings_account_id.balance - record.withdrawal_amount < record.savings_account_id.minimum_balance
                )
            else:
                record.below_minimum_balance = False
                    
    @api.onchange('product_type')
    def _onchange_product_type(self):
        if self.product_type and self.product_type.default_paying_account_id:
            self.paying_account_id = self.product_type.default_paying_account_id.id
            
    @api.onchange('paying_account_id')
    def _onchange_paying_account_id(self):
        if self.paying_account_id:
            self.pay_account = self.paying_account_id.account_id
        else:
            self.pay_account = False
               
    def _get_latest_local_sync_date(self):
        """Get the latest last_sync_date from sacco.withdrawal.request records."""
        latest_withdrawal = self.env['sacco.withdrawal.request'].search([
            ('last_sync_date', '!=', False)
        ], order='last_sync_date desc', limit=1)
        return latest_withdrawal.last_sync_date if latest_withdrawal else None

    def _download_attachment(self, attachment_file, attachment_label):
        """Download an attachment from the external system and return its data."""
        if not attachment_file:
            raise ValidationError(_(f"Attachment file path missing for {attachment_label}"))

        filename = attachment_file.split('/')[-1] if '/' in attachment_file else attachment_file
        file_id = attachment_file

        config = get_config(self.env)
        api_url = f"{config['BASE_URL']}/{DOWNLOAD_FILE_ENDPOINT}/{filename}/download"
        headers = self._get_request_headers()

        if not headers:
            raise UserError(_("Authentication credentials missing for attachment download."))

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

    def _prepare_withdrawal_values(self, external_data):
        """Prepare values for withdrawal request creation using field mapping."""
        member = self.env['res.partner'].search([
            '|',
            ('member_id', '=', external_data.get('memberId')),
            ('username', '=', external_data.get('memberId'))
        ], limit=1)
        if not member:
            raise ValidationError(_(f"Member or Username with ID {external_data.get('memberId')} not found"))

        savings_product = self.env['sacco.savings.product'].search([('name', '=', external_data.get('product'))], limit=1)
        if not savings_product:
            raise ValidationError(_(f"Savings product {external_data.get('product')} not found"))

        currency = self.env['res.currency'].search([('name', '=', external_data.get('currency'))], limit=1)
        if not currency:
            raise ValidationError(_(f"Currency {external_data.get('currency')} not found"))

        savings_account = self._find_savings_account(member.id, savings_product, currency.id)
        if not savings_account:
            raise ValidationError(_(f"No active savings account found for member {member.name}"))

        withdrawal_amount = float(external_data.get('withdrawAmount', 0))
        if withdrawal_amount <= 0 or withdrawal_amount > savings_account.balance:
            raise ValidationError(_(f"Invalid withdrawal amount {withdrawal_amount} for account {savings_account.name}"))

        request_date = datetime.strptime(external_data.get('dateCreated', ''), '%Y-%m-%dT%H:%M:%S.%f').date()

        withdrawal_values = {
            'name': self.env['ir.sequence'].next_by_code('sacco.withdrawal.request') or '/',
            'savings_account_id': savings_account.id,
            'request_date': request_date,
            'withdrawal_amount': withdrawal_amount,
            'currency_id': currency.id,
            'state': 'confirm',
            'member_id': member.id,
            'product_type': savings_product.id,
            'paying_account_id': savings_product.default_paying_account_id.id if savings_product.default_paying_account_id else False,
        }

        for external_field, local_field in self.EXTERNAL_FIELD_MAPPING.items():
            if external_field in external_data and local_field not in withdrawal_values:
                value = external_data.get(external_field)
                if value is not None:
                    if external_field == 'dateCreated':
                        try:
                            value = datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%f').date()
                        except (ValueError, TypeError):
                            _logger.warning(f"Invalid dateCreated format: {value}")
                            value = None
                    # Handle nested fields (e.g., member_id.member_id)
                    if '.' in local_field:
                        field_parts = local_field.split('.')
                        model_field = field_parts[0]
                        sub_field = field_parts[1]
                        if model_field in withdrawal_values and withdrawal_values[model_field]:
                            related_record = self.env[self._fields[model_field].comodel_name].browse(withdrawal_values[model_field])
                            withdrawal_values[sub_field] = getattr(related_record, sub_field, value)
                    else:
                        withdrawal_values[local_field] = value

        return withdrawal_values

    def _create_confirmed_withdrawal(self, withdrawal_values, external_data):
        """Create a withdrawal request, move to confirmed state, attach files, and update last_sync_date."""
        with self.env.cr.savepoint():
            withdrawal = self.create(withdrawal_values)
            _logger.info(f"Created withdrawal request with ID {withdrawal.id} for refID: {external_data.get('refID', 'Unknown')}")

            # Process attachments if present
            attachments = external_data.get('attachments', {})
            _logger.info(f"Attachments data for withdrawal {withdrawal.id}: {attachments}")
            attachment_rows = attachments.get('rows', [])
            _logger.info(f"Attachment rows for withdrawal {withdrawal.id}: {len(attachment_rows)} rows found")

            if attachment_rows:
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
                            'res_model': 'sacco.withdrawal.request',
                            'res_id': withdrawal.id,
                            'description': attachment_data['description'],
                        })
                        _logger.info(f"Created attachment {attachment_data['name']} (ID: {attachment.id}) for withdrawal {withdrawal.id}")
                    else:
                        _logger.warning(f"No attachment_file found in row: {row}")

            # Check if withdrawal would result in below minimum balance
            savings_account = self.env['sacco.savings.account'].browse(withdrawal_values['savings_account_id'])
            if savings_account.balance - withdrawal.withdrawal_amount < savings_account.minimum_balance:
                _logger.info(f"Withdrawal {withdrawal.id} would result in balance below minimum, keeping in draft state")
                # Keep in draft state, no confirmation
            else:
                withdrawal.action_confirm_withdrawal_request()
                _logger.info(f"Confirmed withdrawal {withdrawal.id} as it meets minimum balance requirements")
                
            last_updated = external_data.get('lastUpdated')
            try:
                if last_updated:
                    withdrawal.last_sync_date = datetime.fromisoformat(last_updated)
                    _logger.info(f"Updated last_sync_date for withdrawal {withdrawal.id} to {last_updated}")
            except (ValueError, TypeError) as e:
                _logger.warning(f"Invalid lastUpdated format: {last_updated}, error: {str(e)}")
            return withdrawal

    def _prepare_sync_domain(self, last_updated_date=None):
        """Prepare domain for sync query."""
        domain = {
            "status": "$text_filter:equals Pending"
        }
        if last_updated_date:
            date_str = last_updated_date.strftime('%Y-%m-%dT%H:%M:%S')
            domain["lastUpdated"] = f"$date_filter:gt {date_str}"
            _logger.info(f"Fetching withdrawal requests since: {date_str}")
        return domain

    @api.model
    def sync_withdrawal_requests(self):
        """Sync withdrawal requests from external system."""
        _logger.info("Starting withdrawal request sync process")

        # Step 1: Sync out-of-sync withdrawal requests
        self._cron_sync_withdrawals()

        # Step 2: Fetch and sync new/updated withdrawal requests
        config = get_config(self.env)
        if not config.get('USERNAME') or not config.get('PASSWORD'):
            _logger.info("External system not configured, skipping withdrawal request sync.")
            return self._show_notification(
                'Warning',
                'External system not configured. Withdrawal sync skipped.',
                'warning'
            )

        token, account_id = self._get_authentication_token()
        if not token:
            _logger.error("Failed to obtain authentication token")
            return self._show_notification('Error', 'Failed to obtain authentication token', 'danger')

        api_url = f"{config['BASE_URL']}/{GET_PENDING_WITHDRAWAL_REQUESTS_ENDPOINT}"
        headers = self._get_request_headers()
        if not headers:
            return self._show_notification('Error', 'Authentication credentials missing', 'danger')

        _logger.info(f"Fetching withdrawal requests from {api_url}")

        last_sync_date = self._get_latest_local_sync_date()
        sync_domain = self._prepare_sync_domain(last_sync_date)
        _logger.info(f"Sync domain: {sync_domain}")

        try:
            response = requests.post(api_url, headers=headers, json=sync_domain)
            _logger.info(f"API response status: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            rows = data.get('rows', [])
            _logger.info(f"Received {len(rows)} withdrawal request rows")

            # Log the entire rows data for debugging            
            # import json
            # _logger.info(f"Rows data: {json.dumps(rows, indent=2, default=str)}")
        except requests.RequestException as e:
            _logger.error(f"Failed to fetch withdrawal requests: {str(e)}")
            return self._show_notification('Error', f'Failed to fetch withdrawal requests: {str(e)}', 'danger')

        if not rows:
            _logger.info("No new withdrawal requests to sync")
            return self._show_notification('Info', 'No new withdrawal requests to sync', 'info')

        success_count = 0
        error_count = 0

        for row in rows:
            ref_id = row.get('refID', 'Unknown')
            _logger.info(f"Processing withdrawal request: {ref_id}")
            try:
                if row.get('status') != 'Pending':
                    _logger.info(f"Skipping non-Pending withdrawal: {ref_id}, status: {row.get('status')}")
                    continue

                existing_request = self.search([
                    '|',
                    ('mongo_db_id', '=', row.get('_id')),
                    ('ref_id', '=', row.get('refID'))
                ], limit=1)
                if existing_request:
                    _logger.info(f"Skipping existing withdrawal: {ref_id}, ID: {existing_request.id}")
                    continue

                withdrawal_values = self._prepare_withdrawal_values(row)
                withdrawal = self._create_confirmed_withdrawal(withdrawal_values, row)
                _logger.info(f"Successfully synced withdrawal: {ref_id}")

                success_count += 1
            except Exception as e:
                error_count += 1
                _logger.error(f"Error processing withdrawal {ref_id}: {str(e)}")
                continue

        _logger.info(f"Sync complete: {success_count} withdrawals created, {error_count} errors")
        return self._show_notification(
            'Sync Complete',
            f'Successfully created {success_count} confirmed withdrawal requests. Errors encountered: {error_count}',
            'success' if error_count == 0 else 'warning'
        )

    @api.model
    def _cron_sync_withdrawals(self):
        """Sync withdrawals with in_sync=False to the external system."""
        _logger.info("Starting sync of unsynced withdrawal requests")
        withdrawals = self.search([
            ('in_sync', '=', False),
            ('state', 'in', ['approve', 'disburse', 'reject', 'cancel'])
        ])
        for withdrawal in withdrawals:
            try:
                if withdrawal.state == 'approve':
                    withdrawal.upload_withdrawal_request_status('Approved', 'approve')
                elif withdrawal.state == 'disburse':
                    withdrawal.upload_withdrawal_request_status('Disbursed', 'disburse')
                elif withdrawal.state == 'reject':
                    withdrawal.upload_withdrawal_request_status('Rejected', 'reject', withdrawal.reject_reason)
                elif withdrawal.state == 'cancel':
                    withdrawal.upload_withdrawal_request_status('Cancelled', 'cancel')
                self.env.cr.commit()
                _logger.info(f"Successfully synced withdrawal {withdrawal.name}")
            except Exception as e:
                _logger.error(f"Failed to sync withdrawal {withdrawal.name}: {str(e)}")
                self.env.cr.rollback()
        _logger.info(f"Completed sync of {len(withdrawals)} unsynced withdrawal requests")

    def upload_withdrawal_request_status(self, api_status, odoo_state, remarks=None):
        """Upload withdrawal request status to external system and update Odoo state."""
        def action_callback():
            config = get_config(self.env)
            api_url = f"{config['BASE_URL']}/{UPDATE_WITHDRAWAL_REQUESTS_ENDPOINT}/{self.mongo_db_id}"
            headers = self._get_request_headers()
            if not headers:
                raise UserError(_("Authentication credentials missing"))

            data = {
                'status': api_status,
            }
            if remarks:
                data['remarks'] = remarks

            _logger.info(f"Uploading data to {api_url}: {data}")
            response = requests.put(api_url, headers=headers, json=data)
            response.raise_for_status()
            return self._show_notification(
                'Upload Complete',
                f'Successfully updated the withdrawal status to {api_status}',
                'success'
            )

        def local_update_callback():
            self.state = odoo_state

        return self._handle_external_action(
            action_callback=action_callback,
            local_update_callback=local_update_callback,
            success_message=f'Successfully updated the withdrawal status to {api_status}',
            local_message=f'Withdrawal status updated locally to {odoo_state}. Will sync with external system later.'
        )

    def action_confirm_withdrawal_request(self):
        self.ensure_one()
        if self.name == '/':
            self.name = self.env['ir.sequence'].next_by_code('sacco.withdrawal.request') or '/'
        self.state = 'confirm'
        ir_model_data = self.env['ir.model.data']
        template_id = ir_model_data._xmlid_lookup('savings_management.withdrawal_request_email')[1]
        mtp = self.env['mail.template']
        template_id = mtp.browse(template_id)
        email = self.get_savings_manager_mail()
        template_id.write({'email_to': email})
        template_id.send_mail(self.ids[0], force_send=True)

        savings_manager_group = self.env.ref('savings_management.group_savings_manager')
        savings_managers = savings_manager_group.users

        message = _(f"A new withdrawal request {self.name} has been confirmed for {self.savings_account_id.member_id.name}. Please review and take necessary action.")

        self.message_post(
            body=message,
            message_type='notification',
            subtype_xmlid='mail.mt_note',
            partner_ids=savings_managers.mapped('partner_id').ids
        )

        self.activity_schedule(
            'mail.mail_activity_data_todo',
            note=message,
            user_id=savings_managers[0].id if savings_managers else self.env.user.id,
            summary=_("Review Withdrawal Request")
        )

    def get_savings_manager_mail(self):
        group_id = self.env.ref('savings_management.group_savings_manager').id
        group_id = self.env['res.groups'].browse(group_id)
        email = ''
        if group_id:
            for user in group_id.users:
                if user.partner_id and user.partner_id.email:
                    email = email + ',' + user.partner_id.email if email else user.partner_id.email
        return email

    def get_savings_accountant_mail(self):
        group_id = self.env.ref('savings_management.group_savings_accountant').id
        group_id = self.env['res.groups'].browse(group_id)
        email = ''
        if group_id:
            for user in group_id.users:
                if user.partner_id and user.partner_id.email:
                    email = email + ',' + user.partner_id.email if email else user.partner_id.email
        return email

    def action_approve_withdrawal_request(self):
        self.state = 'approve'
        self.approve_date = date.today()
        self.upload_withdrawal_request_status('Approved', 'approve')

        ir_model_data = self.env['ir.model.data']
        template_id = ir_model_data._xmlid_lookup('savings_management.withdrawal_request_accountant_email')[1]
        mtp = self.env['mail.template']
        template_id = mtp.browse(template_id)

        accountant_email = self.get_savings_accountant_mail()
        if accountant_email:
            template_id.write({'email_to': accountant_email})
            template_id.send_mail(self.ids[0], force_send=True)

            accountant_group = self.env.ref('savings_management.group_savings_accountant')
            accountants = accountant_group.users

            message = _(f"Withdrawal request {self.name} has been approved and requires processing.")

            if accountants:
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    note=message,
                    user_id=accountants[0].id,
                    summary=_("Process Approved Withdrawal")
                )

    def action_set_to_draft(self):
        self.state = 'draft'

    def get_account_move_vals(self):
        if not self.savings_account_id.product_id.disburse_journal_id:
            raise ValidationError(_("Select Disburse Journal !!!"))
        vals = {
            'date': self.disbursement_date,
            'ref': self.name or 'Withdrawal Request',
            'journal_id': self.savings_account_id.product_id.disburse_journal_id.id,
            'company_id': self.company_id.id,
        }
        return vals

    def get_debit_lines(self):
        if not self.savings_account_id.product_id.savings_product_account_id:
            raise ValidationError(_("Select Disburse Account !!!"))

        withdrawal_account = self.savings_account_id.product_id.withdrawal_account_id
        if not withdrawal_account:
            raise ValidationError(_("Please configure withdrawal account in the savings product!"))

        vals = {
            'partner_id': self.savings_account_id.member_id.id,
            'account_id': withdrawal_account.id,
            'debit': self.withdrawal_amount,
            'name': f"Withdrawal - {self.name}" or '/',
            'date_maturity': self.disbursement_date,
            'member_id': self.savings_account_id.member_id.member_id if self.savings_account_id.member_id.member_id else False,
        }
        return vals

    def get_credit_lines(self):
        if not self.paying_account_id:
            if self.savings_account_id.product_id.default_paying_account_id:
                self.paying_account_id = self.savings_account_id.product_id.default_paying_account_id.id
            else:
                raise ValidationError(_("No paying account specified and no default paying account configured in the savings product!"))

        account_id = self.pay_account or self.paying_account_id.account_id
        if not account_id:
            raise ValidationError(_("The paying account does not have a valid accounting account configured!"))

        if self.savings_account_id.member_id and not self.savings_account_id.member_id.property_account_receivable_id:
            raise ValidationError(_("Select Client Receivable Account !!!"))

        vals = {
            'partner_id': self.savings_account_id.member_id.id,
            'account_id': account_id.id,
            'credit': self.withdrawal_amount,
            'name': 'withdraw' or '/',
            'date_maturity': self.disbursement_date,
        }
        return vals

    def action_create_entry(self):
        self.disbursement_date = date.today()
        if not self.disbursement_date:
            raise ValidationError(_("Disbursement date is required!"))

        if not self.paying_account_id:
            if self.savings_account_id.product_id.default_paying_account_id:
                self.paying_account_id = self.savings_account_id.product_id.default_paying_account_id.id
            else:
                raise ValidationError(_("No paying account specified and no default paying account configured in the savings product!"))

        account_move_val = self.get_account_move_vals()
        account_move_id = self.env['account.move'].create(account_move_val)
        vals = []
        if account_move_id:
            val = self.get_debit_lines()
            vals.append((0, 0, val))
            val = self.get_credit_lines()
            vals.append((0, 0, val))
            account_move_id.line_ids = vals
            self.disburse_journal_entry_id = account_move_id.id

            if account_move_id.state == 'draft':
                account_move_id.action_post()
                self.savings_account_id.action_refresh_journal_lines()

    def action_disburse_withdrawal(self):
        self.ensure_one()
        self.action_create_entry()
        if self.disburse_journal_entry_id and self.disburse_journal_entry_id.state == 'posted':
            self.upload_withdrawal_request_status('Disbursed', 'disburse')
            self.state = 'disburse'
        else:
            raise UserError(_("Please Post the draft Entry for this Transaction !!!"))

    def unlink(self):
        for withdrawal_request in self:
            if withdrawal_request.state not in ['draft', 'cancel']:
                raise ValidationError(_('Withdrawal Request delete on Draft and cancel state only !!!.'))
            if withdrawal_request.disburse_journal_entry_id:
                raise ValidationError(_('Cannot delete request with associated journal entries. Please set the entry to draft then delete it'))
        return super(WithdrawalRequest, self).unlink()

    def _find_savings_account(self, member_id, savings_product, currency_id):
        return self.env['sacco.savings.account'].search([
            ('member_id', '=', member_id),
            ('product_id', '=', savings_product.id),
            ('currency_id', '=', currency_id),
            ('state', '=', 'active')
        ], limit=1)

    @api.depends('member_id')
    def _compute_available_products(self):
        for record in self:
            if record.member_id:
                savings_accounts = self.env['sacco.savings.account'].search([
                    ('member_id', '=', record.member_id.id),
                    ('state', '=', 'active')
                ])
                record.available_product_ids = savings_accounts.mapped('product_id')
            else:
                record.available_product_ids = False

    @api.onchange('member_id', 'product_type')
    def _onchange_selection(self):
        self.savings_account_id = False
        if self.member_id and self.product_type:
            savings_account = self.env['sacco.savings.account'].search([
                ('member_id', '=', self.member_id.id),
                ('product_id', '=', self.product_type.id),
                ('state', '=', 'active')
            ], limit=1)
            if savings_account:
                self.savings_account_id = savings_account.id

    @api.onchange('member_id')
    def _onchange_member_id(self):
        self.product_type = False
        self.savings_account_id = False