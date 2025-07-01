# -*- coding: utf-8 -*-
from odoo import models, fields, api

class report_customer_loan(models.AbstractModel): 
    _name = 'report.sacco_loan_management.report_print_loan_template'
    _description = "Loan Report"
            
            
    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['sacco.loan.loan'].browse(docids)
        return {
            'doc_ids': docs.ids,
            'doc_model': 'sacco.loan.loan',
            'docs': docs,
        }