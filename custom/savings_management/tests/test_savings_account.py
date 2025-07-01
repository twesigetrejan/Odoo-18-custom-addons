from odoo.tests import TransactionCase
from odoo.tests.common import tagged
from odoo import fields

@tagged('post_install', '-at_install', 'savings_product_test')
class TestSavingsAccount(TransactionCase):

    def setUp(self):
        super().setUp()
        
        # Create accounts
        self.savings_account = self.env['account.account'].create({
            'name': 'Test Savings Account',
            'code': 'TST001',
            'account_type': 'asset_current',
            'reconcile': True,
        })
        
        self.disburse_account = self.env['account.account'].create({
            'name': 'Test Disburse Account',
            'code': 'TST002',
            'account_type': 'asset_current',
            'reconcile': True,
        })

        self.interest_account = self.env['account.account'].create({
            'name': 'Test Interest Account',
            'code': 'TST003',
            'account_type': 'expense',
            'reconcile': True,
        })

        # Create journals
        self.savings_journal = self.env['account.journal'].create({
            'name': 'Test Savings Journal',
            'code': 'TSJ',
            'type': 'general',
        })
        
        self.disburse_journal = self.env['account.journal'].create({
            'name': 'Test Disburse Journal',
            'code': 'TDJ',
            'type': 'general',
        })

        # Create member
        self.member = self.env['res.partner'].create({
            'name': 'Test Member',
            'is_sacco_member': True,
            'member_id': 'TEST001',
            'email': 'test@test.com'
        })

        # Create product with required accounts and journals
        self.product = self.env['sacco.savings.product'].create({
            'name': 'Test Product',
            'period': 'monthly',
            'interest_rate': 5.0,
            'savings_product_account_id': self.savings_account.id,
            'savings_product_journal_id': self.savings_journal.id,
            'withdrawal_account_id': self.disburse_account.id,
            'disburse_journal_id': self.disburse_journal.id,
            'interest_account_id': self.interest_account.id,
        })

    def test_update_statement_toggle(self):
        # Create savings account with update_statement True
        account = self.env['sacco.savings.account'].create({
            'member_id': self.member.id,
            'product_id': self.product.id,
            'update_statement': True
        })
        
        # Verify initial state
        self.assertTrue(account.update_statement, f"Expected update_statement to be True after transaction confirmation. Got {account.update_statement}")

        # Create a transaction
        transaction = self.env['savings.transaction'].create({
            'savings_account_id': account.id,
            'transaction_type': 'deposit',
            'amount': 1000,
            'transaction_date': fields.Date.today(),
            'status': 'pending'
        })
        transaction.action_confirm_transaction()

        # Verify update_statement was set to False
        self.assertFalse(account.update_statement, f"Expected update_statement to be False after transaction confirmation. Got {account.update_statement}")

        # Verify transaction status and account line creation
        self.assertEqual(transaction.status, 'confirmed')
        self.assertTrue(transaction.savings_account_line_id)