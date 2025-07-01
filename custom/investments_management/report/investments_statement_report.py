from odoo import fields, api, models

class InvestmentsStatementReport(models.AbstractModel):
    _name = 'report.investments_management.report_investments_statement'
    _description = 'Investments Statement Report'
    
    @api.model
    def _get_report_values(self, docids, data=None):
        if not data:
            return {}
            
        docs = []
        if docids:
            wizard = self.env['sacco.investments.statement.wizard'].browse(docids)
            if wizard:
                docs = wizard

        return {
            'doc_ids': docids,
            'doc_model': 'sacco.investments.statement.wizard',
            'docs': docs,
            'data': data,
            'member_id': data.get('member_id', ''),
            'member_name': data.get('member_name', ''),
            'start_date': data.get('start_date', ''),
            'end_date': data.get('end_date', ''),
            'request_date': data.get('request_date', ''),
            'currency': data.get('currency', ''),
            'statement_data': data.get('statement_data', []),
        }