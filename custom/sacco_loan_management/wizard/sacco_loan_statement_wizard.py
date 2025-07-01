from odoo import api, fields, models, _
from datetime import date
from dateutil.relativedelta import relativedelta
import logging
import time
import random
import binascii

_logger = logging.getLogger(__name__)

class LoanStatementWizard(models.TransientModel):
    _name = 'sacco.loan.statement'
    _description = 'Loan Statement Wizard'

    loan_id = fields.Many2one('sacco.loan.loan', string='Loan', required=True, domain="[('id', 'in', available_loan_ids)]")
    start_date = fields.Date(string='Start Date', related='loan_id.disbursement_date', readonly=True)
    end_date = fields.Date(string='End Date', default=fields.Date.today(), store=True)
    member_id = fields.Many2one('res.partner', string='Member', domain=[('is_sacco_member', '=', 'True')], required=True)
    product_id = fields.Many2one('sacco.loan.type', string='Product', required=True, domain="[('id', 'in', available_product_ids)]")
    request_date = fields.Date(string='Request Date', default=fields.Date.today())
    statement_data = fields.Binary(string="Statement PDF", attachment=True)
    statement_filename = fields.Char(string="Statement Filename")
    available_product_ids = fields.Many2many('sacco.loan.type', 
                                           compute='_compute_available_products')
    available_loan_ids = fields.Many2many(
            'sacco.loan.loan',
            string='Available Loans',
            compute='_compute_available_loans'
        )
 
    @api.depends('member_id')
    def _compute_available_products(self):
        """Compute available loan products based on member's loans"""
        for record in self:
            if record.member_id:
                # Get all loans for the member
                loans = self.env['sacco.loan.loan'].search([
                    ('client_id', '=', record.member_id.id),
                    ('state', 'in', ['open', 'close'])
                ])
                # Get unique product IDs from those loans
                record.available_product_ids = loans.mapped('loan_type_id').ids
            else:
                record.available_product_ids = []
 
    @api.depends('product_id')
    def _compute_available_loans(self):
        """Compute available savings products based on member's loans"""
        for record in self:
            if record.member_id and record.product_id:
                # Get all loans for the member
                loans = self.env['sacco.loan.loan'].search([
                    ('client_id', '=', record.member_id.id),
                    ('loan_type_id', '=', record.product_id.id),
                    ('state', 'in', ['open', 'close'])
                ])
                record.available_loan_ids = loans.ids
            else:
                record.available_loan_ids = []
                
    @api.onchange('member_id')
    def _onchange_member_id(self):
        """Clear product and loan selection when member changes"""
        self.product_id = False
        self.loan_id = False
      
    @api.depends('loan_id')
    def _compute_default_end_date(self):
        for record in self:
            if record.loan_id:
                # Find the last installment date for this loan
                last_installment = self.env['sacco.loan.installment'].search([
                    ('loan_id', '=', record.loan_id.id)
                ], order='date desc', limit=1)
                
                record.end_date = last_installment.date if last_installment else fields.Date.today()
            else:
                record.end_date = fields.Date.today()

    def generate_statement(self):
        self.ensure_one()
        
        # Generate detailed loan statement using the loan model's method
        statement_data = self.loan_id.generate_loan_statement(
            start_date=self.start_date,
            end_date=self.end_date
        )
        
        data = {
            'loan_id': self.loan_id.id,
            'member_id': self.member_id.member_id,
            'member_name': self.loan_id.client_id.name,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'request_date': self.request_date,
            'currency': self.loan_id.currency_id.name,
            'statement_data': statement_data,
        }
        
        return self.env.ref('sacco_loan_management.action_report_loan_statement').report_action(self, data=data)
    
    def action_post_statement(self):
        """Action to post/update loan statement to external system"""
        self.ensure_one()
        
        if not self.loan_id:
            return self._show_notification(
                'Error',
                'Please select a loan to generate statement',
                'danger'
            )

        if not self.start_date or not self.end_date:
            return self._show_notification(
                'Error',
                'Statement date range is required',
                'danger'
            )

        try:
            result = self.loan_id.post_or_update_statement(
                start_date=self.start_date,
                end_date=self.end_date
            )
            return result  # Return the notification from post_or_update_statement
        except Exception as e:
            _logger.error(f"Error posting statement for loan {self.loan_id.name}: {str(e)}")
            return self._show_notification(
                'Error',
                f'Failed to post statement: {str(e)}',
                'danger'
            )

    def _show_notification(self, title, message, type='info'):
        """Helper method to show notifications"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'sticky': True,
                'type': type,
            }
        }

class LoanStatementReport(models.AbstractModel):
    _name = 'report.sacco_loan_management.report_loan_statement'
    _description = 'Loan Statement Report'
    
    @api.model
    def _get_report_values(self, docids, data=None):
        if not data:
            return {}
        
        loan = self.env['sacco.loan.loan'].browse(data['loan_id'])
        
        # Get statement data directly from the generate_loan_statement method
        if 'statement_data' in data:
            statement_data = data['statement_data']
        else:
            # Generate the statement data if not already provided
            statement_data = loan.generate_loan_statement(
                start_date=data['start_date'],
                end_date=data['end_date']
            )
        
        return {
            'doc_ids': docids,
            'docs': self.env['sacco.loan.statement'].browse(docids),
            'member_id': data['member_id'],
            'member_name': data['member_name'],
            'loan_id': loan.name,
            'currency': data['currency'],
            'start_date': data['start_date'],
            'end_date': data['end_date'],
            'request_date': data['request_date'],
            'loan_details': statement_data['loan_details'],
            'transactions': statement_data['transactions'],
            'summary': statement_data['summary'],
            'amortization_schedule': statement_data['amortization_schedule'],
        }

