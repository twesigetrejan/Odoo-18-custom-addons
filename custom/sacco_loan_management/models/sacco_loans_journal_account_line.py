from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class SaccoLoansJournalAccountLine(models.Model):
    _name = 'sacco.loans.journal.account.line'
    _description = 'SACCO Loans Journal Account Line'
    _auto = False  # This tells Odoo not to create a table for this model
    _order = 'date asc, id asc'

    id = fields.Integer('ID', readonly=True)
    name = fields.Char('Description', readonly=True)
    loan_id = fields.Many2one('sacco.loan.loan', string='Loan', readonly=True)
    date = fields.Date(string='Date', readonly=True)
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    journal_line_id = fields.Many2one('account.move.line', string='Journal Item', readonly=True)
    transaction_type = fields.Selection([
        ('disbursement', 'Disbursement'),
        ('payment', 'Payment'),
        ('interest', 'Interest Accrual'),
    ], string='Transaction Type', readonly=True)
    principal_amount = fields.Float('Principal Amount', readonly=True, digits='Account')
    interest_amount = fields.Float('Interest Amount', readonly=True, digits='Account')
    total_amount = fields.Float('Total Amount', readonly=True, digits='Account')
    currency_id = fields.Many2one(related='loan_id.currency_id', string='Currency', readonly=True)

    def init(self):
        """Initialize the SQL view as a materialized view for better performance"""
        # Drop existing view if it exists
        self.env.cr.execute("DROP MATERIALIZED VIEW IF EXISTS sacco_loans_journal_account_line CASCADE")

        # Debug Step 1: Check if there are any account_move_line records with account_product_type = 'loans_interest'
        self.env.cr.execute("""
            SELECT COUNT(*)
            FROM account_move_line aml
            WHERE aml.debit > 0
            AND aml.account_product_type = 'loans_interest'
            AND aml.loan_id IS NOT NULL
        """)
        interest_line_count = self.env.cr.fetchone()[0]
        _logger.info("Debug Step 1: Number of account_move_line records with account_product_type='loans_interest' and debit > 0: %s", interest_line_count)

        # Debug Step 2: Check the loan_id values in account_move_line and sacco_loan_loan to verify the join
        self.env.cr.execute("""
            SELECT aml.loan_id, dll.name
            FROM account_move_line aml
            LEFT JOIN sacco_loan_loan dll ON aml.loan_id = dll.name
            WHERE aml.debit > 0
            AND aml.account_product_type = 'loans_interest'
            AND aml.loan_id IS NOT NULL
            LIMIT 10
        """)
        loan_id_matches = self.env.cr.fetchall()
        _logger.info("Debug Step 2: Loan ID matching between account_move_line and sacco_loan_loan: %s", loan_id_matches)

        # Debug Step 3: Check the number of interest lines after joining with account_move
        self.env.cr.execute("""
            SELECT COUNT(*)
            FROM account_move_line aml
            JOIN account_move am ON aml.move_id = am.id
            JOIN sacco_loan_loan dll ON aml.loan_id = dll.name
            WHERE aml.debit > 0
            AND aml.account_product_type = 'loans_interest'
            AND aml.loan_id IS NOT NULL
            AND am.state = 'posted'
        """)
        interest_line_posted_count = self.env.cr.fetchone()[0]
        _logger.info("Debug Step 3: Number of interest lines with posted journal entries: %s", interest_line_posted_count)

        # Debug Step 3.1: Check the states of journal entries for interest lines
        self.env.cr.execute("""
            SELECT am.state, COUNT(*)
            FROM account_move_line aml
            JOIN account_move am ON aml.move_id = am.id
            WHERE aml.debit > 0
            AND aml.account_product_type = 'loans_interest'
            AND aml.loan_id IS NOT NULL
            GROUP BY am.state
        """)
        states = self.env.cr.fetchall()
        _logger.info("Debug Step 3.1: Journal Entry States for Interest Lines: %s", states)

        # Create the materialized view
        query = """
        CREATE MATERIALIZED VIEW sacco_loans_journal_account_line AS (
            WITH journal_entries AS (
                SELECT
                    am.id AS move_id,
                    am.date AS move_date,
                    am.ref AS move_ref,
                    am.state
                FROM
                    account_move am
                WHERE
                    am.state = 'posted'
            ),
            disbursement_lines AS (
                SELECT
                    aml.move_id,
                    aml.id AS line_id,
                    aml.debit AS principal_amount,
                    0.0 AS interest_amount,
                    aml.debit AS total_amount,
                    aml.loan_id AS loan_ref,
                    aml.name,
                    dll.id AS loan_id
                FROM
                    account_move_line aml
                JOIN
                    account_move am ON aml.move_id = am.id
                JOIN
                    sacco_loan_loan dll ON aml.loan_id = dll.name
                WHERE
                    aml.debit > 0
                    AND aml.account_product_type = 'loans'
                    AND aml.loan_id IS NOT NULL
                    AND am.state = 'posted'
            ),
            payment_lines AS (
                SELECT
                    aml.move_id,
                    aml.id AS line_id,
                    CASE 
                        WHEN aml.account_product_type = 'loans' THEN aml.credit
                        ELSE 0.0
                    END AS principal_amount,
                    CASE 
                        WHEN aml.account_product_type = 'loans_interest' THEN aml.credit
                        ELSE 0.0
                    END AS interest_amount,
                    aml.credit AS total_amount,
                    aml.loan_id AS loan_ref,
                    aml.name,
                    dll.id AS loan_id
                FROM
                    account_move_line aml
                JOIN
                    account_move am ON aml.move_id = am.id
                JOIN
                    sacco_loan_loan dll ON aml.loan_id = dll.name
                WHERE
                    aml.credit > 0
                    AND aml.account_product_type IN ('loans', 'loans_interest')
                    AND aml.loan_id IS NOT NULL
                    AND am.state = 'posted'
            ),
            interest_lines AS (
                SELECT
                    aml.move_id,
                    aml.id AS line_id,
                    0.0 AS principal_amount,
                    aml.debit AS interest_amount,
                    aml.debit AS total_amount,
                    aml.loan_id AS loan_ref,
                    aml.name,
                    dll.id AS loan_id
                FROM
                    account_move_line aml
                JOIN
                    account_move am ON aml.move_id = am.id
                JOIN
                    sacco_loan_loan dll ON aml.loan_id = dll.name
                WHERE
                    aml.debit > 0
                    AND aml.account_product_type = 'loans_interest'
                    AND aml.loan_id IS NOT NULL
                    AND am.state = 'posted'
            ),
            -- Combine all lines into a single result set
            all_lines AS (
                SELECT
                    dl.move_id,
                    dl.line_id,
                    dl.principal_amount,
                    dl.interest_amount,
                    dl.total_amount,
                    dl.loan_ref,
                    dl.name,
                    dl.loan_id,
                    'disbursement' AS transaction_type
                FROM disbursement_lines dl
                UNION ALL
                SELECT
                    pl.move_id,
                    pl.line_id,
                    pl.principal_amount,
                    pl.interest_amount,
                    pl.total_amount,
                    pl.loan_ref,
                    pl.name,
                    pl.loan_id,
                    'payment' AS transaction_type
                FROM payment_lines pl
                UNION ALL
                SELECT
                    il.move_id,
                    il.line_id,
                    il.principal_amount,
                    il.interest_amount,
                    il.total_amount,
                    il.loan_ref,
                    il.name,
                    il.loan_id,
                    'interest' AS transaction_type
                FROM interest_lines il
            )
            
            SELECT
                ROW_NUMBER() OVER () AS id,
                COALESCE(al.name, je.move_ref, 'Loan Transaction') AS name,
                al.loan_id,
                je.move_date AS date,
                al.move_id AS journal_entry_id,
                al.line_id AS journal_line_id,
                al.transaction_type,
                al.principal_amount,
                al.interest_amount,
                al.total_amount
            FROM
                all_lines al
            LEFT JOIN
                journal_entries je ON al.move_id = je.move_id
            WHERE
                al.move_id IS NOT NULL
            ORDER BY
                je.move_date, al.move_id
        )
        """
        self.env.cr.execute(query)

        # Debug Step 4: Check the number of interest transactions in the final materialized view
        self.env.cr.execute("""
            SELECT COUNT(*)
            FROM sacco_loans_journal_account_line
            WHERE transaction_type = 'interest'
        """)
        final_interest_count = self.env.cr.fetchone()[0]
        _logger.info("Debug Step 4: Number of interest transactions in the materialized view: %s", final_interest_count)

        # Debug Step 5: Check a sample of interest transactions
        self.env.cr.execute("""
            SELECT *
            FROM sacco_loans_journal_account_line
            WHERE transaction_type = 'interest'
            LIMIT 5
        """)
        sample_interest_transactions = self.env.cr.fetchall()
        _logger.info("Debug Step 5: Sample of interest transactions in the materialized view: %s", sample_interest_transactions)

        # Create indexes for better performance
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS sacco_loans_journal_account_line_loan_id_idx 
            ON sacco_loans_journal_account_line (loan_id)
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS sacco_loans_journal_account_line_date_idx 
            ON sacco_loans_journal_account_line (date)
        """)

    def action_view_journal_entry(self):
        """Open the journal entry related to this line"""
        self.ensure_one()
        return {
            'name': _('Journal Entry'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.journal_entry_id.id,
            'target': 'current',
        }

    @api.model
    def refresh_journal_lines(self, loan_id):
        """Refresh the materialized view for a specific loan"""
        self.env.cr.execute("""
            REFRESH MATERIALIZED VIEW sacco_loans_journal_account_line
        """)