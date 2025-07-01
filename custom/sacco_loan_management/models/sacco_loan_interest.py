from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import logging

_logger = logging.getLogger(__name__)

class LoanInterest(models.Model):
    _name = 'sacco.loan.interest'
    _description = 'Loan Interest Records'
    _order = 'posting_date desc'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char('Reference', default='/', copy=False)
    client_id = fields.Many2one('res.partner', string='Member', domain=[('is_sacco_member', '=', True)], required=True)
    loan_id = fields.Many2one('sacco.loan.loan', string='Loan', required=True, ondelete='cascade', domain="[('id', 'in', available_loan_ids)]")
    available_loan_ids = fields.Many2many('sacco.loan.loan', string='Available Loans', compute='_compute_available_loans')
    posting_date = fields.Date('Posting Date', default=fields.Date.today(), required=True)
    calculation_from_date = fields.Date('Calculation From', required=True)
    calculation_to_date = fields.Date('Calculation To', required=True)
    interest_amount = fields.Monetary('Interest Amount', default=0.0)
    currency_id = fields.Many2one('res.currency', related='loan_id.currency_id', store=True)
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry', copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', required=True, tracking=True)
    
    # Tracking fields
    principal_balance = fields.Monetary('Principal Balance', help='Principal balance at time of interest posting')
    days_calculated = fields.Integer('Days Calculated', compute='_compute_days_calculated', store=True)
    interest_rate = fields.Float('Interest Rate', related='loan_id.interest_rate', store=True)
    interest_mode = fields.Selection(related='loan_id.interest_mode', store=True)
    previous_interest_id = fields.Many2one('sacco.loan.interest', string='Previous Interest Record', compute='_compute_previous_interest', store=True, readonly=True)
    paying_account_id = fields.Many2one('sacco.paying.account', string='Paying Account',
        help="The account that will be credited for this interest")
    pay_account = fields.Many2one('account.account', string='Pay Account')

    @api.depends('calculation_from_date', 'calculation_to_date')
    def _compute_days_calculated(self):
        for record in self:
            if record.calculation_from_date and record.calculation_to_date:
                record.days_calculated = (record.calculation_to_date - record.calculation_from_date).days
            else:
                record.days_calculated = 0

    @api.depends('loan_id', 'posting_date')
    def _compute_previous_interest(self):
        """Compute the previous interest record for the same loan"""
        for record in self:
            if record.loan_id and record.posting_date:
                previous_records = self.env['sacco.loan.interest'].search([
                    ('loan_id', '=', record.loan_id.id),
                    ('posting_date', '<', record.posting_date),
                    ('state', '=', 'posted'),
                ], order='posting_date desc', limit=1)
                record.previous_interest_id = previous_records.id if previous_records else False
            else:
                record.previous_interest_id = False

    @api.depends('client_id')
    def _compute_available_loans(self):
        """Compute available loans based on the selected member"""
        for record in self:
            if record.client_id:
                loans = self.env['sacco.loan.loan'].search([
                    ('client_id', '=', record.client_id.id),
                    ('state', 'in', ['open', 'disburse'])
                ])
                record.available_loan_ids = loans.ids
            else:
                record.available_loan_ids = []

    @api.onchange('client_id')
    def _onchange_client_id(self):
        """Clear loan selection when member changes and set default dates"""
        self.loan_id = False
        self.calculation_to_date = fields.Date.today()
        self.calculation_from_date = fields.Date.today()
        self.interest_amount = 0.0  # Reset interest amount
        
    @api.onchange('paying_account_id')
    def _onchange_paying_account_id(self):
        """Update pay_account when paying_account_id changes"""
        if self.paying_account_id:
            self.pay_account = self.paying_account_id.account_id
        else:
            self.pay_account = False

    @api.onchange('loan_id')
    def _onchange_loan_id(self):
        if self.loan_id and self.state == 'draft':
            self.calculation_to_date = fields.Date.today()
            # Set calculation_from_date based on last_interest_calculation_date or disbursement_date
            self.calculation_from_date = (
                self.loan_id.last_interest_calculation_date or
                self.loan_id.disbursement_date or
                self.loan_id.create_date.date() or
                fields.Date.today()
            )
            interest_amount = self.loan_id.calculate_interest(calculation_date=self.calculation_to_date)
            _logger.info(f"Calculated interest for loan {self.loan_id.name}: {interest_amount}")
            self.interest_amount = interest_amount
            self.principal_balance = self.loan_id.current_principal_balance
            # Set paying_account_id to the loan's paying_account_id, which defaults to the loan product's default_paying_account_id
            self.paying_account_id = self.loan_id.paying_account_id or self.loan_id.loan_type_id.default_paying_account_id
            self.pay_account = self.loan_id.pay_account or self.loan_id.loan_type_id.default_paying_account_id.account_id
            if interest_amount <= 0:
                return {
                    'warning': {
                        'title': _("No Interest Accrued"),
                        'message': _(
                            "No interest has accrued for this loan. This could be due to the loan state, "
                            "interest rate, calculation period, or missing disbursement date. Please review the loan details."
                        )
                    }
                }

    @api.constrains('interest_amount', 'loan_id', 'state')
    def _check_interest_amount(self):
        """Ensure interest_amount is set before saving or posting"""
        for record in self:
            if record.loan_id and record.interest_amount <= 0:
                _logger.warning(f"Validation failed for record {record.name}: loan_id={record.loan_id.id}, interest_amount={record.interest_amount}")
                raise ValidationError(_("Interest Amount must be greater than 0 for a loan interest record. Please select a loan to calculate the interest."))

    @api.model
    def create(self, vals):
        if vals.get('name', '/') == '/':
            vals['name'] = self.env['ir.sequence'].next_by_code('loan.interest.sequence') or '/'
        _logger.info(f"Creating loan interest record with values: {vals}")
        return super(LoanInterest, self).create(vals)
        
    def write(self, vals):
        """Ensure interest_amount is set before saving"""
        for record in self:
            if 'state' in vals and vals['state'] == 'posted' and record.interest_amount <= 0:
                raise ValidationError(_("Cannot post a loan interest record with an Interest Amount of 0. Please ensure a loan is selected and interest is calculated."))
        _logger.info(f"Updating loan interest record {self.name} with values: {vals}")
        return super(LoanInterest, self).write(vals)

    def action_post(self):
        for record in self:
            if record.state != 'draft':
                continue
                
            if record.interest_amount <= 0:
                raise ValidationError(_("Cannot post a loan interest record with an Interest Amount of 0. Please ensure a loan is selected and interest is calculated."))

            # Post the interest to the loan
            move = record.loan_id._create_interest_journal_entry(record)
            
            if move:
                # Update the loan's interest tracking fields
                record.loan_id.write({
                    'last_interest_calculation_date': record.calculation_to_date,
                    'accrued_interest': record.loan_id.accrued_interest + record.interest_amount,
                    'next_interest_calculation_date': record.calculation_to_date + relativedelta(months=1)
                })
                record.write({
                    'state': 'posted',
                    'journal_entry_id': move.id
                })
    
    def action_cancel(self):
        for record in self:
            if record.state != 'posted':
                continue
                
            # Check if there are later posted records
            later_records = self.env['sacco.loan.interest'].search([
                ('loan_id', '=', record.loan_id.id),
                ('posting_date', '>', record.posting_date),
                ('state', '=', 'posted'),
            ])
            if later_records:
                raise ValidationError(_("Cannot cancel this interest record because there are later posted interest records. Please cancel the later records first."))

            # Reverse the journal entry
            if record.journal_entry_id:
                if record.journal_entry_id.state == 'posted':
                    reverse_move = record.journal_entry_id._reverse_moves()
                    record.write({'journal_entry_id': reverse_move.id})
                else:
                    record.journal_entry_id.button_cancel()

            # Reset the loan's last_interest_calculation_date to the previous record's calculation_to_date
            previous_date = record.previous_interest_id.calculation_to_date if record.previous_interest_id else False
            new_accrued_interest = record.loan_id.accrued_interest - record.interest_amount
            if new_accrued_interest < 0:
                new_accrued_interest = 0.0

            # Update the loan's fields
            record.loan_id.write({
                'last_interest_calculation_date': previous_date,
                'accrued_interest': new_accrued_interest,
                'next_interest_calculation_date': previous_date + relativedelta(months=1) if previous_date else False
            })

            # Update the state to cancelled
            record.write({'state': 'cancelled'})