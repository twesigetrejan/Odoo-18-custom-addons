from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta

class DevUpdateTerm(models.TransientModel):
    _name = "sacco.update.term"
    _description = 'Update Loan Term'
    
    months = fields.Integer('Number of Months', required=True)
    
    def update_term(self):
        if self.months <= 0:
            raise ValidationError(_('Number of months must be positive'))
            
        loan_id = self.env['sacco.loan.loan'].browse(self._context.get('active_id'))
        
        # Get existing installments
        all_installments = loan_id.installment_ids.sorted(lambda x: x.date)
        paid_installments = all_installments.filtered(lambda x: x.state in ['paid', 'partial'])
        unpaid_installments = all_installments.filtered(lambda x: x.state == 'unpaid')
        
        if not unpaid_installments:
            return
            
        # Calculate remaining balance and start date for new installments
        opening_balance = unpaid_installments[0].opening_balance
        start_date = unpaid_installments[0].date
        
        # Delete existing unpaid installments
        unpaid_installments.with_context(force_delete=True).unlink()
        
        # Calculate new EMI
        if loan_id.interest_mode == 'reducing':
            k = 12
            i = loan_id.interest_rate / 100
            a = i / k or 0.00
            b = (1 - (1 / ((1 + (i / k)) ** self.months))) or 0.00
            emi = ((opening_balance * a) / b) if b != 0 else (opening_balance / self.months)
        else:
            interest = ((opening_balance * (loan_id.interest_rate / 100)) / 12)
            emi = (opening_balance / self.months) + interest

        emi = float("{:.2f}".format(emi))
        
        # Get accounts and journal from loan type
        interest_account_id, installment_account_id, loan_payment_journal_id = loan_id.get_loan_account_journal()
        
        remaining_balance = opening_balance
        
        # Create new installments
        for i in range(self.months):
            is_last = (i == self.months - 1)
            
            if loan_id.interest_mode != 'flat':
                interest = (remaining_balance * (loan_id.interest_rate / 100)) / 12
            else:
                interest = ((loan_id.loan_amount * (loan_id.interest_rate / 100)) / 12)
                
            interest = float("{:.2f}".format(interest))
            
            if is_last:
                # For last installment, ensure remaining balance is fully covered
                principal = remaining_balance
                total_amount = principal + interest
            else:
                if remaining_balance < emi:
                    principal = remaining_balance
                    total_amount = principal + interest
                else:
                    principal = emi - interest
                    total_amount = emi
                    
            # Ensure no negative values
            principal = max(0, principal)
            closing_balance = max(0, remaining_balance - principal)
            
            if is_last:
                closing_balance = 0  # Force closing balance to zero for last installment
                
            installment_date = start_date + relativedelta(months=i)
            
            self.env['sacco.loan.installment'].create({
                'name': 'INS - ' + loan_id.name + ' - ' + str(len(paid_installments) + i + 1),
                'loan_id': loan_id.id,
                'client_id': loan_id.client_id.id,
                'date': installment_date,
                'opening_balance': remaining_balance,
                'amount': principal,
                'interest': interest,
                'closing_balance': closing_balance,
                'total_amount': float("{:.2f}".format(total_amount)),
                'expected_interest': interest,
                'expected_principal': principal,
                'expected_total_amount': float("{:.2f}".format(total_amount)),
                'state': 'unpaid',
                'interest_account_id': interest_account_id,
                'installment_account_id': installment_account_id,
                'loan_payment_journal_id': loan_payment_journal_id,
                'currency_id': loan_id.currency_id.id,
                'is_last_line': is_last
            })
            
            remaining_balance = closing_balance
            if remaining_balance <= 0:
                break

        # Update loan term
        loan_id.write({'loan_term': len(paid_installments) + self.months})