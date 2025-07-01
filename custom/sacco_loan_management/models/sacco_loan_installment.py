# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2015 DevIntelle Consulting Service Pvt.Ltd (<http://www.devintellecs.com>).
#
#    For Module Support : devintelle@gmail.com  or Skype : devintelle
#
##############################################################################

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime,date
from dateutil.relativedelta import relativedelta


class sacco_loan_installment(models.Model):
    _name = "sacco.loan.installment"
    _order = 'loan_id desc, date'
    _description = "Installment"
    
    
    name = fields.Char('Name')
    client_id = fields.Many2one('res.partner',string='Member')
    loan_id = fields.Many2one('sacco.loan.loan',string='Loan',required=True, ondelete='cascade')
    date = fields.Date('Date')
    state = fields.Selection([('unpaid','Unpaid'),('partial','Partial'), ('paid','Paid')], string='State', default='unpaid')
    opening_balance = fields.Float('Opening')
    amount = fields.Monetary('Principal Amount', compute='_get_amount')
    interest = fields.Monetary('Interest Amount', compute='_get_interest')
    closing_balance = fields.Float('Closing')
    total_amount = fields.Monetary('Estimated Monthly Installment')
    interest_account_id = fields.Many2one('account.account', string='Interest Account')
    installment_account_id = fields.Many2one('account.account', string='Installment Account')
    loan_payment_journal_id = fields.Many2one('account.journal', string='Payment Journal')
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry', copy=False)
    company_id = fields.Many2one('res.company', string='Company')
    payment_date = fields.Date('Payment Date')
    currency_id = fields.Many2one('res.currency', string='Currency')
    loan_state = fields.Selection(related='loan_id.state', string='Loan State')
    is_last_line = fields.Boolean('Last Line')
    none_interest = fields.Boolean('None Interest')
    paid_interest = fields.Float('Paid Interest')
    payment_ids = fields.One2many('sacco.loan.payments', 'installment_id', string='Payments', store=True)
    # New fields to track expected amounts
    expected_total_amount = fields.Monetary('Expected Monthly Installment', 
        help='The original EMI amount that was expected for this installment')
    expected_principal = fields.Monetary('Expected Principal Amount',
        help='The original principal amount that was expected for this installment')
    expected_interest = fields.Monetary('Expected Interest Amount',
        help='The original interest amount that was expected for this installment')
    excess_amount = fields.Monetary('Excess Amount', 
        help='Amount paid in excess of the expected monthly installment',
        compute='_compute_excess_amount', store=True)
    

    @api.depends('total_amount', 'expected_total_amount')
    def _compute_excess_amount(self):
        for record in self:
            if record.total_amount > record.expected_total_amount:
                record.excess_amount = record.total_amount - record.expected_total_amount
            else:
                record.excess_amount = 0.0

    # Override the create method to set expected amounts
    @api.model
    def create(self, vals):
        res = super(sacco_loan_installment, self).create(vals)
        for record in res:
            # Store the initial expected amounts
            record.write({
                'expected_total_amount': record.total_amount,
                'expected_principal': record.amount,
                'expected_interest': record.interest
            })
        return res   
    
    
    @api.depends('total_amount','interest','is_last_line','opening_balance')
    def _get_amount(self):
        for ins in self:
            if ins.opening_balance < ins.loan_id.emi_estimate:
                ins.amount = ins.opening_balance
            else:
                if not ins.is_last_line:
                    ins.amount = ins.total_amount - ins.interest
                    if ins.amount < 0:
                        ins.amount = 0
                else:
                    ins.amount = ins.opening_balance - ins.interest
                    
    
    @api.depends('opening_balance', 'none_interest', 'state', 'loan_id.interest_mode')
    def _get_interest(self):
        for ins in self:
            loan_id = ins.loan_id
            
            # Initialize interest to 0
            ins.interest = 0
            
            # Skip interest calculation if none_interest is True
            if ins.none_interest:
                continue
                
            if loan_id.interest_mode != 'flat':
                # Reducing balance method
                if ins.opening_balance:
                    if ins.state != 'paid':
                        ins.interest = (ins.opening_balance * (loan_id.interest_rate / 100)) / 12
                    else:
                        ins.interest = ins.paid_interest
            else:
                # Flat rate method
                if ins.state == 'unpaid':
                    ins.interest = ((loan_id.loan_amount * (loan_id.interest_rate / 100)) / 12)
                elif ins.state == 'partial':
                    # For partial payments, check remaining balance
                    if ins.opening_balance > 0:
                        ins.interest = ((loan_id.loan_amount * (loan_id.interest_rate / 100)) / 12)
                    else:
                        ins.interest = 0
                else:  # paid state
                    if ins.paid_interest > 0:
                        ins.interest = ins.paid_interest
                    else:
                        ins.interest = 0
                
    
    def loan_installment_reminder(self):
        mtp =self.env['mail.template']
        ir_model_data = self.env['ir.model.data'] 
        template_id = ir_model_data._xmlid_lookup('sacco_loan_management.installment_reminder_email_template')
        print ("template_id========",template_id)
        template_id = mtp.browse(template_id)
        reminder_days = self.env.user.company_id.ins_reminder_days or 0
        date = datetime.now() + relativedelta(days=reminder_days)
        date = date.strftime("%Y-%m-%d")
        installment_ids = self.search([('state','=','unpaid'),('loan_id.state','=','open'),('date','=',date)])
        for installment in installment_ids:
            a= template_id.send_mail(installment.id,True)
        
        
    def set_loan_close(self):
        if self.loan_id.remaining_amount <= 0:
            self.loan_id.state = 'close'

    def unlink(self):
        for installment in self:
            if installment.loan_id.state not in ['cancel','reject'] and not installment._context.get('force_delete'):
                raise ValidationError(_('You can not delete Loan Installment.'))
        return super(sacco_loan_installment, self).unlink()

