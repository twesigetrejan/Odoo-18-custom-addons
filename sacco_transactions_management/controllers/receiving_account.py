from odoo import http
from odoo.http import request, Response
from werkzeug.exceptions import BadRequest
import json
import logging

_logger = logging.getLogger(__name__)

class ReceivingAccountController(http.Controller):
    @http.route('/api/v1/receiving_accounts', type='http', auth='custom_auth', methods=['GET', 'OPTIONS'], csrf=False)
    def get_receiving_accounts(self, **kwargs):
        # Handle preflight OPTIONS request
        if request.httprequest.method == 'OPTIONS':
            headers = {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET',
                'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-AccountId',
                'Access-Control-Max-Age': '86400',  # 24 hours cache for preflight requests
            }
            return Response(status=200, headers=headers)

        try:
            # Fetch all receiving accounts
            accounts = request.env['sacco.receiving.account'].sudo().search([('status', '=', 'active')])

            # Format the response data 
            account_data = []
            for account in accounts:
                account_info = {
                    'account_type': account.account_type,
                    'name': account.name,
                    'bank_name': account.bank_name or '',
                    'branch': account.branch or '',
                    'mobile_money_number': account.mobile_money_number or '',
                    'account_number': account.account_number or '',
                    'status': account.status,
                    'default': account.default
                }
                account_data.append(account_info)

            # Success response
            response_data = {
                'status': 'success',
                'message': 'Receiving accounts retrieved successfully',
                'data': account_data,
                'count': len(account_data)
            }
            return self._json_response(response_data)

        except Exception as e:
            _logger.exception(f"Unexpected error in /api/receiving_accounts: {str(e)}")
            return self._json_response({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }, status=500)

    def _json_response(self, data, status=200):
        """Helper method to create JSON responses with CORS headers"""
        headers = {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET',
            'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-AccountId',
        }
        return Response(json.dumps(data), status=status, headers=headers)