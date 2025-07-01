from odoo import http
from odoo.http import request, Response
from werkzeug.exceptions import BadRequest
import json
import logging

_logger = logging.getLogger(__name__)

class LoansProductController(http.Controller):
    @http.route('/api/v1/loans_products', type='http', auth='custom_auth', methods=['GET', 'OPTIONS'], csrf=False)
    def get_loans_products_v1(self, **kwargs):
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
            # Fetch all loan products
            products = request.env['sacco.loan.type'].sudo().search([])

            # Format the response data using _prepare_product_data
            product_data = []
            for product in products:
                product_info = self._prepare_product_data(product)
                product_data.append(product_info)

            # Success response
            response_data = {
                'status': 'success',
                'message': 'Loan products retrieved successfully',
                'data': product_data,
                'count': len(product_data)
            }
            return self._json_response(response_data)

        except Exception as e:
            _logger.exception(f"Unexpected error in /api/v1/loans_products: {str(e)}")
            return self._json_response({
                'status': 'error',
                'message': 'An unexpected error occurred'
            }, status=500)

    def _prepare_product_data(self, product):
        """Prepare loan product data for API submission"""
        # Get the loan proof names from proof_ids
        loan_proofs = [proof.name for proof in product.proof_ids] if product.proof_ids else []
        
        return {
            "productType": "Loan",
            "productName": product.name,
            "productDescription": product.description or "",
            "currency": product.currency_id.name,
            "interestRate": product.rate if product.is_interest_apply else 0.0,
            "interestCalculationPeriod": "monthly",
            "interestCalculationMethod": product.interest_mode or "None",
            "productCode": product.product_code or "",
            "loan_attachment": loan_proofs
        }

    def _json_response(self, data, status=200):
        """Helper method to create JSON responses with CORS headers"""
        headers = {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET',
            'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-AccountId',
        }
        return Response(json.dumps(data), status=status, headers=headers)