from odoo import http
from odoo.http import request, Response
from datetime import datetime
import json
import logging
from odoo import fields

_logger = logging.getLogger(__name__)

class SharesStatementController(http.Controller):
    @http.route('/api/v1/shares_statement', type='http', auth='custom_auth', methods=['POST', 'OPTIONS'], csrf=False)
    def get_member_statement(self, **kwargs):
        # Handle preflight OPTIONS request
        if request.httprequest.method == 'OPTIONS':
            headers = {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'POST',
                'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-AccountId',
                'Access-Control-Max-Age': '86400',  # 24 hours cache for preflight requests
            }
            return Response(status=200, headers=headers)

        try:
            # Parse request body
            body = json.loads(request.httprequest.data.decode('utf-8'))

            # Extract and validate input parameters
            member_id = body.get('memberId')
            start_date = datetime.strptime(body.get('startDate', ''), '%Y-%m-%d').date() if body.get('startDate') else None
            end_date = datetime.strptime(body.get('endDate', ''), '%Y-%m-%d').date() if body.get('endDate') else None
            product_name = body.get('product')
            currency_code = body.get('currency')

            if not all([member_id, start_date, end_date, product_name, currency_code]):
                return self._json_response({'error': 'Missing required parameters'}, status=400)

            if start_date > end_date:
                return self._json_response({'error': 'Start date must be before end date'}, status=400)

            # Fetch member, product, and currency in one call to minimize database hits
            member = request.env['res.partner'].sudo().search([
                ('member_id', '=', member_id),
                ('is_sacco_member', '=', True)
            ], limit=1)

            product = request.env['sacco.shares.product'].sudo().search([('name', '=', product_name)], limit=1)
            currency = request.env['res.currency'].sudo().search([('name', '=', currency_code)], limit=1)

            if not member or not product or not currency:
                return self._json_response({'error': 'Invalid member, product, or currency information'}, status=404)

            # Fetch the active shares account
            shares_account = request.env['sacco.shares.account'].sudo().search([
                ('member_id', '=', member.id),
                ('product_id', '=', product.id),
                ('currency_id', '=', currency.id),
                ('state', '!=', 'draft')
            ], limit=1)

            if not shares_account:
                return self._json_response({'error': 'No active shares account found for the given member and product'}, status=404)

            # Fetch transactions in chunks
            BATCH_SIZE = 1000
            domain = [
                ('shares_account_id', '=', shares_account.id),
                ('date', '>=', start_date),
                ('date', '<=', end_date),
            ]
            total_count = request.env['sacco.shares.journal.account.line'].sudo().search_count(domain)
            transactions = []

            # Process transactions in chunks for efficiency
            for offset in range(0, total_count, BATCH_SIZE):
                batch = request.env['sacco.shares.journal.account.line'].sudo().search(
                    domain=domain,
                    limit=BATCH_SIZE,
                    offset=offset,
                    order='date asc, id asc'
                )
                if not batch:
                    break
                transactions.extend(self._format_account_lines_bulk(batch))

            # Build response data
            statement_data = {
                'memberId': member_id,
                'memberName': member.name,
                'startDate': start_date.isoformat(),
                'endDate': end_date.isoformat(),
                'requestDate': datetime.now().date().isoformat(),
                'currency': currency.name,
                'product': product_name,
                'totalShares': float(shares_account.share_number),
                'transactions': transactions
            }

            return self._json_response({
                'status': 'success',
                'message': 'Shares statement retrieved successfully',
                'data': statement_data
            })

        except json.JSONDecodeError:
            return self._json_response({'error': 'Invalid JSON in request body'}, status=400)
        except ValueError as ve:
            return self._json_response({'error': str(ve)}, status=400)
        except Exception as e:
            _logger.exception(f"Unexpected error in /api/shares_statement: {str(e)}")
            return self._json_response({'error': 'An unexpected error occurred'}, status=500)

    def _format_account_lines_bulk(self, lines):
        """Bulk format account lines for better performance."""
        formatted_lines = []
        selection = self.env['sacco.shares.journal.account.line']._fields['transaction_type'].selection
        if callable(selection):
            selection = selection(self.env['sacco.shares.journal.account.line'])
        selection_dict = dict(selection) if selection else {}

        running_shares_total = 0.0

        for line in lines:
            number_of_shares = float(line.number_of_shares or 0.0)
            amount = float(line.total_amount or 0.0)
            running_shares_total += number_of_shares

            formatted_lines.append({
                'date': fields.Date.to_string(line.date) if line.date else False,
                'description': 'Shares Transaction',
                'type': selection_dict.get(line.transaction_type, line.transaction_type),
                'number_of_shares': number_of_shares,
                'amount': amount,
                'running_shares_total': running_shares_total
            })

        return formatted_lines

    def _json_response(self, data, status=200):
        """Helper method to create JSON responses with CORS headers"""
        headers = {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-AccountId',
        }
        return Response(json.dumps(data), status=status, headers=headers)