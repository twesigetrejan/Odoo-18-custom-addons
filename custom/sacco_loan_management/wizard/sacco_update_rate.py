# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2015 DevIntelle Consulting Service Pvt.Ltd (<http://www.devintellecs.com>).
#
#    For Module Support : devintelle@gmail.com  or Skype : devintelle 
#
##############################################################################

from odoo import api, fields, models, _
from datetime import datetime
import calendar
import itertools
from operator import itemgetter
import operator
from odoo.exceptions import ValidationError

class sacco_update_rate(models.TransientModel):
    _name = "sacco.update.rate"
    _description = 'Update Interest Rate'
    
    rate = fields.Float('Rate', required=True)
    
    def update_rate(self):
        if self.rate <= 0:
            raise ValidationError(_('Rate must be positive'))
            
        loan_id = self.env['sacco.loan.loan'].browse(self._context.get('active_id'))
        loan_id.interest_rate = self.rate
        
        installment_ids = self.env['sacco.loan.installment'].search([
            ('loan_id', '=', loan_id.id),
            ('state', '=', 'unpaid') # ('state', '!=', 'paid')
        ], order='date')
        
        if not installment_ids:
            return
            
        opening_balance = installment_ids[0].opening_balance
        total_remaining = len(installment_ids)
        
        for idx, installment in enumerate(installment_ids):
            is_last = (idx == len(installment_ids) - 1)
            remaining_months = total_remaining - idx
            
            # Calculate new expected interest based on opening balance
            if loan_id.interest_mode != 'flat':
                new_expected_interest = (opening_balance * (self.rate / 100)) / 12
                new_expected_interest = float("{:.2f}".format(new_expected_interest))
            else:
                new_expected_interest = ((loan_id.loan_amount * (self.rate / 100)) / 12)
            
            # Calculate expected principal and total amount
            if is_last:
                new_expected_principal = opening_balance
                new_expected_total = new_expected_principal + new_expected_interest
            else:
                # Calculate new EMI based on remaining balance and term
                if loan_id.interest_mode != 'flat':
                    monthly_rate = (self.rate / 100) / 12
                    if monthly_rate > 0:
                        new_expected_total = (opening_balance * monthly_rate * (1 + monthly_rate)**remaining_months) / ((1 + monthly_rate)**remaining_months - 1)
                    else:
                        new_expected_total = opening_balance / remaining_months
                else:
                    new_expected_total = (opening_balance / remaining_months) + new_expected_interest
                
                new_expected_principal = new_expected_total - new_expected_interest
            
            # Calculate actual amounts
            total_paid = sum(payment.amount for payment in installment.payment_ids.filtered(lambda p: p.status == 'approved'))
            
            if total_paid == 0:
                # No payments made
                new_state = 'unpaid'
                actual_interest = 0
                actual_principal = 0
                new_closing_balance = opening_balance
            elif total_paid < new_expected_interest:
                # Payment below interest amount
                new_state = 'partial'
                actual_interest = total_paid
                actual_principal = 0
                new_closing_balance = opening_balance
            elif total_paid < new_expected_total:
                # Payment covers interest but not full EMI
                new_state = 'partial'
                actual_interest = new_expected_interest
                actual_principal = total_paid - new_expected_interest
                new_closing_balance = opening_balance - actual_principal
            else:
                # Payment covers full EMI or more
                new_state = 'paid'
                actual_interest = new_expected_interest
                actual_principal = min(opening_balance, total_paid - new_expected_interest)
                new_closing_balance = max(0, opening_balance - actual_principal)
            
            # Update the installment
            installment.write({
                'opening_balance': opening_balance,
                'interest': actual_interest,
                'amount': actual_principal,
                'total_amount': total_paid if total_paid > 0 else new_expected_total,
                'closing_balance': new_closing_balance,
                'expected_interest': new_expected_interest,
                'expected_principal': new_expected_principal,
                'expected_total_amount': new_expected_total,
                'state': new_state,
                'is_last_line': is_last,
                'none_interest': total_paid == 0
            })
            
            # Update opening balance for next iteration
            opening_balance = new_closing_balance
            
            # If balance is fully paid, mark remaining installments as zero
            if opening_balance <= 0:
                remaining_installments = installment_ids.filtered(
                    lambda x: x.date > installment.date
                )
                if remaining_installments:
                    remaining_installments.write({
                        'opening_balance': 0,
                        'closing_balance': 0,
                        'amount': 0,
                        'interest': 0,
                        'total_amount': 0,
                        'expected_interest': 0,
                        'expected_principal': 0,
                        'expected_total_amount': 0,
                        'state': 'paid',
                        'none_interest': True
                    })
                break
        # Store the current term before updating rate
        current_term = len(loan_id.installment_ids.filtered(lambda x: x.state == 'unpaid'))
        
        # Update rate logic
        loan_id.interest_rate = self.rate
        
        update_term_wizard = self.env['sacco.update.term'].create({
            'months': current_term
        })
        update_term_wizard.with_context(active_id=loan_id.id).update_term()
            
            
# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:    
    
