from odoo import http
from odoo.http import request, Response
from datetime import datetime
import json
import logging

_logger = logging.getLogger(__name__)

class GeneralStatementController(http.Controller):
    @http.route('/api/general_statement', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def get_general_statement(self, **kwargs):
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
            product = body.get('product')

            # Validate required parameters and enforce product as "General"
            if not all([member_id, start_date, end_date, product]):
                return self._json_response({'error': 'Missing required parameters'}, status=400)
            if product != "General":
                return self._json_response({'error': 'Product must be "General" for this endpoint'}, status=400)

            # Fetch member by member_id
            member = request.env['res.partner'].sudo().search([
                ('member_id', '=', member_id),
                ('is_sacco_member', '=', True)
            ], limit=1)

            if not member:
                return self._json_response({'error': f'No member found with member_id {member_id}'}, status=404)

            # Prepare options for the MemberLedgerReportHandler
            options = {
                'partner_id': member.id,
                'date': {
                    'date_from': start_date.isoformat(),
                    'date_to': end_date.isoformat(),
                    'mode': 'range',
                },
                'member_id': member.id,  # Used in forced_domain
            }

            # Instantiate the report handler and generate statement data
            report_handler = request.env['member.ledger.report.handler'].sudo()
            report_data = report_handler.action_generate_member_statement(options)

            # Extract the statement data from the report action (since it returns an action, we simulate the data extraction)
            statement_data = report_data.get('data', {}) if isinstance(report_data, dict) else {}

            if not statement_data.get('lines'):
                return self._json_response({
                    'memberId': member_id,
                    'memberName': member.name,
                    'startDate': start_date.isoformat(),
                    'endDate': end_date.isoformat(),
                    'requestDate': datetime.now().date().isoformat(),
                    'product': "General",
                    'totals': {
                        'savings': 0.0,
                        'savings_interest': 0.0,
                        'loan': 0.0,
                        'loan_interest': 0.0,
                        'shares': 0.0,
                        'share_number': 0.0,
                    },
                    'transactions': []
                })

            # Format transactions for the API response
            formatted_transactions = [
                {
                    'date': line['date'].isoformat(),
                    'savings': float(line['savings'] or 0.0),
                    'savings_interest': float(line['savings_interest'] or 0.0),
                    'loan': float(line['loan'] or 0.0),
                    'loan_interest': float(line['loan_interest'] or 0.0),
                    'shares': float(line['shares'] or 0.0),
                    'share_number': float(line['share_number'] or 0.0),
                    'description': line['description'],
                } for line in statement_data.get('lines', [])
            ]

            # Build the response data
            response_data = {
                'memberId': member_id,
                'memberName': member.name,
                'startDate': start_date.isoformat(),
                'endDate': end_date.isoformat(),
                'requestDate': datetime.now().date().isoformat(),
                'product': "General",
                'totals': {
                    'savings': float(statement_data['totals']['savings']),
                    'savings_interest': float(statement_data['totals']['savings_interest']),
                    'loan': float(statement_data['totals']['loan']),
                    'loan_interest': float(statement_data['totals']['loan_interest']),
                    'shares': float(statement_data['totals']['shares']),
                    'share_number': float(statement_data['totals']['share_number']),
                },
                'transactions': formatted_transactions
            }

            return self._json_response(response_data)

        except json.JSONDecodeError:
            return self._json_response({'error': 'Invalid JSON in request body'}, status=400)
        except ValueError as ve:
            return self._json_response({'error': str(ve)}, status=400)
        except Exception as e:
            _logger.exception(f"Unexpected error in /api/general_statement: {str(e)}")
            return self._json_response({'error': 'An unexpected error occurred'}, status=500)

    def _json_response(self, data, status=200):
        """Helper method to create JSON responses with CORS headers"""
        headers = {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-AccountId',
        }
        return Response(json.dumps(data), status=status, headers=headers)