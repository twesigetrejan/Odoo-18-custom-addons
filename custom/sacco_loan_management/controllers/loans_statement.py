from odoo import http
from odoo.http import request, Response
import json
from datetime import datetime, date
from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from odoo.exceptions import ValidationError

class LoanStatementController(http.Controller):
    @http.route('/api/loans_statement', type='http', auth='public', methods=['POST', 'OPTIONS'], csrf=False)
    def get_loan_statement(self, **kwargs):
        # Handle CORS preflight (OPTIONS) request
        if request.httprequest.method == 'OPTIONS':
            headers = {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'POST',
                'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-AccountId',
                'Access-Control-Max-Age': '86400',
            }
            return Response(status=200, headers=headers)

        # Handle POST request
        try:
            # Get data from request body
            data = json.loads(request.httprequest.data.decode('utf-8'))

            # Required fields are 'memberId' and 'loanProduct', 'loanId' is optional
            required_fields = ['memberId', 'loanProduct']
            missing_fields = [field for field in required_fields if field not in data]
            if missing_fields:
                error_response = {
                    'status': 'error',
                    'message': f'Missing required fields: {", ".join(missing_fields)}'
                }
                headers = {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                }
                return Response(json.dumps(error_response), status=400, headers=headers)

            # Extract parameters
            member_id = data.get('memberId')
            loan_product = data.get('loanProduct')
            loan_id = data.get('loanId')  # Optional

            # Use admin user context for unrestricted access
            env = request.env(user=request.env.ref('base.user_admin').id)

            # Search for the loan
            domain = [
                ('client_id.member_id', '=', member_id),
                ('loan_type_id.name', '=', loan_product),
                ('state', 'in', ['open', 'disburse', 'close'])  # Only include active or completed loans
            ]
            if loan_id:
                # If loanId is provided, prioritize it
                domain = [('name', '=', loan_id)]

            loan = env['sacco.loan.loan'].search(domain, limit=1)

            if not loan:
                error_response = {
                    'status': 'error',
                    'message': 'No loan found matching the provided memberId and loanProduct'
                }
                headers = {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                }
                return Response(json.dumps(error_response), status=404, headers=headers)

            # Generate statement using the model's generate_loan_statement method
            start_date = data.get('startDate')
            end_date = data.get('endDate')
            if start_date:
                start_date = parse(start_date).date()
            if end_date:
                end_date = parse(end_date).date()

            statement_raw = loan.generate_loan_statement(start_date=start_date, end_date=end_date)

            # Prepare amortization schedule
            amortization_schedule = [
                {
                    "period": index + 1,
                    "payment": float(installment['total_payment']),
                    "principal": float(installment['principal']),
                    "interest": float(installment['interest']),
                    "balance": float(installment['closing_balance'])
                } for index, installment in enumerate(statement_raw['amortization_schedule'])
            ]

            # Compute amortization summary
            total_payment = sum(installment['total_payment'] for installment in statement_raw['amortization_schedule'])
            total_interest = sum(installment['interest'] for installment in statement_raw['amortization_schedule'])
            monthly_payment = loan.emi_estimate

            amortization_data = {
                "schedule": amortization_schedule,
                "summary": {
                    "monthlyPayment": float(monthly_payment),
                    "totalPayment": float(total_payment),
                    "totalInterest": float(total_interest),
                    "loanAmount": float(loan.loan_amount),
                    "interestRate": float(loan.interest_rate),
                    "loanPeriod": loan.loan_term
                }
            }

            # Format the statement for API response
            statement = {
                'status': 'success',
                'data': {
                    "memberId": loan.client_id.member_id,
                    "memberName": loan.client_id.name,
                    "loanId": loan.name,
                    "startDate": statement_raw['loan_details']['disbursement_date'].isoformat() if statement_raw['loan_details']['disbursement_date'] else None,
                    "endDate": end_date.isoformat() if end_date else date.today().isoformat(),
                    "requestDate": date.today().isoformat(),
                    "product": loan.loan_type_id.name,
                    "productType": "Loans",
                    "loanAmount": float(statement_raw['loan_details']['loan_amount']),
                    "currentBalance": float(statement_raw['summary']['current_principal_balance']),
                    "currency": loan.currency_id.name,
                    "transactions": [
                        {
                            "date": tx['date'].isoformat() if isinstance(tx['date'], date) else tx['date'],
                            "description": tx['type'],
                            "amount": float(tx['amount']),
                            "principal": float(tx['principal']),
                            "interest": float(tx['interest']),
                            "balance": float(tx['balance']),
                        } for tx in statement_raw['transactions']
                    ],
                    "summary": {
                        "totalPaid": float(statement_raw['summary']['total_paid']),
                        "totalPrincipalPaid": float(statement_raw['summary']['total_principal_paid']),
                        "totalInterestPaid": float(statement_raw['summary']['total_interest_paid']),
                        "totalInterestAccrued": float(statement_raw['summary']['total_interest_accrued']),
                        "currentPrincipalBalance": float(statement_raw['summary']['current_principal_balance']),
                        "accruedInterest": float(statement_raw['summary']['accrued_interest'])
                    },
                    "amortization": amortization_data, 
                    "createdBy": loan.client_id.member_id
                }
            }

            # Return JSON response with proper headers
            headers = {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            }
            return Response(json.dumps(statement), status=200, headers=headers)

        except Exception as e:
            error_response = {
                'status': 'error',
                'message': str(e)
            }
            headers = {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            }
            return Response(json.dumps(error_response), status=500, headers=headers)
        
        
    @http.route('/api/v1/loans_statement', type='http', auth='custom_auth', methods=['POST', 'OPTIONS'], csrf=False)
    def get_loan_statement_v1(self, **kwargs):
        # Handle CORS preflight (OPTIONS) request
        if request.httprequest.method == 'OPTIONS':
            headers = {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'POST',
                'Access-Control-Allow-Headers': 'Authorization, Content-Type, X-AccountId',
                'Access-Control-Max-Age': '86400',
            }
            return Response(status=200, headers=headers)

        # Handle POST request
        try:
            # Get data from request body
            data = json.loads(request.httprequest.data.decode('utf-8'))

            # Required fields are 'memberId' and 'loanProduct', 'loanId' is optional
            required_fields = ['memberId', 'loanProduct']
            missing_fields = [field for field in required_fields if field not in data]
            if missing_fields:
                error_response = {
                    'status': 'error',
                    'message': f'Missing required fields: {", ".join(missing_fields)}'
                }
                headers = {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                }
                return Response(json.dumps(error_response), status=400, headers=headers)

            # Extract parameters
            member_id = data.get('memberId')
            loan_product = data.get('loanProduct')
            loan_id = data.get('loanId')  # Optional

            # Use admin user context for unrestricted access
            env = request.env(user=request.env.ref('base.user_admin').id)

            # Search for the loan
            domain = [
                ('client_id.member_id', '=', member_id),
                ('loan_type_id.name', '=', loan_product),
                ('state', 'in', ['open', 'disburse', 'close'])  # Only include active or completed loans
            ]
            if loan_id:
                # If loanId is provided, prioritize it
                domain = [('name', '=', loan_id)]

            loan = env['sacco.loan.loan'].search(domain, limit=1)

            if not loan:
                error_response = {
                    'status': 'error',
                    'message': 'No loan found matching the provided memberId and loanProduct'
                }
                headers = {
                    'Content-Type': 'application/json',
                    'Access-Control-Allow-Origin': '*'
                }
                return Response(json.dumps(error_response), status=404, headers=headers)

            # Generate statement using the model's generate_loan_statement method
            start_date = data.get('startDate')
            end_date = data.get('endDate')
            if start_date:
                start_date = parse(start_date).date()
            if end_date:
                end_date = parse(end_date).date()

            statement_raw = loan.generate_loan_statement(start_date=start_date, end_date=end_date)

            # Prepare amortization schedule
            amortization_schedule = [
                {
                    "period": index + 1,
                    "payment": float(installment['total_payment']),
                    "principal": float(installment['principal']),
                    "interest": float(installment['interest']),
                    "balance": float(installment['closing_balance'])
                } for index, installment in enumerate(statement_raw['amortization_schedule'])
            ]

            # Compute amortization summary
            total_payment = sum(installment['total_payment'] for installment in statement_raw['amortization_schedule'])
            total_interest = sum(installment['interest'] for installment in statement_raw['amortization_schedule'])
            monthly_payment = loan.emi_estimate

            amortization_data = {
                "schedule": amortization_schedule,
                "summary": {
                    "monthlyPayment": float(monthly_payment),
                    "totalPayment": float(total_payment),
                    "totalInterest": float(total_interest),
                    "loanAmount": float(loan.loan_amount),
                    "interestRate": float(loan.interest_rate),
                    "loanPeriod": loan.loan_term
                }
            }

            # Format the statement for API response
            statement = {
                'status': 'success',
                'data': {
                    "memberId": loan.client_id.member_id,
                    "memberName": loan.client_id.name,
                    "loanId": loan.name,
                    "startDate": statement_raw['loan_details']['disbursement_date'].isoformat() if statement_raw['loan_details']['disbursement_date'] else None,
                    "endDate": end_date.isoformat() if end_date else date.today().isoformat(),
                    "requestDate": date.today().isoformat(),
                    "product": loan.loan_type_id.name,
                    "productType": "Loans",
                    "loanAmount": float(statement_raw['loan_details']['loan_amount']),
                    "currentBalance": float(statement_raw['summary']['current_principal_balance']),
                    "currency": loan.currency_id.name,
                    "transactions": [
                        {
                            "date": tx['date'].isoformat() if isinstance(tx['date'], date) else tx['date'],
                            "description": tx['type'],
                            "amount": float(tx['amount']),
                            "principal": float(tx['principal']),
                            "interest": float(tx['interest']),
                            "balance": float(tx['balance']),
                        } for tx in statement_raw['transactions']
                    ],
                    "summary": {
                        "totalPaid": float(statement_raw['summary']['total_paid']),
                        "totalPrincipalPaid": float(statement_raw['summary']['total_principal_paid']),
                        "totalInterestPaid": float(statement_raw['summary']['total_interest_paid']),
                        "totalInterestAccrued": float(statement_raw['summary']['total_interest_accrued']),
                        "currentPrincipalBalance": float(statement_raw['summary']['current_principal_balance']),
                        "accruedInterest": float(statement_raw['summary']['accrued_interest'])
                    },
                    "amortization": amortization_data, 
                    "createdBy": loan.client_id.member_id
                }
            }

            # Return JSON response with proper headers
            headers = {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            }
            return Response(json.dumps(statement), status=200, headers=headers)

        except Exception as e:
            error_response = {
                'status': 'error',
                'message': str(e)
            }
            headers = {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            }
            return Response(json.dumps(error_response), status=500, headers=headers)