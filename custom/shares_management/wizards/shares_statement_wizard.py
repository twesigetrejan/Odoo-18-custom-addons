from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime
import logging 
from odoo.tools.misc import split_every

_logger = logging.getLogger(__name__)

# Setting batch size to process in smaller chunks
BATCH_SIZE = 1000  # This will depend on the available memory and response size

class SharesStatementWizard(models.TransientModel):
    _name = 'sacco.shares.statement.wizard'
    _description = 'Shares Statement Wizard'
    _inherit = ['api.token.mixin']
    
    start_date = fields.Date('Start Date', required=True)
    end_date = fields.Date('End Date', required=True, default=fields.Date.today(), readonly=True)
    request_date = fields.Date('Request Date', default=fields.Date.today(), readonly=True)
    partner_id = fields.Many2one('res.partner', string='Member', domain=[('is_sacco_member', '=', 'True')], required=True)
    product_id = fields.Many2one('sacco.shares.product', string='Product', required=True, domain="[('id', 'in', available_product_ids)]")
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('processing', 'Processing'),
        ('done', 'Done'),
        ('error', 'Error')
    ], default='draft', string='Status')
    available_product_ids = fields.Many2many('sacco.shares.product', 
                                           compute='_compute_available_products')
    
    @api.depends('partner_id')
    def _compute_available_products(self):
        """Compute available shares products based on member's accounts"""
        for record in self:
            if record.partner_id:
                # Get all active shares accounts for the member
                shares_accounts = self.env['sacco.shares.account'].search([
                    ('member_id', '=', record.partner_id.id),
                    ('state', '!=', 'draft')
                ])
                # Get unique product IDs from those accounts
                record.available_product_ids = shares_accounts.mapped('product_id').ids
            else:
                record.available_product_ids = []
                
    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """Clear product selection when member changes"""
        self.product_id = False
    
    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Set currency when product changes"""
        if self.product_id:
            self.currency_id = self.product_id.currency_id.id
        else:
            self.currency_id = self.env.company.currency_id.id


    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for record in self:
            if record.start_date > record.end_date:
                raise ValidationError(_("Start date must be before end date"))
            
    def action_download_statement(self):
        self.ensure_one()
        self.state = 'processing'
        
        try:
            # Use read() instead of browse() for better performance
            shares_account_ids = self.env['sacco.shares.account'].search([
                ('member_id', '=', self.partner_id.id),
                ('product_id', '=', self.product_id.id),
                ('currency_id', '=', self.currency_id.id),
                ('state', '!=', 'draft'),
            ]).ids

            if not shares_account_ids:
                raise ValidationError(_("No shares accounts found for this member"))

            # Prepare report data with optimized queries
            statement_data = self._prepare_statement_data_optimized(shares_account_ids)
            
            # Prepare report context
            data = {
                'member_id': self.partner_id.member_id,
                'member_name': self.partner_id.name,
                'start_date': self.start_date,
                'end_date': self.end_date,
                'request_date': self.request_date,
                'currency': self.currency_id.name,
                'statement_data': statement_data,
            }
            
            self.state = 'done'
            return self.env.ref('shares_management.action_report_shares_statement').with_context(
                skip_report_rendering=True  # Skip immediate rendering
            ).report_action(self, data=data)

        except Exception as e:
            self.state = 'error'
            _logger.error("Error generating statement: %s", str(e))
            raise

    def _prepare_statement_data_optimized(self, account_ids):
        """Optimized method to prepare statement data with efficient queries."""
        statement_data = []
        
        # Fetch all required data in a single query
        accounts = self.env['sacco.shares.account'].browse(account_ids)
        
        for account in accounts:
            lines_data = []
            # Process transactions in chunks
            for lines_chunk in self._get_account_lines_chunked(account.id):
                formatted_chunk = self._format_account_lines_bulk(lines_chunk)
                lines_data.extend(formatted_chunk)
            
            if lines_data:
                statement_data.append({
                    'product': account.product_id.name,
                    'total_shares': account.share_number,
                    'lines': lines_data
                })
        
        return statement_data

    def _get_account_lines_chunked(self, account_id):
        """Fetch and yield account lines in chunks for memory efficiency."""
        domain = [
            ('shares_account_id', '=', account_id),
            ('date', '>=', self.start_date),
            ('date', '<=', self.end_date),
        ]
        
        # Get total count
        total_count = self.env['sacco.shares.journal.account.line'].search_count(domain)
        
        # Process in chunks
        for offset in range(0, total_count, BATCH_SIZE):
            lines = self.env['sacco.shares.journal.account.line'].search(
                domain,
                limit=BATCH_SIZE,
                offset=offset,
                order="date asc, id asc"
            )
            if not lines:
                break
            yield lines

    def _format_account_lines_bulk(self, lines):
        """Bulk format account lines for better performance."""
        formatted_lines = []
        # Get selection field properly handling both function and static selection
        selection = self.env['sacco.shares.journal.account.line']._fields['transaction_type'].selection
        if callable(selection):
            selection = selection(self.env['sacco.shares.journal.account.line'])
        selection_dict = dict(selection)
        
        running_shares_total = 0.0
        
        for line in lines:
            # Get the number of shares and amount for this transaction
            number_of_shares = float(line.number_of_shares or 0.0)
            amount = float(line.total_amount or 0.0)
            
            # Update running total of shares
            running_shares_total += number_of_shares

            formatted_lines.append({
                'date': fields.Date.to_string(line.date) if line.date else False,
                'description': 'Shares Transaction', # previously line.name
                'type': selection_dict.get(line.transaction_type, line.transaction_type),
                'number_of_shares': number_of_shares,
                'amount': amount,
                'running_shares_total': running_shares_total
            })
        
        return formatted_lines

    def _chunk_data_for_report(self, data, chunk_size=1000):
        """Split report data into manageable chunks."""
        if not data.get('statement_data'):
            return [data]
        
        chunked_data = []
        for statement in data['statement_data']:
            if 'lines' in statement:
                for lines_chunk in split_every(chunk_size, statement['lines']):
                    chunk = dict(data)
                    chunk['statement_data'] = [{
                        'product': statement['product'],
                        'total_shares': statement['total_shares'],
                        'lines': lines_chunk
                    }]
                    chunked_data.append(chunk)
        
        return chunked_data or [data]

    def _show_notification(self, title, message, type='info'):
        _logger.info(f"Showing notification - Title: {title}, Message: {message}, Type: {type}")
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