from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from ..config import (get_config, UPDATE_LOAN_APPLICATION_COLLECTION_ENDPOINT, CREATE_UPDATE_LOANS_STATEMENT_COLLECTION_ENDPOINT, CREATE_NOTIFICATIONS_COLLECTION_ENDPOINT)
import requests
import logging
import time
import random
import binascii

_logger = logging.getLogger(__name__)

class sacco_loan_loan(models.Model):
    _name = "sacco.loan.loan"
    _inherit = ['mail.thread', 'mail.activity.mixin', 'api.token.mixin']
    _order = 'request_date desc, id desc'
    _description = "Loan"
    
    name = fields.Char('Name', default='/', copy=False)
    client_id = fields.Many2one('res.partner', domain=[('is_allow_loan','=',True), ('is_sacco_member', '=', True)], required=True, string='Member')
    request_date =fields.Date('Request Date', default=fields.Date.today(), required=True)
    approve_date = fields.Date('Approve Date', copy=False)
    disbursement_date = fields.Date('Disbursement Date', copy=False)
    loan_type_id = fields.Many2one('sacco.loan.type', string='Loan Product', required=True)
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    loan_amount = fields.Monetary('Loan Amount', required=True)
    is_interest_apply = fields.Boolean(related='loan_type_id.is_interest_apply', string='Apply Interest')
    interest_rate = fields.Float(string='Interest Rate')
    none_interest_month = fields.Integer(string='None Interest Month')
    loan_term = fields.Integer('Loan Period (months)', required=True)
    interest_mode = fields.Selection(related='loan_type_id.interest_mode', string='Interest Mode')	
    
    state = fields.Selection([('draft','Draft'),
                              ('confirm','Confirmed'),
                              ('approve','Approved'),
                              ('disburse','Disbursed'),
                              ('open','Open'),
                              ('close','Closed'),
                              ('cancel','Cancelled'),
                              ('reject','Rejected')], string='State', required=True, default='draft', track_visibility='onchange')
    
    
    installment_ids = fields.One2many('sacco.loan.installment','loan_id', string='Installments')
    
    total_interest = fields.Monetary('Expected Interest Amount', compute='get_total_interest')
    paid_amount = fields.Monetary('Paid Amount', compute='get_total_interest')
    remaining_amount = fields.Monetary('Remaing Amount', compute='get_total_interest')
    notes = fields.Text('Notes about the Loan')
    reject_reason = fields.Text('Reject Reason', copy=False)
    reject_user_id = fields.Many2one('res.users','Reject By', copy=False)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self:self.env.user.company_id.id)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, tracking=True, default=lambda self: self._get_default_currency())
    proof_ids = fields.Many2many('sacco.loan.proof', string='Loan Proof') 
    loan_account_id = fields.Many2one('account.account', string='Disburse Account')
    disburse_journal_id = fields.Many2one('account.journal', string='Disburse Journal')
    disburse_journal_entry_id = fields.Many2one('account.move', string='Disburse Account Entry', copy=False)
    loan_url = fields.Char('URL', compute='get_loan_url')
    loan_document_ids = fields.One2many('ir.attachment','res_id', string='Loan Document')
    attachment_number = fields.Integer(compute='_compute_attachment_number', string='Number of Attachments')
    emi_estimate = fields.Monetary(string="Estimated Monthly Payment", compute="_estimated_monthly_payment")
    count_installment = fields.Integer('Count Installment', compute='_get_count_installment')
    payment_ids = fields.One2many('sacco.loan.payments', 'loan_id', string='Payments') 
    paying_account_id = fields.Many2one('sacco.paying.account', string='Paying Account',
        help="The account that received this withdrawal")
    pay_account = fields.Many2one('account.account', string='Pay Account')
    guarantor_ids = fields.One2many('sacco.loan.guarantor', 'loan_id', string='Guarantors')
    security_ids = fields.One2many('sacco.loan.security', 'loan_id', string='Securities', help="Linked securities for this loan")
    security_count = fields.Integer('Security Count', compute='_get_security_count', help="Count of securities linked to this loan")
    
    # Balance tracking fields
    current_principal_balance = fields.Monetary('Current Principal Balance', compute='_compute_balances', store=True)
    total_interest_paid = fields.Monetary(
        'Total Interest Paid', 
        compute='_compute_balances', 
        store=True, 
        help="Total interest paid, calculated from journal lines where payments are applied to accrued interest."
    )
    total_principal_paid = fields.Monetary('Total Principal Paid', compute='_compute_balances', store=True)
    last_interest_calculation_date = fields.Date('Last Interest Calculation', 
                                               default=lambda self: fields.Date.today())
    next_interest_calculation_date = fields.Date('Next Interest Calculation')
    interest_ids = fields.One2many('sacco.loan.interest', 'loan_id', string='Interest Records')
    total_interest_accrued = fields.Monetary('Total Interest Accrued', compute='_compute_interest_totals', store=True)
    total_interest_outstanding = fields.Monetary('Outstanding Interest', compute='_compute_interest_totals', store=True)
    loans_journal_account_lines = fields.One2many(
        'sacco.loans.journal.account.line',
        'loan_id',
        string='Journal Account Lines',
        readonly=True
    )
    
    # MIS fields
    specify = fields.Text('Loan Purpose', help="Purpose or description of the loan")
    account_name = fields.Char('Account Name', help="Name of the account holder")
    account_number = fields.Char('Account Number', help="Bank account number")
    bank_name = fields.Char('Bank Name', help="Name of the bank")
    branch = fields.Char('Bank Branch', help="Bank branch")
    
    statement_mongo_db_id = fields.Char('Loan Statement MongoDB Id', copy=False)
    last_statement_sync_date = fields.Date(
        string='Last Statement Sync Date',
        readonly=True,
        help='Tracks the last time a statement was synced with the external system'
    )
    update_statement = fields.Boolean(
        string='Allow Statement Update',
        default=False,
        tracking=True,
        help='Toggle to allow statement update to external system'
    )
    
    loan_mongo_db_id = fields.Char('Loan MongoDB ID', readonly=True, copy=False)
    loan_ref_id = fields.Char('Loan Ref ID', readonly=True, copy=False)
    last_sync_date = fields.Datetime(string='Last Sync Date')
    in_sync = fields.Boolean(string='In Sync', default=True, help='Indicates if the loan is synchronized with the external system')
    
    def _compute_attachment_number(self):
        for loan in self:
            loan.attachment_number = len(loan.loan_document_ids.ids)
    
    def action_get_attachment_view(self):
        self.ensure_one()
        res = self.env['ir.actions.act_window']._for_xml_id('base.action_attachment')
        res['domain'] = [('res_model', '=', 'sacco.loan.loan'), ('res_id', 'in', self.ids)]
        res['context'] = {'default_res_model': 'sacco.loan.loan', 'default_res_id': self.id}
        return res
        
    def action_view_installment(self):
        if self.installment_ids:
            action = self.env.ref('sacco_loan_management.action_sacco_loan_installment').read()[0]
            action['domain'] = [('id', 'in', self.installment_ids.ids),('state','not in',['draft','reject','cancel'])]
            action['context']= {}
            return action
        else:
            return {'type': 'ir.actions.act_window_close'}
    
    @api.depends('security_ids')
    def _get_security_count(self):
        for loan in self:
            if loan.security_ids:
                loan.security_count = len(loan.security_ids)
            else:
                loan.security_count = 0

    def action_view_securities(self):
        self.ensure_one()
        action = self.env.ref('sacco_loan_management.action_view_securities').read()[0]
        action['domain'] = [('loan_id', '=', self.id)]
        action['context'] = {'default_loan_id': self.id}
        return action
        
    def action_refresh_journal_lines(self):
        """Refresh journal lines for this loan"""
        self.env['sacco.loans.journal.account.line'].refresh_journal_lines(self.id)
        return True
    
    
    @api.model
    def _get_default_currency(self):
        """Get default currency from product if available, otherwise company currency"""
        if self._context.get('default_product_id'):
            product = self.env['sacco.loan.type'].browse(self._context.get('default_product_id'))
            return product.currency_id
        return self.env.company.currency_id
        

    @api.depends('loans_journal_account_lines')
    def _compute_balances(self):
        """Compute current balances based on journal account lines, tracking interest paid chronologically."""
        for loan in self:
            # Get journal lines for this loan, sorted by date
            journal_lines = loan.loans_journal_account_lines.sorted(key=lambda l: l.date)

            # Initialize variables
            outstanding_interest = 0.0  # Tracks unpaid accrued interest
            total_principal_paid = 0.0  # Total principal paid
            total_interest_paid = 0.0   # Total interest paid (calculated)
            disbursed_amount = 0.0      # Initial loan amount disbursed
            total_paid = 0.0            # Total amount paid
            total_interest_accrued = 0.0

            # Process journal lines chronologically
            for line in journal_lines:
                if line.transaction_type == 'disbursement':
                    # Record the initial disbursement
                    disbursed_amount += line.principal_amount
                elif line.transaction_type == 'interest':
                    # Add to outstanding interest when interest is accrued
                    total_interest_accrued += line.interest_amount
                    outstanding_interest += line.interest_amount
                elif line.transaction_type == 'payment':
                    # Allocate payment: first to interest, then to principal
                    total_paid += line.total_amount
                    payment_amount = line.total_amount

                    # Step 1: Apply payment to outstanding interest
                    interest_paid = min(outstanding_interest, payment_amount)
                    if interest_paid > 0:
                        total_interest_paid += interest_paid
                        outstanding_interest -= interest_paid

                    # Step 2: Apply remaining payment to principal
                    remaining_payment = payment_amount - interest_paid
                    if remaining_payment > 0:
                        total_principal_paid += remaining_payment

            # Fallback logic in case interest-paid is inconsistent
            inferred_interest_paid = total_paid - total_principal_paid
            if inferred_interest_paid < total_interest_paid:
                # We overestimated interest paid, fallback to inferred value
                total_interest_paid = max(0.0, inferred_interest_paid)

            # Assign computed values to fields
            loan.total_principal_paid = total_principal_paid
            loan.total_interest_paid = min(total_interest_paid, total_interest_accrued)
            loan.current_principal_balance = max(0, disbursed_amount - total_principal_paid)

            # Optional: store total_interest_accrued if needed
            loan.total_interest_accrued = total_interest_accrued

            # Check if loan is fully paid
            if self.remaining_amount <= 0 and self.state == 'open':
                self.write({'state': 'close'})

            # Log for debugging
            _logger.info(f"Loan {loan.name}: "
                        f"Total Paid = {total_paid}, "
                        f"Total Interest Accrued = {total_interest_accrued}, "
                        f"Total Interest Paid = {total_interest_paid}, "
                        f"Total Principal Paid = {total_principal_paid}, "
                        f"Current Principal Balance = {loan.current_principal_balance}")
                
    @api.depends('installment_ids', 'payment_ids', 'loans_journal_account_lines')
    def get_total_interest(self):
        """Compute total interest, paid amount, and remaining amount based on journal lines and installments."""
        for loan in self:
            # Calculate total expected interest from installment schedule
            total_interest = sum(installment.interest for installment in loan.installment_ids)

            # Get journal lines for this loan, sorted by date
            journal_lines = loan.loans_journal_account_lines.sorted(key=lambda l: l.date)

            # Calculate paid amount as the sum of all payment transactions
            paid_amount = sum(
                line.total_amount 
                for line in journal_lines 
                if line.transaction_type == 'payment'
            )

            # Compute the running balance to determine the remaining amount
            running_balance = 0.0

            # Identify the disbursement line
            disbursement_line = journal_lines.filtered(lambda l: l.transaction_type == 'disbursement')
            if not disbursement_line and journal_lines:
                # Fallback to the first journal line if no disbursement line
                disbursement_line = journal_lines[:1]

            # Initialize running balance with the disbursement amount if available
            if disbursement_line:
                running_balance = disbursement_line[0].principal_amount
                processed_disbursement = disbursement_line[0].id
            else:
                running_balance = loan.loan_amount  # Fallback to loan_amount if no journal lines
                processed_disbursement = False

            # Process the disbursement line first if it exists
            if disbursement_line:
                statement_data = {
                    'date': disbursement_line[0].date,
                    'type': 'Disbursement',
                    'amount': disbursement_line[0].total_amount,
                    'principal': disbursement_line[0].principal_amount,
                    'interest': disbursement_line[0].interest_amount,
                    'balance': running_balance,
                    'journal_entry': disbursement_line[0].journal_entry_id.name,
                }

            # Process remaining journal lines (excluding disbursement) sorted by date, only after disbursement
            remaining_lines = journal_lines.filtered(lambda l: l.id != processed_disbursement) if processed_disbursement else journal_lines
            if disbursement_line:
                remaining_lines = remaining_lines.filtered(lambda l: l.date >= disbursement_line[0].date)
            for line in remaining_lines.sorted(key=lambda l: l.date):
                if line.transaction_type == 'payment':
                    running_balance -= line.principal_amount
                elif line.transaction_type == 'interest':
                    running_balance += line.interest_amount

            # Ensure the running balance doesn't go negative
            running_balance = max(0, running_balance)

            # Assign computed values to the fields
            loan.total_interest = total_interest
            loan.paid_amount = paid_amount
            loan.remaining_amount = running_balance

    @api.depends('interest_ids.interest_amount', 'interest_ids.state', 'payment_ids.interest_paid')
    def _compute_interest_totals(self):
        for loan in self:
            # Get journal lines for this loan to calculate actual payments
            journal_lines = loan.loans_journal_account_lines.sorted(key=lambda l: l.date)
            
            # Calculate total interest accrued and paid from journal lines
            loan.total_interest_accrued = sum(
                line.interest_amount 
                for line in journal_lines 
                if line.transaction_type == 'interest'
            )
            
            # Outstanding interest = accrued - paid
            loan.total_interest_outstanding = loan.total_interest_accrued - loan.total_interest_paid
            # Update guarantor's released_flag and securities when loan is closed
            if loan.state == 'close' and self.state == 'open':
                if loan.guarantor_ids and not all(g.released_flag for g in loan.guarantor_ids):
                    loan.guarantor_ids.write({'released_flag': True})
                if loan.security_ids:
                    loan.security_ids.write({
                        'security_status': 'released',
                        'release_date': fields.Date.today()
                    })

    @api.model
    def refresh_computed_fields(self):
        loans = self.search([])
        for loan in loans:
            # Invalidate cache to force recomputation
            loan._compute_balances()
            loan._compute_interest_totals()
            loan._estimated_monthly_payment()
        return True
                
    @api.onchange('loan_type_id')
    def _onchange_loan_type_id(self):
        if self.loan_type_id and self.loan_type_id.default_paying_account_id:
            self.paying_account_id = self.loan_type_id.default_paying_account_id.id
            
    @api.onchange('paying_account_id')
    def _onchange_paying_account_id(self):
        """Update pay_account when paying_account_id changes"""
        if self.paying_account_id:
            self.pay_account = self.paying_account_id.account_id
        else:
            self.pay_account = False
            
    def calculate_interest(self, calculation_date=None):
        """Calculate interest for the loan as of a specific date"""
        self.ensure_one()
        
        if not calculation_date:
            calculation_date = fields.Date.today()
            
        if self.state not in ['open', 'disburse']:
            return 0.0
            
        # Determine the start date for interest calculation
        start_date = self.last_interest_calculation_date
        if not start_date:
            # If last_interest_calculation_date is False, use disbursement_date or creation date
            start_date = self.disbursement_date or self.create_date.date()
            if not start_date:
                # If no start date is available, return 0 to avoid errors
                return 0.0
        
        # Calculate days since last calculation
        days_since_last_calc = (calculation_date - start_date).days
        if days_since_last_calc <= 0:
            return 0.0
        
        # Calculate interest based on interest mode
        if self.interest_mode == 'reducing':
            interest = (self.current_principal_balance * (self.interest_rate / 100) * days_since_last_calc) / 365
        else:  # flat interest
            interest = (self.loan_amount * (self.interest_rate / 100) * days_since_last_calc) / 365
            
        return interest
    
    def post_interest(self, calculation_date=None):
        """Calculate and post interest as journal entry"""
        self.ensure_one()
        
        if not calculation_date:
            calculation_date = fields.Date.today()
            
        interest_amount = self.calculate_interest(calculation_date)
        if interest_amount <= 0:
            return False
            
        # Create interest record
        interest_record = self.env['sacco.loan.interest'].create({
            'loan_id': self.id,
            'posting_date': calculation_date,
            'calculation_from_date': self.last_interest_calculation_date,
            'calculation_to_date': calculation_date,
            'interest_amount': interest_amount,
            'principal_balance':  max(0, self.current_principal_balance),
        })
        
        # Post the interest record
        interest_record.action_post()
        
        # Update last interest calculation date
        self.write({
            'last_interest_calculation_date': calculation_date,
            'next_interest_calculation_date': calculation_date + relativedelta(months=1)
        })
        
        return interest_record

    @api.model
    def post_monthly_loan_interest(self):
        """Post interest for all open or disbursed loans at the beginning of the month."""
        _logger.info("Starting monthly loan interest posting cron job")
        
        # Get the first day of the current month
        today = fields.Date.today()
        calculation_date = today.replace(day=1)
        
        # Search for loans in 'open' or 'disburse' state with interest applicable
        loans = self.search([
            ('state', 'in', ['open', 'disburse']),
            ('is_interest_apply', '=', True),
        ])
        
        success_count = 0
        failed_count = 0
        
        for loan in loans:
            try:
                # Check if interest should be posted for this loan
                if loan.next_interest_calculation_date and loan.next_interest_calculation_date > calculation_date:
                    _logger.debug(f"Skipping loan {loan.name}: Next interest calculation date is {loan.next_interest_calculation_date}")
                    continue
                
                if loan.none_interest_month > 0:
                    start_date = loan.disbursement_date or loan.approve_date or loan.request_date
                    months_since_start = relativedelta(calculation_date, start_date).months
                    if months_since_start < loan.none_interest_month:
                        _logger.debug(f"Skipping loan {loan.name}: Within none-interest period")
                        continue
                    
                # Post interest for the loan
                interest_record = loan.post_interest(calculation_date)
                if interest_record:
                    success_count += 1
                    _logger.info(f"Successfully posted interest for loan {loan.name}")
                else:
                    _logger.warning(f"No interest posted for loan {loan.name}: Zero or invalid interest amount")
            except Exception as e:
                failed_count += 1
                _logger.error(f"Failed to post interest for loan {loan.name}: {str(e)}")
        
        _logger.info(f"Monthly interest posting completed: {success_count} successful, {failed_count} failed")
        
        # Return a notification for the system logs
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Monthly Loan Interest Posting',
                'message': f"Processed {len(loans)} loans: {success_count} successful, {failed_count} failed",
                'type': 'info',
                'sticky': False,
            }
        }

    def _create_interest_journal_entry(self, interest_record):
        """Create journal entry for interest accrual with proper account associations"""
        interest_account_id, installment_account_id, loan_payment_journal_id = self.get_loan_account_journal()
        
        if not interest_account_id or not installment_account_id:
            raise ValidationError(_("Missing accounting configuration for interest posting!"))
        
        # Ensure the interest record has a pay_account
        if not interest_record.pay_account:
            raise ValidationError(_("Please select a paying account for the interest record."))
        
        # Create interest journal entry
        journal = self.env['account.journal'].browse(loan_payment_journal_id)
        
        # Get account objects
        pay_account = interest_record.pay_account
        interest_income_account = self.env['account.account'].browse(self.loan_type_id.interest_account_id.id)
        
        move_vals = {
            'ref': f'Loan Interest: {self.name} ({interest_record.name})',
            'journal_id': journal.id,
            'date': interest_record.posting_date,
            'move_type': 'entry',
            'partner_id': self.client_id.id,  # Set partner at move level
            'line_ids': []
        }
        
        # Credit interest paying account
        credit_line_vals = {
            'account_id': pay_account.id,
            'credit': interest_record.interest_amount,
            'debit': 0.0,
            'partner_id': self.client_id.id,
            'name': f'Interest accrual for loan {self.name}',
        }
        
        # Debit interest income
        debit_line_vals = {
            'account_id': interest_income_account.id,
            'credit': 0.0,
            'debit': interest_record.interest_amount,
            'partner_id': self.client_id.id,
            'name': f'Interest income for loan {self.name}',
            'member_id': self.client_id.member_id if self.client_id and self.client_id.member_id else False,
        }
        
        # Add loan_id if account type is 'loans' or 'loans_interest'
        if interest_income_account.account_product_type in ('loans', 'loans_interest'):
            debit_line_vals['loan_id'] = self.name
            
        move_vals['line_ids'].append((0, 0, debit_line_vals))
        
        move_vals['line_ids'].append((0, 0, credit_line_vals))
        
        # Create and post the journal entry
        try:
            move = self.env['account.move'].create(move_vals)
            move.action_post()
            
            # Link the move to the interest record
            interest_record.write({'journal_entry_id': move.id})
            
            _logger.info(f"Created interest journal entry: {move.name} for loan {self.name}")
            return move
        except Exception as e:
            _logger.error(f"Error creating interest journal entry: {str(e)}")
            raise ValidationError(_(f"Error creating interest journal entry: {str(e)}"))

    def process_payment(self, payment):
        """Process a loan payment, treating the full amount as principal"""
        self.ensure_one()
        
        if payment.status != 'pending':
            return False
        
        # Treat the entire payment amount as principal
        principal_paid = payment.amount
        
        # Update the payment with allocation details (no interest)
        payment.write({
            'interest_paid': 0.0,  # No interest allocation
            'principal_paid': principal_paid,
            'status': 'approved',
            'payment_date': payment.payment_date or fields.Date.today()
        })
        
        # Update last interest calculation date (optional, keep for consistency)
        self.write({
            'last_interest_calculation_date': payment.payment_date or fields.Date.today()
        })
        
        # Create journal entry for the payment
        self._create_payment_journal_entry(payment)
        
        # Check if loan is fully paid
        if self.remaining_amount <= 0 and self.state == 'open':
            self.write({'state': 'close'})
        
        return True
    
    def _create_payment_journal_entry(self, payment):
        """Create journal entry for loan payment with full amount as principal"""
        interest_account_id, installment_account_id, loan_payment_journal_id = self.get_loan_account_journal()
        _logger.info("interest_account_id: %s, installment_account_id: %s, loan_payment_journal_id: %s", 
                    interest_account_id, installment_account_id, loan_payment_journal_id)
        
        if not loan_payment_journal_id or not installment_account_id:
            raise ValidationError(_("Missing accounting configuration for this loan type! (Journal or Installment Account)"))
        
        # Validate receipt_account
        if not payment.receipt_account:
            raise ValidationError(_("No receipt account specified for the payment. Please configure a receiving account."))
        
        # Prepare journal entry
        journal = self.env['account.journal'].browse(loan_payment_journal_id)
        
        move_vals = {
            'ref': f'Loan Payment: {self.name}',
            'journal_id': journal.id,
            'date': payment.payment_date,
            'move_type': 'entry',
            'partner_id': self.client_id.id,  # Set partner at move level
            'line_ids': []
        }
        
        # Debit receipt account (total payment amount)
        receipt_line_vals = {
            'account_id': payment.receipt_account.id,
            'debit': payment.amount,
            'credit': 0.0,
            'partner_id': self.client_id.id,
            'name': f'Loan payment received for {self.name}',
        }
        move_vals['line_ids'].append((0, 0, receipt_line_vals))
        
        # Credit installment account (full payment amount as principal)
        installment_account = self.env['account.account'].browse(installment_account_id)
        principal_line_vals = {
            'account_id': installment_account_id,
            'credit': payment.amount,  # Full amount credited as principal
            'debit': 0.0,
            'partner_id': self.client_id.id,
            'name': f'Principal payment for loan {self.name}',
            'member_id': self.client_id.member_id if self.client_id and self.client_id.member_id else False,
        }
        if installment_account.account_product_type in ('loans', 'loans_interest'):
            principal_line_vals['loan_id'] = self.name
        move_vals['line_ids'].append((0, 0, principal_line_vals))
        
        # Create and post the journal entry
        try:
            move = self.env['account.move'].create(move_vals)
            move.action_post()
            self.action_refresh_journal_lines()
            
            # Link the journal entry to the payment
            payment.write({'journal_entry_id': move.id})
            
            _logger.info(f"Created payment journal entry: {move.name} for loan {self.name}")
            return move
        except Exception as e:
            _logger.error(f"Error creating payment journal entry: {str(e)}")
            raise ValidationError(_(f"Error creating payment journal entry: {str(e)}"))
    

    def generate_loan_statement(self, start_date=None, end_date=None):
        """Generate a detailed loan statement based on journal account lines and included amortization schedule."""
        self.ensure_one()

        if not start_date:
            start_date = self.disbursement_date or self.approve_date or self.request_date
        if not end_date:
            end_date = fields.Date.today()

        # Get all journal account lines for this loan within the date range
        journal_lines = self.env['sacco.loans.journal.account.line'].search([
            ('loan_id', '=', self.id),
            ('date', '>=', start_date),
            ('date', '<=', end_date),
        ]).sorted(key=lambda l: l.date)

        # Build amortization schedule from installment_ids
        amortization_schedule = []
        for installment in self.installment_ids.sorted(key=lambda i: i.date):
            amortization_schedule.append({
                'date': installment.date,
                'opening_balance': installment.opening_balance,
                'principal': installment.amount,
                'interest': installment.interest,
                'total_payment': installment.total_amount,
                'closing_balance': installment.closing_balance,
            })
            
        # Build statement data
        statement_data = {
            'loan_details': {
                'name': self.name,
                'client_id': self.client_id.name,
                'loan_id': self.name,
                'loan_amount': self.loan_amount,
                'current_balance': self.remaining_amount,
                'interest_rate': self.interest_rate,
                'loan_term': self.loan_term,
                'interest_mode': self.interest_mode,
                'disbursement_date': self.disbursement_date,
                'product': self.loan_type_id.name,
                'estimated_monthly_installment': self.emi_estimate,
                'original_maturity_date': (self.disbursement_date + relativedelta(months=self.loan_term)) if self.disbursement_date else None,
            },
            'transactions': [],
            'summary': {
                'total_paid': 0.0,
                'total_principal_paid': sum(line.principal_amount for line in journal_lines if line.transaction_type == 'payment'),
                'total_interest_paid': self.total_interest_paid,
                'total_interest_accrued': sum(line.interest_amount for line in journal_lines if line.transaction_type == 'interest'),
                'current_principal_balance': max(0, self.current_principal_balance),
                'accrued_interest': 0.0  # Will compute this below
            },
            'amortization_schedule': amortization_schedule
        }

        # Calculate total paid and total interest accrued from journal lines
        for line in journal_lines:
            if line.transaction_type == 'payment':
                statement_data['summary']['total_paid'] += line.total_amount
            elif line.transaction_type == 'interest':
                statement_data['summary']['total_interest_accrued'] += line.interest_amount

        # Calculate outstanding accrued interest (total accrued - total paid)
        outstanding_accrued_interest = statement_data['summary']['total_interest_accrued'] - statement_data['summary']['total_interest_paid']
        statement_data['summary']['accrued_interest'] = max(0, outstanding_accrued_interest)

        # Initialize running balance
        running_balance = 0.0
                
        # Identify the disbursement line
        disbursement_line = journal_lines.filtered(lambda l: l.transaction_type == 'disbursement')
        _logger.info(f"Disbursement line for loan {self.name}: {disbursement_line}")
        if not disbursement_line and journal_lines:
            # If no disbursement line is found, use the first journal line as a fallback
            disbursement_line = journal_lines[:1]
            _logger.info(f"No disbursement line found for loan {self.name}. Using first journal line (ID: {disbursement_line[0].id}, Date: {disbursement_line[0].date}) as disbursement.")

        # Initialize running balance with the disbursement amount if available
        running_balance = 0.0
        if disbursement_line:
            running_balance = disbursement_line[0].principal_amount
            statement_data['transactions'].append({
                'date': disbursement_line[0].date,
                'type': 'Disbursement',
                'amount': disbursement_line[0].total_amount,
                'principal': disbursement_line[0].principal_amount,
                'interest': disbursement_line[0].interest_amount,
                'balance': running_balance,  # Initial balance after disbursement
                'journal_entry': disbursement_line[0].journal_entry_id.name,
            })
            processed_disbursement = disbursement_line[0].id
        else:
            processed_disbursement = False

        # Process remaining journal lines (excluding the disbursement line) sorted by date
        remaining_lines = journal_lines.filtered(lambda l: l.id != processed_disbursement) if processed_disbursement else journal_lines
        for line in remaining_lines.sorted(key=lambda l: l.date):
            if line.transaction_type == 'payment':
                running_balance -= line.principal_amount
            elif line.transaction_type == 'interest':
                running_balance += line.interest_amount
            
            # Append transaction with updated balance
            statement_data['transactions'].append({
                'date': line.date,
                'type': line.transaction_type.capitalize().replace('_', ' '),
                'amount': line.total_amount,
                'principal': line.principal_amount,
                'interest': line.interest_amount,
                'balance': running_balance,  # Ensure balance doesn't go negative
                'journal_entry': line.journal_entry_id.name,
            })

        running_balance = running_balance

        # Update the summary balance to reflect the final running balance
        statement_data['summary']['current_principal_balance'] = running_balance

        return statement_data
            
    def unlink(self):
        """Delete the loan and its associated installments and guarantor if in draft or cancel state."""
        for loan in self:
            if loan.state not in ['draft', 'cancel']:
                raise ValidationError(_('Loan delete on Draft and cancel state only !!!.'))
            
            # Delete all associated installments
            if loan.installment_ids:
                loan.installment_ids.unlink()
            
            # Delete associated guarantor
            if loan.guarantor_ids:
                loan.guarantor_ids.unlink()
        
        # Call the parent unlink to delete the loan record itself
        return super(sacco_loan_loan, self).unlink()
        
    
    @api.depends('installment_ids')
    def _get_count_installment(self):
        for loan in self:
            if loan.installment_ids:
                loan.count_installment = len(loan.installment_ids)
            else:
                loan.count_installment = 0
                              
    @api.depends('interest_rate','loan_term','loan_amount')
    def _estimated_monthly_payment(self):
        for loan in self:
            loan.emi_estimate = 0.0
            if loan.interest_rate and loan.loan_amount and loan.loan_term:
                if loan.interest_mode == 'reducing':
                    if loan.interest_rate and loan.loan_term and loan.loan_amount:
                        k = 12
                        i = loan.interest_rate / 100
                        a = i / k or 0.00
                        b = (1 - (1 / ((1 + (i / k)) ** loan.loan_term))) or 0.00
                        emi = ((loan.loan_amount * a) / b) or 0.00
                        loan.emi_estimate =  emi
                else:
                    loan.emi_estimate = (loan.loan_amount / loan.loan_term) + ((loan.loan_amount * (loan.interest_rate / 100)) / 12)
                    
    
    @api.depends('client_id')
    def get_loan_url(self):
        for loan in self:
            loan.loan_url =  ''
            if loan.client_id:
                base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', default='http://localhost:8069')
                if base_url:
                    base_url += '/web/login?db=%s&login=%s&key=%s#id=%s&model=%s' % (
                    self._cr.dbname, '', '', loan.id, 'sacco.loan.loan')
                    loan.loan_url = base_url
                    
                    
    # @api.depends('installment_ids', 'payment_ids', 'loans_journal_account_lines')
    # def get_total_interest(self):
    #     """Compute total interest, paid amount, and remaining amount based on journal lines and installments."""
    #     for loan in self:
    #         # Calculate total expected interest from installment schedule
    #         total_interest = sum(installment.interest for installment in loan.installment_ids)

    #         # Get journal lines for this loan to calculate actual payments
    #         journal_lines = loan.loans_journal_account_lines.sorted(key=lambda l: l.date)

    #         # Calculate paid amount as the sum of all payment transactions
    #         paid_amount = sum(
    #             line.total_amount 
    #             for line in journal_lines 
    #             if line.transaction_type == 'payment'
    #         )

    #         # Calculate the running balance to determine the remaining amount
    #         running_balance = 0.0



    #         # The remaining amount is the final running balance
    #         remaining_amount = running_balance

    #         # Assign computed values to the fields
    #         loan.total_interest = total_interest
    #         loan.paid_amount = paid_amount
    #         loan.remaining_amount = remaining_amount
    
    
    @api.depends('total_interest','loan_amount')
    def get_total_amount_to_pay(self):
        for loan in self:
            loan.total_amount_to_pay = loan.total_interest + loan.loan_amount
    
    def get_loan_account_journal(self):
        interest_account_id = installment_account_id = loan_payment_journal_id = False
        if not self.loan_type_id:
            raise ValidationError(_("Please Select the Loan Product !!!"))
        if self.loan_type_id.interest_account_id:
            interest_account_id = self.loan_type_id.interest_account_id and self.loan_type_id.interest_account_id.id or False
        
        if self.loan_type_id.installment_account_id:
            installment_account_id = self.loan_type_id.installment_account_id and self.loan_type_id.installment_account_id.id or False
        
        if self.loan_type_id.loan_payment_journal_id:
            loan_payment_journal_id = self.loan_type_id.loan_payment_journal_id and self.loan_type_id.loan_payment_journal_id.id or False
            
        return interest_account_id,installment_account_id,loan_payment_journal_id
            
    
    def compute_installment(self,date=False):
        if self.installment_ids:
            for installment in self.installment_ids:
                installment.with_context({'force_delete':True}).unlink()
        opening_balance = self.loan_amount
        if self.state == 'draft':
            date = self.request_date
        else:
            date = self.disbursement_date
        vals = []
        interest_account_id,installment_account_id,loan_payment_journal_id = self.get_loan_account_journal()
        interest =  ((self.loan_amount * (self.interest_rate / 100)) / 12)
        for i in range(1,self.loan_term+1):
            emi = float("{:.2f}".format(self.emi_estimate))
            if self.interest_mode != 'flat':
                interest = (opening_balance * (self.interest_rate / 100)) / 12
            interest = float("{:.2f}".format(interest))
            if opening_balance < emi:
                emi = opening_balance + interest
            principal = emi - interest
            closing_amount = opening_balance - principal
            date = date+relativedelta(months=1)
            none_interest = False
            if i <= self.none_interest_month:
                none_interest = True
                closing_amount = opening_balance - emi
            if closing_amount < 0.0:
                closing_amount = 0.0
            vals.append((0, 0,{
                'name':'INS - '+self.name+ ' - '+str(i),
                'client_id':self.client_id and self.client_id.id or False,
                'date':date,
                'opening_balance':opening_balance,
                'amount':principal,
                'none_interest':none_interest,
                'interest':interest,
                'closing_balance':closing_amount,
                'total_amount':float("{:.2f}".format(interest+principal)),
                'state':'unpaid',
                'interest_account_id':interest_account_id or False,
                'installment_account_id':installment_account_id or False,
                'loan_payment_journal_id':loan_payment_journal_id or False,
                'currency_id':self.currency_id and self.currency_id.id or False,
            }))
            opening_balance = closing_amount
        self.installment_ids = vals
            
            
    # @api.constrains('client_id','request_date')
    # def check_number_of_client_loan(self):
    #     for loan in self:
    #         if loan.client_id and loan.request_date:
    #             no_of_loan_allow = loan.client_id.loan_request
    #             start_date = date(date.today().year, 1, 1)
    #             start_date = start_date.strftime('%Y-%m-%d')
    #             end_date = date(date.today().year, 12, 31)
    #             end_date = end_date.strftime('%Y-%m-%d')
    #             loan_ids = loan.env['sacco.loan.loan'].search([('request_date','<=',end_date),('request_date','>=',start_date),('state','not in',['cancel','reject']),('client_id','=',loan.client_id.id)])
                
    #             if len(loan_ids) > no_of_loan_allow:
    #                 raise ValidationError(_("This Member allow only %s Loan Request in Year !!!")%(no_of_loan_allow))
            
    
    @api.onchange('loan_type_id')
    def onchange_loan_type(self):
        if self.loan_type_id:
            self.interest_rate = self.loan_type_id and self.loan_type_id.rate or 0.0
            self.none_interest_month = self.loan_type_id and self.loan_type_id.none_interest_month or 0
        else:
            self.interest_rate = 0.0
            self.none_interest_month = 0
            
        if self.loan_type_id and self.loan_type_id.proof_ids:
            self.proof_ids = [(6,0, self.loan_type_id.proof_ids.ids)]
        else:
            self.proof_ids = False
            
            
    
    @api.constrains('loan_term','loan_amount','loan_type_id')        
    def check_rate(self):
        if self.loan_term <= 0:
            raise ValidationError(_("Loan Period Must be Positive !!!"))
                
        if self.loan_amount <= 0:
            raise ValidationError(_("Loan Amount Must be Positive !!!"))
            
    @api.model
    def create(self,vals):
        vals.update({
                    'name':self.env['ir.sequence'].next_by_code('sacco.loan.loan') or '/'
                })
        
        # Ensure interest_rate is set from loan_type_id if not provided
        if 'interest_rate' not in vals and 'loan_type_id' in vals:
            loan_type = self.env['sacco.loan.type'].browse(vals['loan_type_id'])
            vals['interest_rate'] = loan_type.rate or 0.0
        
        return super(sacco_loan_loan, self).create(vals)
    
    
    def get_loan_manager_mail(self):
        group_id = self.env.ref('sacco_loan_management.group_loan_manager').id
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
    
    def get_loan_officer_mail(self):
        group_id = self.env.ref('sacco_loan_management.group_loan_loans_officer').id
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
        
        
    def action_confirm_loan(self):
        self.state = 'confirm'
        ir_model_data = self.env['ir.model.data']
        template_id = ir_model_data._xmlid_lookup('sacco_loan_management.sacco_loan_loan_request')[1]
        mtp = self.env['mail.template']
        template_id = mtp.browse(template_id)
        email = self.get_loan_manager_mail()
        template_id.write({'email_to': email})
        template_id.send_mail(self.ids[0], True)

        # Set security status to 'verified' for all securities
        if self.security_ids:
            self.security_ids.write({'security_status': 'verified'})   
        
    def get_accountant_mail(self):
        group_id = self.env.ref('account.group_account_user').id
        group_id = self.env['res.groups'].browse(group_id)
        email = ''
        if group_id:
            for user in group_id.users:
                if user.partner_id and user.partner_id.email:
                    if email:
                        email = email + ',' + user.partner_id.email
                    else:
                        email = user.partner_id.email
        return email
    
    def action_approve_loan(self):
        self.state = 'approve'
        if self.loan_type_id:
            self.loan_account_id = self.loan_type_id.loan_account_id and self.loan_type_id.loan_account_id.id or False
            self.disburse_journal_id = self.loan_type_id.disburse_journal_id and self.loan_type_id.disburse_journal_id.id or False
        
        if not self.approve_date:
            self.approve_date = date.today()
        
        try:
            # Send email notification to accountant
            email = self.get_accountant_mail()
            if email:
                template_id = self.env.ref('sacco_loan_management.sacco_loan_approval_accountant_notification')
                template_id.write({'email_to': email})
                template_id.send_mail(self.id, force_send=True)
                _logger.info(f"Loan approval notification sent to accountant: {email}")

            # Upload loan status
            self.upload_loan_status('Approved', 'approve')

            # Send notification to member
            message = f"""Hello <b>{self.client_id.name}</b>,<br>
            We are pleased to inform you that your loan application has been approved. Below are the details:
            <br>Loan Amount: {self.currency_id.symbol}{self.loan_amount:,.2f}
            <br>Approval Date: {self.approve_date.strftime('%Y-%m-%d')}
            <br>Loan Type: {self.loan_type_id.name}
            <br>The loan will be disbursed soon. You will receive another notification when the loan is ready for payments.
            <br>If you have any questions, feel free to contact our support team.<br>
            <br>Thank you for choosing our service!<br>
            Best regards
            """
            notification = self._prepare_notification("Loan Application Approved", message)
            self._send_notification(notification)

        except Exception as e:
            _logger.error(f"Failed to send loan approval notification: {str(e)}")
            return self._show_notification('Error', f'Failed to send approval notification, Please contact support', 'danger')
        
    def action_set_to_draft(self):
        if self.installment_ids:
            for installment in self.installment_ids:
                installment.unlink()
        self.state = 'draft'
                
        # Reset security status to 'pending_verification' for all securities
        if self.security_ids:
            self.security_ids.write({'security_status': 'pending_verification'})   
    
    
    def get_account_move_vals(self):
        if not self.disburse_journal_id:
            raise ValidationError(_("Select Disburse Journal !!!"))
        vals={
            'date':self.disbursement_date,
            'ref':self.name or 'Loan Disburse',
            'journal_id':self.disburse_journal_id and self.disburse_journal_id.id or False,
            'company_id':self.company_id and self.company_id.id or False,
        }
        return vals
    
    
    def get_debit_lines(self):
        if not self.loan_account_id:
            raise ValidationError(_("Select Disburse Account !!!"))
        
        vals={
            'partner_id':self.client_id and self.client_id.id or False,
            'account_id':self.loan_account_id and self.loan_account_id.id or False,
            'debit':self.loan_amount,
            'name':self.name or '/',
            'date_maturity':self.disbursement_date,
            'member_id': self.client_id.member_id if self.client_id and self.client_id.member_id else False,
        }
        if self.loan_account_id.account_product_type in ('loans', 'loans_interest'):
            vals['loan_id'] = self.name
        
        return vals
    
    def get_credit_lines(self):
        if self.client_id and not self.client_id.property_account_receivable_id:
            raise ValidationError(_("Select Client Receivable Account !!!"))
        account_id = self.pay_account
        vals={
            'partner_id':self.client_id and self.client_id.id or False,
            'account_id':account_id and account_id.id or False,
            'credit':self.loan_amount,
            'name':self.name or '/',
            'date_maturity':self.disbursement_date,
        }
        
        return vals
        
        
    
    def action_disburse_loan(self):
        self.upload_loan_status('Disbursed', 'disburse')
        if not self.disbursement_date:
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
                self.action_refresh_journal_lines()  
                
        if self.disburse_journal_entry_id:
            self.state = 'disburse'
            
            # Send email notification to loans officer
            email = self.get_loan_officer_mail()
            template_id = self.env.ref('sacco_loan_management.sacco_loan_disbursement_notification')
            if template_id:
                template_id.write({'email_to': email})
                template_id.send_mail(self.id, force_send=True)
                
        self.compute_installment(self.disbursement_date)
        
        if self.state != "open":
            self.action_open_loan()        
    
    
    def action_open_loan(self):
        # Send notification
        message = f"""Hello <b>{self.client_id.name}</b>,<br>We are pleased to inform you that your loan application has been disbursed and your loan is now open for payment. Below are the details:
        <br>Loan Amount: {self.currency_id.symbol}{self.loan_amount:,.2f}<br>Disbursement Date: {self.disbursement_date.strftime('%Y-%m-%d')}<br>To make your payments or view your loan details, please log in to your account.
        <br>If you have any questions, feel free to contact our support team.<br>Thank you for choosing our service!<br>
        Best regards
        """
        
        notification = self._prepare_notification(
            "Loan Open for Payment",
            message
        )
        self._send_notification(notification)
        self.state = 'open'
        self.post_or_update_statement()
        
    
    def action_cancel(self):
        self.state = 'cancel'
        self.upload_loan_status('Cancelled', 'cancel')
        
        # Send email notification to manager
        email = self.get_loan_manager_mail()
        template_id = self.env.ref('sacco_loan_management.sacco_loan_cancellation_notification')
        if template_id:
            template_id.write({'email_to': email})
            template_id.send_mail(self.id, force_send=True)
            
        
    def upload_loan_status(self, api_status, odoo_state, remarks=None):
        """Upload loan status to external system and update Odoo state."""
        def action_callback():
            config = get_config(self.env)
            api_url = f"{config['BASE_URL']}/{UPDATE_LOAN_APPLICATION_COLLECTION_ENDPOINT}/{self.loan_mongo_db_id}"
            headers = self._get_request_headers()
            
            data = {
                'status': api_status,
                'loanId': self.name,
            }
            if remarks:
                data['remarks'] = remarks
            
            _logger.info(f"Uploading data: {data}")
            response = requests.put(api_url, headers=headers, json=data)
            response.raise_for_status()
            return self._show_notification('Upload Complete', f'Successfully updated the loan status to {api_status}', 'success')

        def local_update_callback():
            self.state = odoo_state

        return self._handle_external_action(
            action_callback=action_callback,
            local_update_callback=local_update_callback,
            success_message=f'Successfully updated the loan status to {api_status}',
            local_message=f'Loan status updated locally to {odoo_state}. Will sync with external system later.'
        )
        
    def _get_payment_details(self, installment):
        """Get payment details for an installment."""
        total_paid = sum(payment.amount for payment in installment.payment_ids)
        
        # Calculate the proportion of principal paid
        if total_paid > 0:
            # If payment is less than or equal to interest, no principal is paid
            if total_paid <= installment.expected_interest:
                principal_paid = 0
                interest_paid = total_paid
            else:
                # If payment exceeds interest, calculate principal portion
                interest_paid = installment.expected_interest
                principal_paid = min(total_paid - interest_paid, installment.expected_principal)
        else:
            # For expected payments, use the expected amounts
            principal_paid = installment.expected_principal
            interest_paid = installment.interest
            total_paid = 0
            
        return {
            'amount_paid': total_paid,
            'principal_paid': principal_paid,
            'interest_paid': interest_paid,
            'is_paid': bool(installment.payment_ids),
            'payment_date': installment.payment_ids[0].payment_date if installment.payment_ids else False
        }

    def _generate_mongo_like_id(self):
        """Generate a 24-character hexadecimal string similar to MongoDB ObjectId"""
        # 4 bytes timestamp (8 hex chars)
        timestamp = int(time.time()).to_bytes(4, byteorder='big')
        # 5 bytes random (10 hex chars)
        random_bytes = random.randbytes(5)
        # 3 bytes counter (6 hex chars) - using random for simplicity
        counter = random.randint(0, 0xFFFFFF).to_bytes(3, byteorder='big')
        
        # Combine and convert to hex
        object_id = binascii.hexlify(timestamp + random_bytes + counter).decode('utf-8')
        return object_id

    def post_or_update_statement(self, start_date=None, end_date=None):
        """Post or update the loan statement to the external system using a single endpoint."""
        self.ensure_one()

        _logger.info(f"Starting statement post/update for loan {self.name}")

        # Default dates if not provided
        if not start_date:
            start_date = self.disbursement_date or self.approve_date or self.request_date
        if not end_date:
            last_installment = self.env['sacco.loan.installment'].search([
                ('loan_id', '=', self.id)
            ], order='date desc', limit=1)
            end_date = last_installment.date if last_installment else fields.Date.today()

        # Get authentication token
        token = self._get_authentication_token()
        if not token:
            _logger.error(f"Failed to get auth token for loan {self.name}")
            return self._show_notification('Error', 'Failed to connect with external system', 'danger')

        # Generate statement data using the existing generate_loan_statement method
        statement_data_raw = self.generate_loan_statement(start_date=start_date, end_date=end_date)

        # Prepare amortization schedule
        amortization_schedule = [
            {
                "period": index + 1,
                "payment": float(installment['total_payment']),
                "principal": float(installment['principal']),
                "interest": float(installment['interest']),
                "balance": float(installment['closing_balance'])
            } for index, installment in enumerate(statement_data_raw['amortization_schedule'])
        ]

        # Compute amortization summary
        total_payment = sum(installment['total_payment'] for installment in statement_data_raw['amortization_schedule'])
        total_interest = sum(installment['interest'] for installment in statement_data_raw['amortization_schedule'])
        monthly_payment = self.emi_estimate  # From computed field

        amortization_data = {
            "schedule": amortization_schedule,
            "summary": {
                "monthlyPayment": float(monthly_payment),
                "totalPayment": float(total_payment),
                "totalInterest": float(total_interest),
                "loanAmount": float(self.loan_amount),
                "interestRate": float(self.interest_rate),
                "loanPeriod": self.loan_term
            }
        }
               
        # Prepare statement data in the format expected by the external system
        statement_data = {
            "memberId": self.client_id.member_id,
            "memberName": self.client_id.name,
            "loanId": self.name,
            "startDate": start_date.isoformat() if start_date else None,
            "endDate": end_date.isoformat() if end_date else None,
            "requestDate": fields.Date.today().isoformat(),
            "product": self.loan_type_id.name,
            "loanAmount": float(self.loan_amount),
            "currentBalance": float(self.remaining_amount),
            "interestRate": self.interest_rate,
            'loanPeriod': self.loan_term,
            'interestMode': self.interest_mode,
            'estimatedMonthlyInstallment': self.emi_estimate,
            "productType": "Loans", 
            "currency": self.currency_id.name,
            'disbursementDate': self.disbursement_date.isoformat() if self.disbursement_date else None,
            "transactions": [
                {
                    "date": tx['date'].isoformat() if isinstance(tx['date'], date) else tx['date'],
                    "description": tx['type'],
                    "amount": float(tx['amount']),
                    "principal": float(tx['principal']),
                    "interest": float(tx['interest']),
                    "balance": float(tx['balance']),
                } for tx in statement_data_raw['transactions']
            ],
            "summary": {
                "totalPaid": float(statement_data_raw['summary']['total_paid']),
                "totalPrincipalPaid": float(statement_data_raw['summary']['total_principal_paid']),
                "totalInterestPaid": float(statement_data_raw['summary']['total_interest_paid']),
                "totalInterestAccrued": float(statement_data_raw['summary']['total_interest_accrued']),
                "currentPrincipalBalance": float(statement_data_raw['summary']['current_principal_balance']),
                "accruedInterest": float(statement_data_raw['summary']['accrued_interest'])
            },
            "amortization": amortization_data, 
            "createdBy": self.client_id.member_id
        }

        # Prepare headers and API URL
        headers = self._get_request_headers()
        config = get_config(self.env)

        # Use existing statement_mongo_db_id or generate a new one
        mongo_id = self.statement_mongo_db_id
        if not mongo_id:
            mongo_id = self._generate_mongo_like_id()
            self.write({'statement_mongo_db_id': mongo_id})
            _logger.info(f"Generated new MongoDB-like ID for loan {self.name}: {mongo_id}")

        api_url = f"{config['BASE_URL']}/{CREATE_UPDATE_LOANS_STATEMENT_COLLECTION_ENDPOINT}/{mongo_id}".rstrip('/')

        # Post or update the statement
        try:
            _logger.info(f"Posting/Updating loan statement to {api_url}")
            response = requests.post(api_url, headers=headers, json=statement_data)
            response.raise_for_status()

            response_data = response.json()
            if response_data and 'docId' in response_data:
                new_mongo_id = response_data['docId']
                if new_mongo_id != mongo_id:
                    self.write({'statement_mongo_db_id': new_mongo_id})
                    _logger.info(f"Updated statement_mongo_db_id for loan {self.name} to {new_mongo_id}")

            self.write({'last_statement_sync_date': fields.Date.today()})
            self.env.cr.commit()
            _logger.info(f"Successfully posted/updated statement for loan {self.name}")

            return self._show_notification(
                'Success',
                'Successfully posted/updated loan statement in external system',
                'success'
            )
        except requests.RequestException as e:
            error_msg = f"Failed to post/update loan statement: {str(e)}"
            _logger.error(error_msg)
            return self._show_notification('Error', 'Failed to post/update loan statement', 'danger')
            
    @api.model
    def sync_all_pending_statements(self):
        """Syncs all pending statements for all loans in the system"""
        _logger.info("====================== Starting sync of pending loan statements ============================")
        
        loans = self.search([
            ('state', 'in', ['open', 'disburse', 'close']),
        ])
        
        for loan in loans:
            try:
                loan.post_or_update_statement()
            except Exception as e:
                _logger.error(f"Failed to sync statement for loan {loan.name}: {str(e)}")
                continue
                
        _logger.info("===================== Completed sync of pending loan statements =========================")
        
    def _prepare_notification(self, header, message):
        """Helper method to prepare notification data"""
        return {
            "notificationType": "information",
            "group": "",
            "sender": "odoo",
            "isRead": False,
            "messageHeader": header,
            "messageText": message,
            "sendDate": datetime.now().isoformat(),
            "endDate": "",
            "createdBy": self.client_id.member_id
        }

    def _send_notification(self, notification_data):
        """Helper method to send notification to external system"""
        try:
            config = get_config(self.env)
            token = self._get_authentication_token()
            if not token:
                return False

            headers = self._get_request_headers()
            url = f"{config['BASE_URL']}/{CREATE_NOTIFICATIONS_COLLECTION_ENDPOINT}"
            
            response = requests.post(url, headers=headers, json=notification_data)
            response.raise_for_status()
            return True
        except Exception as e:
            _logger.error(f"Failed to send notification: {str(e)}")
            return False
    
    def action_mass_sync_loan_statements(self):
        """Mass action to sync loan statements for selected records"""
        if not self:
            raise ValidationError(_("No records selected for statement synchronization."))
        
        _logger.info(f"Starting mass statement sync for {len(self)} loans")
        
        success_count = 0
        skipped_count = 0
        failed_count = 0
        
        for loan in self:
            try:
                if loan.state in ['open', 'disburse', 'close']:
                    loan.post_or_update_statement()
                    loan.write({'update_statement': False})
                    self.env.cr.commit()
                    success_count += 1
                    _logger.info(f"Successfully synced statement for loan {loan.name}")
                else:
                    skipped_count += 1
                    _logger.warning(f"Skipping loan {loan.name} - not in valid state for statement sync")
            except Exception as e:
                self.env.cr.rollback()
                failed_count += 1
                _logger.error(f"Failed to sync statement for loan {loan.name}: {str(e)}")
        
        message = _(f"Statement sync completed: {success_count} successful, {skipped_count} skipped, {failed_count} failed")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Statement Sync Complete'),
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }