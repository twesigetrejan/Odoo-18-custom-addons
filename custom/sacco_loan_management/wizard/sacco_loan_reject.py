from odoo import api, fields, models, _

class sacco_loan_reject(models.TransientModel):
    _name = "sacco.loan.reject"
    _description = "Loan Reject"
    
    reason = fields.Text('Reason', required=True)
    
    
    def action_reject_loan(self):
        active_ids = self._context.get('active_ids')
        loan_ids = self.env['sacco.loan.loan'].browse(active_ids)
        ir_model_data = self.env['ir.model.data']
        mtp = self.env['mail.template']
        
        for loan in loan_ids:
            loan.reject_reason = self.reason
            loan.state = 'reject'
            loan.reject_user_id = self.env.user.id
            
            # Send email notification
            template_id = ir_model_data._xmlid_lookup('sacco_loan_management.sacco_loan_loan_request_reject')[1]
            template_id = mtp.browse(template_id)
            template_id.send_mail(loan.id, force_send=True)
            
            # Upload loan status
            loan.upload_loan_status('Rejected', 'reject', self.reason)

            # Reset security status to 'pending_verification' for all securities
            if loan.security_ids:
                loan.security_ids.write({'security_status': 'pending_verification'})
            
            # Send rejection notification
            message = f"""Hello <b>{loan.client_id.name}</b>,<br>We regret to inform you that your loan application has been rejected after careful review.
            <br>If you believe this decision was made in error, you may contact our support team for clarification or to discuss other available options.
            <br>Thank you for considering our services. We look forward to assisting you in the future.<br>Best regards
            """
            notification = loan._prepare_notification("Loan Application Rejected", message)
            loan._send_notification(notification)
