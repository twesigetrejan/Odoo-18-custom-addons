from odoo import models, fields, api, _

class LoanPaymentSync(models.Model):
    _name = 'loan.payment.sync'
    _description = 'Loan Payments Sync'
    
    def sync_loan_payments(self):
        config = self.env['res.config.settings'].create({})
        return config.action_sync_loan_payments()