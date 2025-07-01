from odoo import fields, api, models

class SharesStatementReport(models.AbstractModel):
    _name = 'report.shares_management.report_shares_statement'
    _description = 'Shares Statement Report'
    
    @api.model
    def _get_report_values(self, docids, data=None):
        if not data:
            return {}
            
        docs = []
        if docids:
            wizard = self.env['sacco.shares.statement.wizard'].browse(docids)
            if wizard:
                docs = wizard

        return {
            'doc_ids': docids,
            'doc_model': 'sacco.shares.statement.wizard',
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