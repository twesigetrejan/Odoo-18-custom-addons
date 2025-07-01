from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)

class withdrawal_request_reject(models.TransientModel):
    _name = "sacco.withdrawal.request.reject"
    _description = "Withdrawal Reject"
    
    reason = fields.Text('Reason', required=True)
    
    
    def action_reject_withdrawal_request(self):
        active_ids = self._context.get('active_ids')
        withdrawal_request_ids = self.env['sacco.withdrawal.request'].browse(active_ids)
        ir_model_data = self.env['ir.model.data']
        mtp = self.env['mail.template']
        for withdrawal_request in withdrawal_request_ids:
            withdrawal_request.reject_reason = self.reason
            withdrawal_request.state = 'reject'
            withdrawal_request.upload_withdrawal_request_status('Rejected', 'reject', self.reason) 
            withdrawal_request.reject_user_id = self.env.user.id   
            
            template_id = ir_model_data._xmlid_lookup('savings_management.withdrawal_request_reject_email')[1]
            print ("template_id========",template_id)
            template_id = mtp.browse(template_id)
            template_id.send_mail(withdrawal_request.id, force_send=True) 

            
    
