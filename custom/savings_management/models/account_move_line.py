# savings_management/models/account_move_line.py
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'
    
    @api.constrains('account_id', 'partner_id')
    def _check_savings_account_requirements(self):
        if self.env.context.get('install_mode') or self._context.get('module'):
            return
            
        for line in self:
            if line.move_id.state != 'posted':
                continue
                
            if line.account_id.requires_member and line.account_id.account_product_type == 'savings':
                if not line.partner_id:
                    raise ValidationError(_("Account %s requires a member to be selected.") % line.account_id.name)
                if not line.member_id:
                    raise ValidationError(_("Account %s requires a member ID to be set.") % line.account_id.name)