from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class ResCompany(models.Model):
    _inherit = 'res.company'

    sacco_accronym = fields.Char(string="SACCO Accronym", required=True)