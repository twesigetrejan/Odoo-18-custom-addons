from odoo import models, fields, api, _

class sacco_loan_proof(models.Model):
    _name = "sacco.loan.proof"
    _description = "Loan Proof"
    
    name = fields.Char('Name', required=True, copy=False)
    is_required= fields.Boolean('Required')
    description = fields.Text(string='Description', help='Detailed description of the savings product', default="")
