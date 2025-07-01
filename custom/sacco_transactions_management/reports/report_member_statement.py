from odoo import api, models
from odoo.exceptions import ValidationError

class MemberStatementReport(models.AbstractModel):
    _name = 'report.sacco_transactions_management.member_statement_report'
    _description = 'Member Statement Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        if not data:
            return {
                'doc_ids': docids,
                'doc_model': 'general.member.statement.wizard',
                'docs': [],
            }

        # Find the partner based on member_id (assuming it's a partner ID or ref)
        member_id = data.get('member_id', '')
        if isinstance(member_id, int):  # Check if member_id is already an integer
            partner = self.env['res.partner'].browse(member_id)
            member_id = partner.member_id
            if not partner.exists():
                raise ValidationError(f"No partner found with ID {member_id}")
        elif str(member_id).isdigit():  # Check if member_id is a string that contains only digits
            partner = self.env['res.partner'].browse(int(member_id))
            member_id = partner.member_id
            if not partner.exists():
                raise ValidationError(f"No partner found with ID {member_id}")
        else:  # If member_id is a ref (string identifier)
            partner = self.env['res.partner'].search([('ref', '=', member_id)], limit=1)
            member_id = partner.member_id
            if not partner:
                raise ValidationError(f"No partner found with ref {member_id}")

        # Create a transient record with a valid partner_id
        wizard = self.env['general.member.statement.wizard'].create({
            'partner_id': partner.id,
            'date_from': data.get('date_from'),
            'date_to': data.get('date_to'),
        })

        docs = wizard
        request_date = data.get('request_date', '')
        filename = f"Member_Statement_{member_id}_{request_date.replace('/', '-')}.pdf"

        return {
            'doc_ids': docids,
            'doc_model': 'general.member.statement.wizard',
            'docs': docs,
            'data': data,
            'member_id': member_id,
            'member_name': data.get('member_name', ''),
            'date_from': data.get('date_from', ''),
            'date_to': data.get('date_to', ''),
            'request_date': request_date,
            'lines': data.get('lines', []),
            'totals': data.get('totals', {}),
            'report_filename': filename,
        }