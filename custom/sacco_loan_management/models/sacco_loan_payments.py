from odoo import models, api, fields, _
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta
from datetime import date
import logging
import uuid

_logger = logging.getLogger(__name__)

class LoanPayments(models.Model):
    _name = 'sacco.loan.payments'
    _description = 'Loan Payments'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'payment_date desc, id desc'
    
    name = fields.Char(string='Payment Reference', compute="_get_payment_ref", store=True)
    loan_id = fields.Many2one('sacco.loan.loan', string='Loan Reference', domain="[('id', 'in', available_loan_ids)]", store=True)
    installment_id = fields.Many2one('sacco.loan.installment', string='Loan Installment',
                                    help='The installment this payment is associated with', store=True)
    client_id = fields.Many2one('res.partner', string='Member', domain=[('is_sacco_member', '=', 'True')], required=True, store=True)
    loan_type_id = fields.Many2one('sacco.loan.type', string='Loan Type', store=True, required=True, domain="[('id', 'in', available_product_ids)]")
    amount = fields.Float(string='Payment Amount', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                 compute='_compute_currency_id', store=True, readonly=False,
                                 tracking=True, default=lambda self: self.env.company.currency_id)
    payment_date = fields.Date(string='Payment Date', default=fields.Date.today(), required=True)
    status = fields.Selection([('pending', 'Pending'), ('approved', 'Approved')], 
                            string='Status', default='pending')
    created_by = fields.Char(string="Created By")
    mongo_db_id = fields.Char(string='Mongo DB ID', 
                             help='Unique mongo db ID from the source system')
    ref_id = fields.Char(string="Reference ID")
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry', copy=False)
    available_product_ids = fields.Many2many('sacco.loan.type', 
                                           compute='_compute_available_products')
    available_loan_ids = fields.Many2many(
            'sacco.loan.loan',
            string='Available Loans',
            compute='_compute_available_loans'
        )
    # Payment allocation (computed after processing)
    principal_paid = fields.Float(string='Principal Portion', readonly=True)
    interest_paid = fields.Float(string='Interest Portion', readonly=True)
    receiving_account_id = fields.Many2one('sacco.receiving.account', string='Receiving Account',
        help="The account that received this deposit")
    receipt_account = fields.Many2one('account.account', string='Receipt Account')
    general_transaction_id = fields.Many2one('sacco.general.transaction', string='General Transaction', ondelete='restrict')
    missing_loan = fields.Boolean(string='Missing Loan', default=False, readonly=True,
                                 help="Indicates if the loan record is missing in the local database")

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('increment_loan_payment_ref')
        return super(LoanPayments, self).create(vals)
    
    def unlink(self):
        for loan_payment in self:
            if loan_payment.journal_entry_id:
                raise ValidationError(_('Cannot delete payment with associated journal entries. Please set the entry to draft then delete it'))
            if loan_payment.general_transaction_id:
                raise ValidationError(_('Cannot delete payment linked to a general transaction. Please unlink it first.'))
            # Store the associated loan for refreshing journal lines
            loan = loan_payment.loan_id
            # Perform the deletion
            super(LoanPayments, loan_payment).unlink()
            # Refresh journal lines for the associated loan
            if loan:
                loan.action_refresh_journal_lines()
        return True
      
    def _get_payment_ref(self):
        for record in self:
            record.name = str(uuid.uuid4())

    @api.constrains('amount')        
    def check_amount(self):                
        for line in self:
            if line.amount <= 0:
                raise ValidationError(_("Amount must be greater than zero."))
            
    @api.depends('loan_id', 'missing_loan')
    def _compute_currency_id(self):
        for record in self:
            if record.loan_id and not record.missing_loan:
                record.currency_id = record.loan_id.currency_id
            else:
                record.currency_id = record.env.company.currency_id
            
    @api.depends('client_id')
    def _compute_available_products(self):
        """Compute available loan products based on member's loans"""
        for record in self:
            if record.client_id:
                # Get all loans for the member
                loans = self.env['sacco.loan.loan'].search([
                    ('client_id', '=', record.client_id.id),
                    ('state', 'in', ['open', 'close'])
                ])
                # Get unique product IDs from those loans
                record.available_product_ids = loans.mapped('loan_type_id').ids
            else:
                record.available_product_ids = []
 
    @api.depends('loan_type_id')
    def _compute_available_loans(self):
        """Compute available savings products based on member's loans"""
        for record in self:
            if record.client_id and record.loan_type_id:
                # Get all loans for the member
                loans = self.env['sacco.loan.loan'].search([
                    ('client_id', '=', record.client_id.id),
                    ('loan_type_id', '=', record.loan_type_id.id),
                    ('state', 'in', ['open', 'close'])
                ])
                record.available_loan_ids = loans.ids
            else:
                record.available_loan_ids = []
                
    @api.onchange('client_id')
    def _onchange_client_id(self):
        """Clear product and loan selection when member changes"""
        self.loan_type_id = False
        self.loan_id = False  
        
    @api.onchange('receiving_account_id')
    def _onchange_receiving_account_id(self):
        """Update receipt_account when receiving_account_id changes"""
        if self.receiving_account_id:
            self.receipt_account = self.receiving_account_id.account_id
        else:
            self.receipt_account = False
            
    @api.onchange('loan_type_id')
    def _onchange_loan_type_id(self):
        if self.loan_type_id and self.loan_type_id.default_receiving_account_id:
            self.receiving_account_id = self.loan_type_id.default_receiving_account_id.id
            
    def action_approve_payment(self):
        """Process the payment through the loan"""
        self.ensure_one()
        for payment in self:
            if payment.status != 'pending':
                raise ValidationError(_("Only pending payments can be processed."))
                
            if payment.missing_loan:
                raise ValidationError(_("Cannot approve payment: No local loan record found. Please create the corresponding loan first."))
                
            if not payment.loan_id:
                raise ValidationError(_("No loan selected for this payment."))
                
            # Ensure receipt_account is set
            if not payment.receipt_account and payment.receiving_account_id:
                payment.receipt_account = payment.receiving_account_id.account_id
            elif not payment.receipt_account:
                raise ValidationError(_("A receipt account is required for loan payments. Please configure a receiving account."))

            payment.loan_id.process_payment(payment)
        
        return True
        
    def action_reverse(self):
        """Reverse the payment by setting journal entries to draft and deleting them, then setting payment to pending"""
        for payment in self:
            if payment.status != 'approved':
                raise ValidationError(_("Only approved payments can be reversed."))
                
            # Set journal entry to draft if it exists
            if payment.journal_entry_id and payment.journal_entry_id.state == 'posted':
                payment.journal_entry_id.button_draft()
                
            # Delete the journal entry
            if payment.journal_entry_id:
                payment.journal_entry_id.unlink()
                
            # Reset payment to pending
            payment.write({
                'status': 'pending',
                'principal_paid': 0.0,
                'interest_paid': 0.0,
                'journal_entry_id': False
            })