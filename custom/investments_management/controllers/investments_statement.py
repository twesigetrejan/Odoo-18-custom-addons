from odoo import http
from odoo.http import request, Response
from datetime import datetime
import json
import logging

_logger = logging.getLogger(__name__)

class InvestmentsStatementController(http.Controller):
    @http.route('/api/investments_statement', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def get_member_investment_statement(self, **kwargs):
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
            # Extract data from the request body
            body = json.loads(request.httprequest.data.decode('utf-8'))
            
            # Extract parameters from the body
            member_id = body.get('memberId')
            start_date = datetime.strptime(body.get('startDate', ''), '%Y-%m-%d').date() if body.get('startDate') else None
            end_date = datetime.strptime(body.get('endDate', ''), '%Y-%m-%d').date() if body.get('endDate') else None
            product_name = body.get('product')
            currency_code = body.get('currency')

            # Validate required parameters
            if not all([member_id, start_date, end_date, product_name, currency_code]):
                return self._json_response({'error': 'Missing required parameters'}, status=400)

            # Find the member
            member = request.env['res.partner'].sudo().search([
                ('member_id', '=', member_id),
                ('is_sacco_member', '=', True)
            ], limit=1)
            
            if not member:
                return self._json_response({'error': 'Member not found'}, status=404)

            # Find the product
            product = request.env['sacco.investments.product'].sudo().search([
                ('name', '=', product_name)
            ], limit=1)
            
            if not product:
                return self._json_response({'error': 'Product not found'}, status=404)
            
            # Find the currency
            currency = request.env['res.currency'].sudo().search([
                ('name', '=', currency_code)
            ], limit=1)
            
            if not currency:
                return self._json_response({'error': f'Currency {currency_code} not found'}, status=404)

            # Find the investment account
            investment_account = request.env['sacco.investments.account'].sudo().search([
                ('member_id', '=', member.id),
                ('product_id', '=', product.id),
                ('currency_id', '=', currency.id),
                ('state', '!=', 'draft')
            ], limit=1)
            
            if not investment_account:
                return self._json_response(
                    {'error': 'No active investment account found for this member and product'}, 
                    status=404
                )
            
            investment_account.action_refresh_journal_lines()

            # Get transactions
            transactions = request.env['sacco.investment.account.journal.line'].sudo().search([
                ('investment_account_id', '=', investment_account.id),
                ('date', '>=', start_date),
                ('date', '<=', end_date)
            ], order='date asc, id asc')

            # Format transactions
            formatted_transactions = []
            for transaction in transactions:
                selection = transaction._fields['type'].selection
                if callable(selection):
                    selection = selection(transaction)

                formatted_transactions.append({
                    "date": transaction.date.isoformat() if transaction.date else None,
                    "type": dict(selection).get(transaction.type, transaction.type),
                    "opening_cash_balance": float(transaction.opening_cash_balance),
                    "opening_investment_balance": float(transaction.opening_investment_balance),
                    "amount": float(transaction.amount),
                    "closing_cash_balance": float(transaction.closing_cash_balance),
                    "closing_investment_balance": float(transaction.closing_investment_balance)
                })

            # Prepare the statement data
            statement_data = {
                "memberId": member_id,
                "memberName": member.name,
                "startDate": start_date.isoformat() if start_date else None,
                "endDate": end_date.isoformat() if end_date else None,
                "requestDate": datetime.now().date().isoformat(),
                "product": product_name,
                "currency": currency_code,
                "cashBalance": float(investment_account.cash_balance),
                "investmentBalance": float(investment_account.investment_balance),
                "totalProfit": float(investment_account.total_profit),
                "transactions": formatted_transactions,
            }

            return self._json_response(statement_data)

        except json.JSONDecodeError:
            return self._json_response({'error': 'Invalid JSON in request body'}, status=400)
        except Exception as e:
            _logger.error(f"Error generating investment statement: {str(e)}")
            return self._json_response({'error': str(e)}, status=500)

    def _json_response(self, data, status=200):
        """Helper method to create JSON responses with CORS headers"""
        headers = {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',  # Allow all origins
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-AccountId',
        }
        
        return Response(
            json.dumps(data),
            status=status,
            headers=headers
        )