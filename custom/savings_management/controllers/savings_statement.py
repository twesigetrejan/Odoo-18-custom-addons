from odoo import http
from odoo.http import request, Response
from datetime import datetime
import json
import logging

_logger = logging.getLogger(__name__)

class SavingsStatementController(http.Controller):
    @http.route('/api/savings_statement', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
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

            # Fetch member, product, and currency in one call to minimize database hits
            member = request.env['res.partner'].sudo().search([
                ('member_id', '=', member_id),
                ('is_sacco_member', '=', True)
            ], limit=1)

            product = request.env['sacco.savings.product'].sudo().search([('name', '=', product_name)], limit=1)
            currency = request.env['res.currency'].sudo().search([('name', '=', currency_code)], limit=1)

            if not member or not product or not currency:
                return self._json_response({'error': 'Invalid member, product, or currency information'}, status=404)

            # Fetch the active savings account
            savings_account = request.env['sacco.savings.account'].sudo().search([
                ('member_id', '=', member.id),
                ('product_id', '=', product.id),
                ('currency_id', '=', currency.id),
                ('state', '!=', 'draft')
            ], limit=1)

            if not savings_account:
                return self._json_response({'error': 'No active savings account found for the given member and product'}, status=404)

            # Fetch transactions using sacco.journal.account.line in batches
            BATCH_SIZE = 1000  # Consistent with wizard
            domain = [
                ('savings_account_id', '=', savings_account.id),
                ('date', '>=', start_date),
                ('date', '<=', end_date),
            ]
            total_count = request.env['sacco.journal.account.line'].sudo().search_count(domain)
            transactions = []

            # Process transactions in chunks for efficiency
            for offset in range(0, total_count, BATCH_SIZE):
                batch = request.env['sacco.journal.account.line'].sudo().search_read(
                    domain=domain,
                    fields=['date', 'type', 'opening_balance', 'amount', 'closing_balance'],
                    limit=BATCH_SIZE,
                    offset=offset,
                    order='date asc, id asc'
                )
                if not batch:
                    break
                transactions.extend(batch)

            # Handle the selection field for the `type`
            selection = request.env['sacco.journal.account.line']._fields['type'].selection
            if callable(selection):
                selection = selection(request.env['sacco.journal.account.line'])
            selection_dict = dict(selection) if selection else {}

            # Format transactions using a generator for memory efficiency
            formatted_transactions = (
                {
                    "date": trans['date'].isoformat() if trans['date'] else None,
                    "type": selection_dict.get(trans['type'], trans['type']),
                    "opening_balance": float(trans['opening_balance'] or 0.0),
                    "credit": float(trans['amount'] or 0.0) if trans['type'] != 'withdrawal' else 0.0,
                    "debit": float(trans['amount'] or 0.0) if trans['type'] == 'withdrawal' else 0.0,
                    "closing_balance": float(trans['closing_balance'] or 0.0),
                }
                for trans in transactions
            )

            # Build response data
            statement_data = {
                "memberId": member_id,
                "memberName": member.name,
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "requestDate": datetime.now().date().isoformat(),
                "currency": currency.name,
                "product": product_name,
                "currentBalance": float(savings_account.balance),
                "transactions": list(formatted_transactions)  # Convert generator to list for response
            }

            return self._json_response(statement_data)

        except json.JSONDecodeError:
            return self._json_response({'error': 'Invalid JSON in request body'}, status=400)
        except ValueError as ve:
            return self._json_response({'error': str(ve)}, status=400)
        except Exception as e:
            _logger.exception(f"Unexpected error: {str(e)}")
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
    
    @http.route('/api/v1/savings_statement', type='http', auth='custom_auth', methods=['POST', 'OPTIONS'], csrf=False)
    def get_member_statement_v1(self, **kwargs):
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

            # Fetch member, product, and currency in one call to minimize database hits
            member = request.env['res.partner'].sudo().search([
                ('member_id', '=', member_id),
                ('is_sacco_member', '=', True)
            ], limit=1)

            product = request.env['sacco.savings.product'].sudo().search([('name', '=', product_name)], limit=1)
            currency = request.env['res.currency'].sudo().search([('name', '=', currency_code)], limit=1)

            if not member or not product or not currency:
                return self._json_response({'error': 'Invalid member, product, or currency information'}, status=404)

            # Fetch the active savings account
            savings_account = request.env['sacco.savings.account'].sudo().search([
                ('member_id', '=', member.id),
                ('product_id', '=', product.id),
                ('currency_id', '=', currency.id),
                ('state', '!=', 'draft')
            ], limit=1)

            if not savings_account:
                return self._json_response({'error': 'No active savings account found for the given member and product'}, status=404)

            # Fetch transactions using sacco.journal.account.line in batches
            BATCH_SIZE = 1000  # Consistent with wizard
            domain = [
                ('savings_account_id', '=', savings_account.id),
                ('date', '>=', start_date),
                ('date', '<=', end_date),
            ]
            total_count = request.env['sacco.journal.account.line'].sudo().search_count(domain)
            transactions = []

            # Process transactions in chunks for efficiency
            for offset in range(0, total_count, BATCH_SIZE):
                batch = request.env['sacco.journal.account.line'].sudo().search_read(
                    domain=domain,
                    fields=['date', 'type', 'opening_balance', 'amount', 'closing_balance'],
                    limit=BATCH_SIZE,
                    offset=offset,
                    order='date asc, id asc'
                )
                if not batch:
                    break
                transactions.extend(batch)

            # Handle the selection field for the `type`
            selection = request.env['sacco.journal.account.line']._fields['type'].selection
            if callable(selection):
                selection = selection(request.env['sacco.journal.account.line'])
            selection_dict = dict(selection) if selection else {}

            # Format transactions using a generator for memory efficiency
            formatted_transactions = (
                {
                    "date": trans['date'].isoformat() if trans['date'] else None,
                    "type": selection_dict.get(trans['type'], trans['type']),
                    "opening_balance": float(trans['opening_balance'] or 0.0),
                    "credit": float(trans['amount'] or 0.0) if trans['type'] != 'withdrawal' else 0.0,
                    "debit": float(trans['amount'] or 0.0) if trans['type'] == 'withdrawal' else 0.0,
                    "closing_balance": float(trans['closing_balance'] or 0.0),
                }
                for trans in transactions
            )

            # Build response data
            statement_data = {
                "memberId": member_id,
                "memberName": member.name,
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "requestDate": datetime.now().date().isoformat(),
                "currency": currency.name,
                "product": product_name,
                "currentBalance": float(savings_account.balance),
                "transactions": list(formatted_transactions)  # Convert generator to list for response
            }

            return self._json_response(statement_data)

        except json.JSONDecodeError:
            return self._json_response({'error': 'Invalid JSON in request body'}, status=400)
        except ValueError as ve:
            return self._json_response({'error': str(ve)}, status=400)
        except Exception as e:
            _logger.exception(f"Unexpected error: {str(e)}")
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