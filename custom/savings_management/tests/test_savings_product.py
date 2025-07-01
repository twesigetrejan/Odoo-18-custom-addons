from odoo.tests import TransactionCase
from odoo.tests.common import tagged
from odoo.exceptions import ValidationError, UserError

@tagged('post_install', '-at_install')
class TestSavingsProduct(TransactionCase):

    def setUp(self):
        super().setUp()
        
        # Create test sequence
        self.env['ir.sequence'].create({
            'name': 'Test Savings Product Sequence',
            'code': 'sacco.savings.product.code',
            'prefix': 'TST',
            'padding': 3,
        })

        # Create base product for testing
        self.savings_product = self.env['sacco.savings.product'].create({
            'name': 'Test Savings Product',
            'interest_rate': 5,
            'period': 'monthly',
            'currency_id': self.env.company.currency_id.id,
        })

    def test_create_savings_product(self):
        """Test creation of savings product with basic fields"""
        self.assertTrue(self.savings_product.id)
        self.assertEqual(self.savings_product.name, 'Test Savings Product')
        self.assertEqual(self.savings_product.interest_rate, 5.0)
        self.assertEqual(self.savings_product.period, 'monthly')

    def test_compute_savings_account_count(self):
        """Test computation of related savings accounts"""
        # Initially should be 0
        self.assertEqual(self.savings_product.savings_account_count, 0)

        # Create a savings account linked to the product
        self.env['sacco.savings.account'].create({
            'member_id': self.env['res.partner'].create({'name': 'Test Member'}).id,
            'product_id': self.savings_product.id,
        })

        # Recompute and check count
        self.savings_product._compute_savings_account_count()
        self.assertEqual(self.savings_product.savings_account_count, 1)

    def test_prevent_name_modification(self):
        """Test prevention of name modification when accounts exist"""
        # Create a linked savings account
        self.env['sacco.savings.account'].create({
            'member_id': self.env['res.partner'].create({'name': 'Test Member'}).id,
            'product_id': self.savings_product.id,
        })

        # Attempt to modify name should raise ValidationError
        with self.assertRaises(ValidationError):
            self.savings_product.write({'name': 'Modified Name'})

    def test_create_account_journals(self):
        """Test creation of accounts and journals"""
        # Ensure no accounts/journals are set initially
        self.assertFalse(self.savings_product.withdrawal_account_id)
        self.assertFalse(self.savings_product.interest_account_id)
        self.assertFalse(self.savings_product.savings_product_account_id)
        self.assertFalse(self.savings_product.savings_product_journal_id)
        self.assertFalse(self.savings_product.disburse_journal_id)

        # Create accounts and journals
        self.savings_product.action_create_account_journals()

        # Verify all accounts and journals were created
        self.assertTrue(self.savings_product.withdrawal_account_id)
        self.assertTrue(self.savings_product.interest_account_id)
        self.assertTrue(self.savings_product.savings_product_account_id)
        self.assertTrue(self.savings_product.savings_product_journal_id)
        self.assertTrue(self.savings_product.disburse_journal_id)

        # Verify account types
        self.assertEqual(self.savings_product.savings_product_account_id.account_type, 'asset_current')
        self.assertEqual(self.savings_product.withdrawal_account_id.account_type, 'asset_current')
        self.assertEqual(self.savings_product.interest_account_id.account_type, 'expense')

        # Verify journal types
        self.assertEqual(self.savings_product.savings_product_journal_id.type, 'general')
        self.assertEqual(self.savings_product.disburse_journal_id.type, 'general')

    def test_prevent_duplicate_account_journal_creation(self):
        """Test prevention of creating duplicate accounts and journals"""
        # Create accounts and journals first time
        self.savings_product.action_create_account_journals()

        # Attempt to create again should raise UserError
        with self.assertRaises(UserError):
            self.savings_product.action_create_account_journals()

    def test_unique_code_generation(self):
        """Test generation of unique codes"""
        code1 = self.savings_product._get_unique_code()
        code2 = self.savings_product._get_unique_code()
        
        self.assertTrue(code1)
        self.assertTrue(code2)
        self.assertNotEqual(code1, code2)