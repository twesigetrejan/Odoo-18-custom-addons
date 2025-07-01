from ..config import (BASE_URL, get_config, GET_WITHDRAWAL_REQUESTS_ENDPOINT)
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import date
import logging
import requests
from datetime import datetime

_logger = logging.getLogger(__name__)

class InvestmentWithdrawalRequest(models.Model):
    _name  = 'sacco.investments.withdrawal.request'
    _description = 'Withdrawal request'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'api.token.mixin']
    _order = 'name desc'
    _rec_name = 'name'
    
    name = fields.Char('ID', default='/', copy=False)
    investments_account_id = fields.Many2one('sacco.investments.account', string='Investments Account', domain=[('state', '=', 'active')], required=True, store=True)
    request_date = fields.Date('Request Date', default=fields.Date.today(), required=True)
    approve_date = fields.Date('Approve Date', copy=False)
    disbursement_date = fields.Date('Disbursement Date', copy=False)
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    withdrawal_amount = fields.Float('Amount', required=True)
    account_balance=fields.Float(related='investments_account_id.cash_balance', string='Account Balance', readonly=True, store=False)
    state = fields.Selection([('draft','Draft'),
                              ('confirm','Confirm'),
                              ('approve','Approve'),
                              ('reconcile','Reconcile'),
                              ('disburse','Disburse'),
                              ('open','Open'),
                              ('close','Close'),
                              ('cancel','Cancel'),
                              ('reject','Reject')], string='State', required=True, default='draft')
    reject_reason = fields.Text('Reject Reason', copy=False)
    reject_user_id = fields.Many2one('res.users','Reject By', copy=False)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self:self.env.user.company_id.id)
    withdrawal_request_url = fields.Char('URL', compute='get_withdrawal_request_url')
    attachment_document_ids = fields.One2many('ir.attachment','res_id', string='Attachment Document')
    attachment_number = fields.Integer(compute='_compute_attachment_number', string='Number of Attachments')    
    disburse_journal_entry_id = fields.Many2one('account.move', string='Disburse Account Entry', copy=False)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, 
        default=lambda self: self.env.company.currency_id.id,
        tracking=True, related='investments_account_id.currency_id')
    member_id = fields.Many2one('res.partner', string='Member', 
        domain=[('is_sacco_member', '=', True)], required=True)
    available_product_ids = fields.Many2many('sacco.investments.product', 
        compute='_compute_available_products')
    product_type = fields.Many2one('sacco.investments.product', string='Product')
    paying_account_id = fields.Many2one('sacco.paying.account', string='Paying Account',
        help="The account that received this withdrawal")
    pay_account = fields.Many2one('account.account', string='Pay Account')
    below_minimum_balance = fields.Boolean(
        string='Below Minimum Balance',
        compute='_compute_below_minimum_balance',
        help='Indicates if the withdrawal would result in a balance below the minimum required.'
    )


    # MIS FIELDS
    mongo_db_id = fields.Char(string='Mongo DB ID', readonly=True)
    ref_id = fields.Char(string='Reference ID', readonly=True)

    def _compute_attachment_number(self):
        for withdrawal_request in self:
            withdrawal_request.attachment_number = len(withdrawal_request.attachment_document_ids.ids)
    
    def action_get_attachment_view(self):
        self.ensure_one()
        res = self.env['ir.actions.act_window']._for_xml_id('base.action_attachment')
        res['domain'] = [('res_model', '=', 'sacco.investments.withdrawal.request'), ('res_id', 'in', self.ids)]
        res['context'] = {'default_res_model': 'sacco.investments.withdrawal.request', 'default_res_id': self.id}
        return res   
    
    @api.depends('investments_account_id')
    def get_withdrawal_request_url(self):
        for withdrawl_request in self:
            withdrawl_request.withdrawal_request_url =  ''
            if withdrawl_request.investments_account_id:
                base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', default='http://localhost:8069')
                if base_url:
                    base_url += '/web/login?db=%s&login=%s&key=%s#id=%s&model=%s' % (
                    self._cr.dbname, '', '', withdrawl_request.id, 'sacco.investments.withdrawal.request')
                    withdrawl_request.withdrawal_request_url = base_url
                    
                    
    @api.constrains('withdrawal_amount')        
    def check_rate(self):
        for record in self:
            if record.withdrawal_amount <= 0:
                raise ValidationError(_("Withdrawal Amount Must be Positive !!!"))
            if record.withdrawal_amount > record.investments_account_id.cash_balance:
                raise ValidationError(_("Withdrawal amount cannot exceed the available cash balance."))
            # Skip minimum balance check for synced requests or if bypass_minimum_balance is True
            if not (record.mongo_db_id or record.ref_id or record.investments_account_id.bypass_minimum_balance):
                if record.investments_account_id.cash_balance - record.withdrawal_amount < record.investments_account_id.minimum_balance:
                    raise ValidationError(
                        _("Withdrawal would result in a cash balance below the minimum required balance of %s for this investments account.")
                        % record.investments_account_id.minimum_balance
                    )

    @api.depends('withdrawal_amount', 'investments_account_id.cash_balance', 'investments_account_id.minimum_balance')
    def _compute_below_minimum_balance(self):
        for record in self:
            if record.investments_account_id and record.withdrawal_amount:
                record.below_minimum_balance = (
                    record.investments_account_id.cash_balance - record.withdrawal_amount < record.investments_account_id.minimum_balance
                )
            else:
                record.below_minimum_balance = False
                    
    @api.onchange('product_type')
    def _onchange_product_type(self):
        if self.product_type and self.product_type.default_paying_account_id:
            self.paying_account_id = self.product_type.default_paying_account_id.id
            
    @api.onchange('paying_account_id')
    def _onchange_paying_account_id(self):
        """Update pay_account when paying_account_id changes"""
        if self.paying_account_id:
            self.pay_account = self.paying_account_id.account_id
        else:
            self.pay_account = False
              
    def action_confirm_withdrawal_request(self):
        self.ensure_one()
        if self.name == '/':
            self.name = self.env['ir.sequence'].next_by_code('sacco.investments.withdrawal.request') or '/'
        self.state = 'confirm'
        ir_model_data = self.env['ir.model.data']
        template_id = ir_model_data._xmlid_lookup('investments_management.withdrawal_request_email')[1]
        mtp = self.env['mail.template']
        template_id = mtp.browse(template_id)
        email = self.get_investments_manager_mail()
        template_id.write({'email_to': email})
        template_id.send_mail(self.ids[0], True)
        
        # Send in-app notification
        investments_manager_group = self.env.ref('investments_management.group_investments_manager')
        investments_managers = investments_manager_group.users

        message = _(f"A new withdrawal request {self.name} has been confirmed for {self.investments_account_id.member_id.name}. Please review and take necessary action.")

        self.message_post(
            body=message,
            message_type='notification',
            subtype_xmlid='mail.mt_note',
            partner_ids=investments_managers.mapped('partner_id').ids
        )

        # Create an activity for the investments managers
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            note=message,
            user_id=investments_managers[0].id if investments_managers else self.env.user.id,
            summary=_("Review Withdrawal Request")
        )
        
    def get_investments_manager_mail(self):
        group_id = self.env.ref('investments_management.group_investments_manager').id
        group_id = self.env['res.groups'].browse(group_id)
        email=''
        if group_id:
            for user in group_id.users:
                if user.partner_id and user.partner_id.email:
                    if email:
                        email = email+','+ user.partner_id.email
                    else:
                        email= user.partner_id.email
        return email
    
    def get_investments_accountant_mail(self):
        group_id = self.env.ref('investments_management.group_investments_accountant').id
        group_id = self.env['res.groups'].browse(group_id)
        email=''
        if group_id:
            for user in group_id.users:
                if user.partner_id and user.partner_id.email:
                    if email:
                        email = email+','+ user.partner_id.email
                    else:
                        email= user.partner_id.email
        return email
        
    def action_approve_withdrawal_request(self):
        self.state = 'approve'
        self.approve_date = date.today()
        
        # Send in-app notification
        investments_accountant_group = self.env.ref('investments_management.group_investments_accountant')
        investments_accountants = investments_accountant_group.users

        message = _(f"A new withdrawal request {self.name} has been confirmed for {self.investments_account_id.member_id.name}. Please review and take necessary action.")

        self.message_post(
            body=message,
            message_type='notification',
            subtype_xmlid='mail.mt_note',
            partner_ids=investments_accountants.mapped('partner_id').ids
        )

        # Create an activity for the investments managers
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            note=message,
            user_id=investments_accountants[0].id if investments_accountants else self.env.user.id,
            summary=_("Review Withdrawal Request")
        )    
        
        # Send email to accountant
        ir_model_data = self.env['ir.model.data']
        template_id = ir_model_data._xmlid_lookup('investments_management.withdrawal_request_accountant_email')[1]
        mtp = self.env['mail.template']
        template_id = mtp.browse(template_id)    
        
        # Get accountant email
        accountant_email = self.get_investments_accountant_mail()
        if accountant_email:
            template_id.write({'email_to': accountant_email})
            template_id.send_mail(self.ids[0], True)
            
            # Create activity for accountant group
            accountant_group = self.env.ref('investments_management.group_investments_accountant')
            accountants = accountant_group.users
            
            message = _(f"Withdrawal request {self.name} has been approved and requires processing.")
            
            # Schedule activity for the first accountant
            if accountants:
                self.activity_schedule(
                    'mail.mail_activity_data_todo',
                    note=message,
                    user_id=accountants[0].id,
                    summary=_("Process Approved Withdrawal")
                )       
        
    # def action_approve_withdrawal_request(self):
    #     self.ensure_one()
    #     if self.name == '/':
    #         self.name = self.env['ir.sequence'].next_by_code('sacco.investments.withdrawal.request') or '/'
    #     self.state = 'confirm'
    #     ir_model_data = self.env['ir.model.data']
    #     template_id = ir_model_data._xmlid_lookup('investments_management.withdrawal_request_approve_email')[1]
    #     mtp = self.env['mail.template']
    #     template_id = mtp.browse(template_id)
    #     email = self.get_investments_manager_mail()
    #     template_id.write({'email_to': email})
    #     template_id.send_mail(self.ids[0], True)
        
    def action_set_to_draft(self):
        self.state = 'draft'
    
    def get_account_move_vals(self):
        if not self.investments_account_id.product_id.investments_product_cash_journal_id:
            raise ValidationError(_("Select Disburse Cash Journal !!!"))
        vals={
            'date':self.disbursement_date,
            'ref':self.name or 'Withdrawal Request',
            'journal_id':self.investments_account_id.product_id.investments_product_cash_journal_id and self.investments_account_id.product_id.investments_product_cash_journal_id.id or False,
            'company_id':self.company_id and self.company_id.id or False,
        }
        return vals
    
    def get_credit_lines(self):
        if not self.pay_account:
            raise ValidationError(_("Select Cash Pay Account !!!"))
        account_id = self.pay_account

        # Check if account requires member linking
        requires_member = account_id.requires_member
        account_product_type = account_id.account_product_type
        
        vals={
            'partner_id':self.investments_account_id.member_id and self.investments_account_id.member_id.id or False,
            'account_id': account_id and account_id.id or False,
            'credit':self.withdrawal_amount,
            'name':self.name or '/',
            'date_maturity':self.disbursement_date,
        }
        # If account requires member investments account, add it to the line
        if requires_member and account_product_type == 'investments':
            vals['investments_account_id'] = self.investments_account_id.id
        elif requires_member and account_product_type == 'investments':
            # Look for an investment account if required
            investment_accounts = self.env['sacco.investments.account'].search([
                ('member_id', '=', self.investments_account_id.member_id.id),
                ('state', '=', 'active'),
            ], limit=1)
            if investment_accounts:
                vals['investments_account_id'] = investment_accounts[0].id
            else:
                raise ValidationError(_("This account requires an investment account but none was found for this member."))
            
        return vals

    def get_debit_lines(self):
        if not self.investments_account_id.product_id.investments_product_account_id:
            raise ValidationError(_("Select Disburse Cash Account !!!"))        
        
        withdrawal_account = self.investments_account_id.product_id.investments_product_cash_account_id
        if not withdrawal_account:
            raise ValidationError(_("Please configure withdrawal cash account in the investments product!"))

        # Check if account requires member linking
        requires_member = withdrawal_account.requires_member
        account_product_type = withdrawal_account.account_product_type
        
        vals={
            'partner_id':self.investments_account_id.member_id and self.investments_account_id.member_id.id or False,
            'account_id':self.investments_account_id.product_id.investments_product_cash_account_id and self.investments_account_id.product_id.investments_product_cash_account_id.id or False,
            'debit':self.withdrawal_amount,
            'name':self.name or '/',
            'date_maturity':self.disbursement_date,
        }
        
        # If account requires member investments account, add it to the line
        if requires_member and account_product_type == 'investments':
            vals['investments_account_id'] = self.investments_account_id.id
            
        return vals
    
    def action_create_entry(self):
        self.disbursement_date = date.today()
        if self.disbursement_date:
            account_move_val = self.get_account_move_vals()
            account_move_id = self.env['account.move'].create(account_move_val)
            vals=[]
            if account_move_id:
                val = self.get_debit_lines()
                vals.append((0,0,val))
                val = self.get_credit_lines()
                vals.append((0,0,val))
                account_move_id.line_ids = vals
                self.disburse_journal_entry_id = account_move_id and account_move_id.id or False

                if account_move_id.state == 'draft':
                    account_move_id.action_post()  
                    self.investments_account_id.action_refresh_journal_lines()
        
        
    def action_disburse_withdrawal(self):
        self.action_create_entry()
        if self.disburse_journal_entry_id and self.disburse_journal_entry_id.state == 'posted':
            self.state = 'disburse'        
            transaction = self.env['sacco.investments.transaction'].create({
                'investments_account_id': self.investments_account_id.id,
                'member_id': self.member_id.id,
                'product_id': self.product_type.id,
                'transaction_type': 'withdrawal',
                'amount': self.withdrawal_amount,
                'transaction_date': self.disbursement_date,
                'status': 'pending',
            })
            
            transaction.action_confirm_transaction()            
            transaction.journal_entry_id = self.disburse_journal_entry_id
        else:
            raise UserError(_("Please Post the draft Entry for this Transaction !!!"))
        
    def unlink(self):
        for withdrawal_request in self:
            if withdrawal_request.state not in ['draft','cancel']:
                raise ValidationError(_('Withdrawal Request delete on Draft and cancel state only !!!.'))
        return super(InvestmentWithdrawalRequest, self).unlink()

    def _find_investments_account(self, member_id, investments_product, currency_id):
        """Find matching investments account for the withdrawal"""
        return self.env['sacco.investments.account'].search([
            ('member_id', '=', member_id),
            ('product_id', '=', investments_product.id),
            ('currency_id', '=', currency_id),
            ('state', '=', 'active')
        ], limit=1)

    @api.model
    def sync_withdrawal_requests(self):
        """Sync withdrawal requests from external system"""
        token = self._get_authentication_token()
        if not token:
            return self._show_notification('Error', 'Failed to obtain authentication token', 'danger')

        config = get_config(self.env)
        api_url = f"{config['BASE_URL']}/{GET_WITHDRAWAL_REQUESTS_ENDPOINT}"
        headers = self._get_request_headers()
        
        try:
            response = requests.get(api_url, headers=headers)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            _logger.error(f"Failed to fetch withdrawal requests: {str(e)}")
            return self._show_notification('Error', f'Failed to fetch withdrawal requests: {str(e)}', 'danger')

        success_count = 0
        error_count = 0

        for row in data.get('rows', []):
            try:
                _logger.info(f"Withdrawal Request data obtained")
                # Skip if not approved or if request already exists
                if row.get('status') != 'Approved':
                    continue
                
                existing_request = self.search([('ref_id', '=', row.get('refID'))])
                if existing_request:
                    continue

                # Get required records
                member = self.env['res.partner'].search([('member_id', '=', row.get('memberId'))], limit=1)
                if not member:
                    _logger.warning(f"Member with ID {row.get('memberId')} not found")
                    continue

                investments_product = self.env['sacco.investments.product'].search(
                    [('name', '=', row.get('product'))], 
                    limit=1
                )
                if not investments_product:
                    _logger.warning(f"Investments product {row.get('investmentsProduct')} not found")
                    continue

                currency = self.env['res.currency'].search([('name', '=', row.get('currency'))], limit=1)
                if not currency:
                    _logger.warning(f"Currency {row.get('currency')} not found")
                    continue

                # Find investments account
                investments_account = self._find_investments_account(member.id, investments_product, currency.id)
                if not investments_account:
                    _logger.warning(f"No active investments account found for member {member.name}")
                    continue

                # Check if withdrawal amount is valid
                withdrawal_amount = float(row.get('withdrawAmount', 0))
                if withdrawal_amount <= 0 or withdrawal_amount > investments_account.cash_balance:
                    _logger.warning(f"Invalid withdrawal amount {withdrawal_amount} for account {investments_account.name}")
                    continue

                # Parse dates
                request_date = datetime.strptime(row.get('dateCreated', ''), '%Y-%m-%dT%H:%M:%S.%f')
                approve_date = datetime.strptime(row.get('lastUpdated', ''), '%Y-%m-%dT%H:%M:%S.%f')

                # Create withdrawal request
                withdrawal = self.create({
                    'name': row.get('refID'),
                    'investments_account_id': investments_account.id,
                    'request_date': request_date.date(),
                    'approve_date': approve_date.date(),
                    'withdrawal_amount': withdrawal_amount,
                    'currency_id': currency.id,
                    'state': 'approve',
                    'mongo_db_id': row.get('_id'),
                    'ref_id': row.get('refID')
                })

                # Create journal entry and transaction
                withdrawal.action_create_entry()
                if withdrawal.disburse_journal_entry_id:
                    withdrawal.disburse_journal_entry_id.action_post()
                    withdrawal.action_disburse_withdrawal()
                    self.investments_account_id.action_refresh_journal_lines()
                
                success_count += 1
                
            except Exception as e:
                error_count += 1
                _logger.error(f"Error processing withdrawal request {row.get('refID', 'Unknown')}: {str(e)}")

        return self._show_notification(
            'Sync Complete', 
            f'Successfully processed {success_count} withdrawal requests. Errors: {error_count}',
            'success' if error_count == 0 else 'warning'
        )

    @api.depends('member_id')
    def _compute_available_products(self):
        """Compute available products based on member's active investment accounts"""
        for record in self:
            if record.member_id:
                investment_accounts = self.env['sacco.investments.account'].search([
                    ('member_id', '=', record.member_id.id),
                    ('state', '=', 'active')
                ])
                record.available_product_ids = investment_accounts.mapped('product_id')
            else:
                record.available_product_ids = False

    @api.onchange('member_id', 'product_type')
    def _onchange_selection(self):
        """Update investments account based on member and product selection"""
        self.investments_account_id = False
        if self.member_id and self.product_type:
            investment_account = self.env['sacco.investments.account'].search([
                ('member_id', '=', self.member_id.id),
                ('product_id', '=', self.product_type.id),
                ('state', '=', 'active')
            ], limit=1)
            if investment_account:
                self.investments_account_id = investment_account.id

    @api.onchange('member_id')
    def _onchange_member_id(self):
        """Clear dependent fields when member changes"""
        self.product_type = False
        self.investments_account_id = False
        
    def _show_notification(self, title, message, type='info'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'sticky': True,
                'type': type,
            }
        }
    