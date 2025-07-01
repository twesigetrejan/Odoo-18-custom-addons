import base64
import pandas as pd
from io import BytesIO
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class ImportWizard(models.TransientModel):
    _name = 'import.wizard'
    _description = 'Import Wizard for Sacco Transactions'

    file = fields.Binary(string='Excel File', required=True)
    file_name = fields.Char(string='File Name')
    
    # Savings Accounts
    savings_account_ids = fields.Many2many(
        'account.account',
        relation='import_wizard_savings_account_rel',
        string='Savings Accounts',
        domain="[('account_product_type', '=', 'savings'), ('deprecated', '=', False)]"
    )
    savings_product_ids = fields.Char(
        string='Savings Product IDs (Comma-separated)',
        help="Enter product IDs for savings accounts (e.g., SVOPTPO,SV002)"
    )
    savings_journal_id = fields.Many2one('account.journal', string='Savings Journal', required=True)

    # Savings Interest Accounts
    savings_interest_account_ids = fields.Many2many(
        'account.account',
        relation='import_wizard_savings_interest_account_rel',
        string='Savings Interest Accounts',
        domain="[('account_product_type', '=', 'savings_interest'), ('deprecated', '=', False)]"
    )
    savings_interest_product_ids = fields.Char(
        string='Savings Interest Product IDs (Comma-separated)',
        help="Enter product IDs for savings interest accounts"
    )
    savings_interest_journal_id = fields.Many2one('account.journal', string='Savings Interest Journal')

    # Shares Accounts
    shares_account_ids = fields.Many2many(
        'account.account',
        relation='import_wizard_shares_account_rel',
        string='Shares Accounts',
        domain="[('account_product_type', '=', 'shares'), ('deprecated', '=', False)]"
    )
    shares_product_ids = fields.Char(
        string='Shares Product IDs (Comma-separated)',
        help="Enter product IDs for shares accounts (e.g., SH001,SH002)"
    )
    shares_journal_id = fields.Many2one('account.journal', string='Shares Journal', required=True)

    # Loan Accounts
    loan_account_ids = fields.Many2many(
        'account.account',
        relation='import_wizard_loan_account_rel',
        string='Loan Accounts',
        domain="[('account_product_type', '=', 'loans'), ('deprecated', '=', False)]"
    )
    loan_product_ids = fields.Char(
        string='Loan Product IDs (Comma-separated)',
        help="Enter product IDs for loan accounts (e.g., LN001,LN002)"
    )
    loan_journal_id = fields.Many2one('account.journal', string='Loan Journal', required=True)

    # Loan Interest Accounts
    loan_interest_account_ids = fields.Many2many(
        'account.account',
        relation='import_wizard_loan_interest_account_rel',
        string='Loan Interest Accounts',
        domain="[('account_product_type', '=', 'loans_interest'), ('deprecated', '=', False)]"
    )
    loan_interest_product_ids = fields.Char(
        string='Loan Interest Product IDs (Comma-separated)',
        help="Enter product IDs for loan interest accounts"
    )
    loan_interest_journal_id = fields.Many2one('account.journal', string='Loan Interest Journal')

    # Default Accounts
    default_receiving_account_id = fields.Many2one(
        'account.account',
        string='Default Receiving Account',
        domain="[('deprecated', '=', False)]",
        required=True
    )
    default_paying_account_id = fields.Many2one(
        'account.account',
        string='Default Paying Account',
        domain="[('deprecated', '=', False)]",
        required=True
    )
    
    interest_income_account_id = fields.Many2one('account.account', string="Interest Income Account")

    def action_import(self):
        _logger.info("Starting import process for file: %s", self.file_name)

        if not self.file:
            raise ValidationError(_("Please upload an Excel file."))

        excel_data = base64.b64decode(self.file)
        df = pd.read_excel(BytesIO(excel_data))

        required_columns = ['memberId', 'productId', 'vdate', 'ttype', 'amount', 'amtusd', 'paydet', 'bfbal']
        if not all(col in df.columns for col in required_columns):
            raise ValidationError(_("Excel file must contain the following columns: %s") % ', '.join(required_columns))

        balances = {}

        for index, row in df.iterrows():
            if str(row['bfbal']).strip().upper() == "Y":
                _logger.info("Skipping row %d: bfbal is 'Y' for memberId=%s", index, row['memberId'])
                continue
            
            skip_product_ids = {'SVSCFP3', 'SVTAGP1', 'SVTAGP3', 'SVSCFP1'}
            if str(row['productId']).strip().upper() in skip_product_ids:
                _logger.info("Skipping transaction for productId=%s as it belongs to excluded categories", row['productId'])
                continue
                    
            _logger.info("Processing row %d: memberId=%s, productId=%s, ttype=%s, amount=%s", 
                        index, row['memberId'], row['productId'], row['ttype'], row['amount'])
            try:
                key = f"{row['memberId']}-{row['productId']}"
                current_balance = balances.get(key, 0.0)
                _logger.info("Current balance for %s: %s", key, current_balance)

                transaction_type = 'deposit' if 'C' in str(row['ttype']) else 'withdrawal'
                amount = float(row['amount'])

                self.process_row(row)

                if transaction_type == 'deposit':
                    balances[key] = current_balance + amount
                else:
                    balances[key] = current_balance - amount

                _logger.info("New balance for %s: %s", key, balances[key])
                _logger.info("Successfully processed row %d", index)

            except Exception as e:
                _logger.error("Error processing row %d: %s", index, str(e))
                _logger.info("Balances at error point: %s", balances)
                raise ValidationError(
                    _("Error processing row %d: %s\nCurrent balances: %s") % 
                    (index, str(e), str(balances))
                )

        _logger.info("Import process completed successfully. Final balances: %s", balances)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Transactions imported successfully.'),
                'sticky': False,
            }
        }

    def process_row(self, row):
        """
        Process a single row from the imported Excel file.
        """
        member_id = row['memberId']
        try:
            member_id = str(int(float(member_id))) if float(member_id).is_integer() else str(member_id)
        except ValueError:
            member_id = str(member_id)

        product_id = row['productId']
        vdate = row['vdate']
        ttype = row['ttype']
        amount = row['amount']
        paydet = row.get('paydet', '').lower()  # Get payment detail, default to empty string

        # Find the member
        member = self.env['res.partner'].search([('member_id', '=', member_id)], limit=1)
        if not member:
            raise ValidationError(_("Member with ID %s not found.") % member_id)

        transaction_type = 'deposit' if 'C' in str(ttype) else 'withdrawal'

        # Define product lists from wizard fields
        savings_products = self.savings_product_ids.split(',') if self.savings_product_ids else []
        savings_interest_products = self.savings_interest_product_ids.split(',') if self.savings_interest_product_ids else []
        shares_products = self.shares_product_ids.split(',') if self.shares_product_ids else []
        loan_products = self.loan_product_ids.split(',') if self.loan_product_ids else []
        loan_interest_products = self.loan_interest_product_ids.split(',') if self.loan_interest_product_ids else []

        # Route the transaction based on product ID
        if str(product_id) in savings_products:
            _logger.info("Processing savings transaction for productId=%s", product_id)
            self.process_savings_transaction(member, product_id, vdate, transaction_type, amount, paydet, is_interest=False)
        elif str(product_id) in savings_interest_products:
            _logger.info("Processing savings interest transaction for productId=%s", product_id)
            self.process_savings_transaction(member, product_id, vdate, transaction_type, amount, paydet, is_interest=True)
        elif str(product_id) in shares_products:
            _logger.info("Processing shares transaction for productId=%s", product_id)
            self.process_shares_transaction(member, product_id, vdate, transaction_type, amount, paydet)
        elif str(product_id) in loan_products:
            _logger.info("Processing loan transaction for productId=%s", product_id)
            self.process_loan_transaction(member, product_id, vdate, transaction_type, amount, paydet)
        elif str(product_id) in loan_interest_products:
            _logger.info("Processing loan interest transaction for productId=%s", product_id)
            self.process_loan_interest_transaction(member, product_id, vdate, transaction_type, amount, paydet)
        else:
            raise ValidationError(_("Product ID %s does not match any defined products.") % product_id)

    def process_savings_transaction(self, member, product_id, vdate, transaction_type, amount, paydet, is_interest=False):
        account_ids = self.savings_interest_account_ids if is_interest else self.savings_account_ids
        journal_id = self.savings_interest_journal_id if is_interest else self.savings_journal_id
        
        account = account_ids.filtered(lambda a: a.code == str(product_id))
        if not account:
            raise ValidationError(_("No savings %s account found for product ID %s.") % ('interest' if is_interest else '', product_id))

        if not journal_id:
            raise ValidationError(_("No journal configured for savings %s transactions") % ('interest' if is_interest else ''))

        # For interest transactions, we don't need a savings product or account creation
        if is_interest:
            move_vals = {
                'date': vdate,
                'ref': paydet or f"Savings Interest - {member.member_id}",
                'journal_id': journal_id.id,
                'company_id': journal_id.company_id.id,
                'line_ids': [],
            }

            if transaction_type == 'deposit':
                debit_line = {
                    'account_id': self.default_receiving_account_id.id,
                    'debit': amount,
                    'credit': 0.0,
                    'partner_id': member.id,
                    'name': f"{paydet}",
                }
                credit_line = {
                    'account_id': account.id,
                    'credit': amount,
                    'debit': 0.0,
                    'partner_id': member.id,
                    'name': f"{paydet}",
                    'member_id': str(member.member_id) if member.member_id else False,
                }
                move_vals['line_ids'].extend([(0, 0, debit_line), (0, 0, credit_line)])

            else:  # withdrawal
                debit_line = {
                    'account_id': account.id,
                    'debit': amount,
                    'credit': 0.0,
                    'partner_id': member.id,
                    'name': f"{paydet}",
                    'member_id': str(member.member_id) if member.member_id else False,
                }
                credit_line = {
                    'account_id': self.default_paying_account_id.id,
                    'credit': amount,
                    'debit': 0.0,
                    'partner_id': member.id,
                    'name': f"{paydet}",
                }
                move_vals['line_ids'].extend([(0, 0, debit_line), (0, 0, credit_line)])

            try:
                move = self.env['account.move'].create(move_vals)
                move.action_post()
                _logger.info("Created journal entry for savings interest: %s", move.name)
            except Exception as e:
                _logger.error("Error creating journal entry for savings interest transaction: %s", str(e))
                raise ValidationError(_("Error creating journal entry for savings interest transaction: %s") % str(e))

        else:  # Non-interest savings transactions
            product = self.env['sacco.savings.product'].search([('savings_product_account_id.code', '=', account.code)], limit=1)
            if not product:
                raise ValidationError(_("Savings product not found for account %s.") % account.name)

            savings_account = self.env['sacco.savings.account'].search([
                ('member_id', '=', member.id),
                ('product_id', '=', product.id),
                ('state', '=', 'active'),
            ], limit=1)

            if not savings_account:            
                savings_account = self.env['sacco.savings.account'].create({
                    'member_id': member.id,
                    'product_id': product.id,
                    'currency_id': product.currency_id.id,
                    'state': 'active',
                })
            
            savings_account.action_refresh_journal_lines()
            
            account_balance = savings_account.balance if hasattr(savings_account, 'balance') else 0.0
            _logger.info("Savings account balance for member %s, product %s: %s", member.member_id, product_id, account_balance)

            move_vals = {
                'date': vdate,
                'ref': paydet or f"Savings {transaction_type} - {member.member_id}",
                'journal_id': journal_id.id,
                'company_id': journal_id.company_id.id,
                'line_ids': [],
            }

            if transaction_type == 'deposit':
                debit_line = {
                    'account_id': self.default_receiving_account_id.id,
                    'debit': amount,
                    'credit': 0.0,
                    'partner_id': member.id,
                    'name': f"{paydet}",
                }
                credit_line = {
                    'account_id': account.id,
                    'credit': amount,
                    'debit': 0.0,
                    'partner_id': member.id,
                    'name': f"{paydet}",
                    'member_id': str(member.member_id) if member.member_id else False,
                }
                move_vals['line_ids'].extend([(0, 0, debit_line), (0, 0, credit_line)])

            else:  # withdrawal
                withdrawal_account = product.withdrawal_account_id or account
                debit_line = {
                    'account_id': withdrawal_account.id,
                    'debit': amount,
                    'credit': 0.0,
                    'partner_id': member.id,
                    'name': f"{paydet}",
                    'member_id': str(member.member_id) if member.member_id else False,
                }
                credit_line = {
                    'account_id': self.default_paying_account_id.id,
                    'credit': amount,
                    'debit': 0.0,
                    'partner_id': member.id,
                    'name': f"{paydet}",
                }
                move_vals['line_ids'].extend([(0, 0, debit_line), (0, 0, credit_line)])

            try:
                move = self.env['account.move'].create(move_vals)
                move.action_post()
                _logger.info("Created journal entry for savings %s: %s", transaction_type, move.name)
                
                if hasattr(savings_account, 'action_refresh_journal_lines'):
                    savings_account.action_refresh_journal_lines()
                    
            except Exception as e:
                _logger.error("Error creating journal entry for savings transaction: %s", str(e))
                raise ValidationError(_("Error creating journal entry for savings transaction: %s") % str(e))

    def process_shares_transaction(self, member, product_id, vdate, transaction_type, amount, paydet):
        account = self.shares_account_ids.filtered(lambda a: a.code == str(product_id))
        if not account:
            raise ValidationError(_("No shares account found for product ID %s.") % product_id)

        product = self.env['sacco.shares.product'].search([('original_shares_product_account_id.code', '=', account.code)], limit=1)
        if not product:
            raise ValidationError(_("Shares product not found for account %s.") % account.name)

        shares_account = self.env['sacco.shares.account'].search([
            ('member_id', '=', member.id),
            ('product_id', '=', product.id),
            ('state', '=', 'active'),
        ], limit=1)

        if not shares_account:
            shares_account = self.env['sacco.shares.account'].create({
                'member_id': member.id,
                'product_id': product.id,
                'currency_id': product.currency_id.id,
                'state': 'active',
            })

        account_balance = shares_account.balance if hasattr(shares_account, 'balance') else 0.0
        _logger.info("Shares account balance for member %s, product %s: %s", member.member_id, product_id, account_balance)

        if transaction_type == 'withdrawal' and amount > account_balance:
            raise ValidationError(
                _("Withdrawal amount %s exceeds shares account balance %s for member %s, product %s") % 
                (amount, account_balance, member.member_id, product_id)
            )

        transaction = self.env['shares.transaction'].create({
            'member_id': member.id,
            'product_id': product.id,
            'shares_account_id': shares_account.id,
            'transaction_type': transaction_type,
            'amount': amount,
            'transaction_date': vdate,
            'status': 'pending',
            'receipt_account': self.default_receiving_account_id.id if transaction_type == 'deposit' else self.default_paying_account_id.id,
        })

        transaction.action_confirm_transaction()

        if transaction.journal_entry_id:
            transaction.journal_entry_id.write({'ref': paydet})

    def process_loan_transaction(self, member, product_id, vdate, transaction_type, amount, paydet):
        """
        Process transactions for loan accounts (account_product_type = 'loans').
        Creates a new loan for disbursements if none exists, otherwise associates with an existing loan.
        """
        # Find the loan account based on product_id
        account = self.loan_account_ids.filtered(lambda a: a.code == str(product_id))
        if not account:
            raise ValidationError(_("No loan account found for product ID %s.") % product_id)

        # Find the loan type based on the account
        loan_type = self.env['sacco.loan.type'].search([('loan_account_id', '=', account.id)], limit=1)
        if not loan_type:
            raise ValidationError(_("No loan type found for account %s.") % account.name)

        # Determine if it's a disbursement, handling typos like "Disbustment"
        paydet_lower = paydet.lower()  # Convert to lowercase for case-insensitive comparison
        is_disbursement = any(term in paydet_lower for term in ['disbursement', 'disbustment', 'disbursment'])

        loan = False
        if is_disbursement:
            # Check for an existing loan
            loan = self.env['sacco.loan.loan'].search([
                ('client_id', '=', member.id),
                ('loan_type_id', '=', loan_type.id),
                ('state', 'in', ['open', 'disburse', 'approve', 'close'])
            ], limit=1)
            if not loan:
                # Create a new loan
                loan_vals = {
                    'client_id': member.id,
                    'loan_type_id': loan_type.id,
                    'loan_amount': float(amount),
                    'loan_term': 60,
                    'interest_rate': loan_type.rate or 0.0,
                    'currency_id': loan_type.currency_id.id,
                    'state': 'open',
                    'disbursement_date': vdate,
                    'approve_date': vdate,
                    'request_date': vdate,
                    'user_id': self.env.user.id,
                    'company_id': self.env.company.id,
                }
                loan = self.env['sacco.loan.loan'].create(loan_vals)
                loan.compute_installment(vdate)
                
                # self.env.flush_all()  # Write all pending changes to the database
                # self.env.cr.commit()  # Commit the transaction so the loan is visible
                _logger.info("Created new loan %s for member %s", loan.name, member.member_id)
        else: 
            # For non-disbursements (e.g., payments), find an existing loan
            loan = self.env['sacco.loan.loan'].search([
                ('client_id', '=', member.id),
                ('loan_type_id', '=', loan_type.id),
                ('state', 'in', ['open', 'disburse'])
            ], limit=1)
            if not loan:
                raise ValidationError(_("No existing loan found for member %s and product %s for this transaction.") % (member.member_id, product_id))

        # Create journal entry
        move_vals = {
            'date': vdate,
            'ref': paydet or f"Loan Transaction - {member.member_id}",
            'journal_id': self.loan_journal_id.id,
            'company_id': self.loan_journal_id.company_id.id,
            'line_ids': [],
        }

        if transaction_type == 'withdrawal':  # ttype = 'D' (Loan Disbursement)
            # Debit loan account (receivable), credit paying account (e.g., cash/bank)
            debit_line = {
                'account_id': account.id,
                'debit': amount,
                'credit': 0.0,
                'partner_id': member.id,
                'name': f"{paydet}",
                'date_maturity':vdate,
                'loan_id': loan.name,
                'member_id': member.member_id,
            }
            credit_line = {
                'account_id': self.default_paying_account_id.id,
                'credit': amount,
                'debit': 0.0,
                'partner_id': member.id,
                'name': f"{paydet}",
                'date_maturity':vdate,
            }
            move_vals['line_ids'].extend([(0, 0, debit_line), (0, 0, credit_line)])
        else:
            # ttype = 'C' (Loan Payment)
            # For payments: debit receiving account (e.g., cash/bank), credit loan account
            debit_line = {
                'account_id': self.default_receiving_account_id.id,
                'debit': amount,
                'credit': 0.0,
                'partner_id': member.id,
                'name': f"{paydet}",
            }
            credit_line = {
                'account_id': account.id,
                'credit': amount,
                'debit': 0.0,
                'partner_id': member.id,
                'name': f"{paydet}",
                'loan_id': loan.name,
                'member_id': member.member_id,
            }
            move_vals['line_ids'].extend([(0, 0, debit_line), (0, 0, credit_line)])
            
            ###################################################################

        try:
            move = self.env['account.move'].create(move_vals)
            move.action_post()
            _logger.info("Created journal entry for loan transaction: %s", move.name)
        except Exception as e:
            _logger.error("Error creating journal entry for loan transaction: %s", str(e))
            raise ValidationError(_("Error creating journal entry for loan transaction: %s") % str(e))
        

    def process_loan_interest_transaction(self, member, product_id, vdate, transaction_type, amount, paydet):
        """
        Process transactions for loan interest accounts (account_product_type = 'loans_interest').
        Associates the transaction with an existing loan based on interest_account_id.code.
        """
        # Find the interest account based on product_id
        account = self.loan_interest_account_ids.filtered(lambda a: a.code == str(product_id))
        if not account:
            raise ValidationError(_("No loan interest account found for product ID %s.") % product_id)

        # Find the loan type where interest_account_id matches the account
        loan_type = self.env['sacco.loan.type'].search([('interest_account_id', '=', account.id)], limit=1)
        if not loan_type:
            raise ValidationError(_("No loan type found for interest account %s.") % account.name)

        # Find an existing loan
        loan = self.env['sacco.loan.loan'].search([
            ('client_id', '=', member.id),
            ('loan_type_id', '=', loan_type.id),
            ('state', 'in', ['open', 'disburse'])
        ], limit=1)
        if not loan:
            raise ValidationError(_("No existing loan found for member %s and interest product %s.") % (member.member_id, product_id))

        # Create journal entry
        move_vals = {
            'date': vdate,
            'ref': paydet or f"Loan Interest Transaction - {member.member_id}",
            'journal_id': self.loan_interest_journal_id.id,
            'move_type': 'entry',
            'partner_id': member.id,
            'line_ids': [],
        }

        # Debit interest account, credit interest income account
        credit_line = {
            'account_id': self.default_paying_account_id.id,
            'credit': amount,
            'debit': 0.0,
            'partner_id': member.id,
            'name': f"{paydet}",
        }
        debit_line = {
            'account_id': loan_type.interest_account_id.id,
            'debit': amount,
            'credit': 0.0,
            'partner_id': member.id,
            'name': f"{paydet}",
            'member_id': member.member_id,
            'loan_id': loan.name,
        }
        move_vals['line_ids'].extend([(0, 0, debit_line), (0, 0, credit_line)])

        try:
            move = self.env['account.move'].create(move_vals)
            move.action_post()
            _logger.info("Created journal entry for loan interest transaction: %s", move.name)
        except Exception as e:
            _logger.error("Error creating journal entry for loan interest transaction: %s", str(e))
            raise ValidationError(_("Error creating journal entry for loan interest transaction: %s") % str(e))