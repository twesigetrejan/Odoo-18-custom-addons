from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from psycopg2.sql import SQL, Identifier
from odoo import tools

class SaccoJournalAccountLine(models.Model):
    _name = 'sacco.journal.account.line'
    _description = 'SACCO Journal Account Line'
    _auto = False  # This tells Odoo not to create a table for this model
    _order = 'date asc, id asc'

    id = fields.Integer('ID', readonly=True)
    name = fields.Char('Description', readonly=True)
    savings_account_id = fields.Many2one('sacco.savings.account', string='Savings Account', readonly=True)
    date = fields.Date(string='Date', readonly=True)
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    journal_line_id = fields.Many2one('account.move.line', string='Journal Item', readonly=True)
    type = fields.Selection([
        ('deposit', 'Deposit'),
        ('withdrawal', 'Withdrawal'),
        ('interest', 'Interest'),
        ('interest_withdrawal', 'Interest Withdrawal'),
        ('fee', 'Fee'),
        ('transfer', 'Transfer'),
        ('other', 'Other')
    ], string='Transaction Type', readonly=True)
    opening_balance = fields.Float('Opening Balance', readonly=True, digits='Account')
    amount = fields.Float('Amount', readonly=True, digits='Account')
    closing_balance = fields.Float('Closing Balance', readonly=True, digits='Account')
    currency_id = fields.Many2one(related='savings_account_id.currency_id', string='Currency')

    def init(self):
        """Initialize the SQL materialized view"""
        
        # First, check if the object exists and what type it is
        self.env.cr.execute("""
            SELECT CASE 
                WHEN EXISTS (SELECT 1 FROM information_schema.tables 
                            WHERE table_name = 'sacco_journal_account_line' 
                            AND table_type = 'BASE TABLE') 
                THEN 'TABLE'
                WHEN EXISTS (SELECT 1 FROM pg_matviews 
                            WHERE matviewname = 'sacco_journal_account_line') 
                THEN 'MATERIALIZED VIEW'
                WHEN EXISTS (SELECT 1 FROM pg_views 
                            WHERE viewname = 'sacco_journal_account_line') 
                THEN 'VIEW'
                ELSE 'NONE'
            END as object_type
        """)
        object_type = self.env.cr.fetchone()[0]
        
        # Drop the object based on its type
        if object_type == 'TABLE':
            self.env.cr.execute("DROP TABLE IF EXISTS sacco_journal_account_line CASCADE")
        elif object_type == 'MATERIALIZED VIEW':
            self.env.cr.execute("DROP MATERIALIZED VIEW IF EXISTS sacco_journal_account_line CASCADE")
        elif object_type == 'VIEW':
            self.env.cr.execute("DROP VIEW IF EXISTS sacco_journal_account_line CASCADE")
        
        # Create the SQL materialized view
        query = """
        CREATE MATERIALIZED VIEW sacco_journal_account_line AS (
            WITH move_data AS (
                SELECT
                    aml.id,
                    aml.name,
                    sa.id AS savings_account_id,
                    aml.date,
                    aml.move_id AS journal_entry_id,
                    aml.id AS journal_line_id,
                    CASE
                        WHEN aml.account_id = sp.savings_product_account_id AND aml.credit > 0 THEN 'deposit'
                        WHEN aml.account_id = sp.savings_product_account_id AND aml.debit > 0 THEN 'withdrawal'
                        WHEN aml.account_id = sp.interest_disbursement_account_id AND aml.credit > 0 THEN 'interest'
                        WHEN aml.account_id = sp.interest_disbursement_account_id AND aml.debit > 0 THEN 'interest_withdrawal'
                        ELSE 'other'
                    END AS type,
                    CASE
                        WHEN aml.account_id = sp.savings_product_account_id AND aml.credit > 0 THEN aml.credit  -- Deposit increases balance
                        WHEN aml.account_id = sp.savings_product_account_id AND aml.debit > 0 THEN -aml.debit  -- Withdrawal decreases balance
                        WHEN aml.account_id = sp.interest_disbursement_account_id AND aml.credit > 0 THEN aml.credit  -- Interest increases balance
                        WHEN aml.account_id = sp.interest_disbursement_account_id AND aml.debit > 0 THEN -aml.debit  -- Interest decreases balance
                        ELSE 0
                    END AS amount,
                    aml.date as row_date
                FROM
                    account_move_line aml
                JOIN
                    account_move am ON aml.move_id = am.id
                JOIN
                    res_partner rp ON aml.member_id = rp."member_id"
                JOIN
                    sacco_savings_account sa ON sa.member_id = rp.id
                JOIN
                    sacco_savings_product sp ON sa.product_id = sp.id
                WHERE
                    am.state = 'posted'
                    AND (aml.account_id = sp.savings_product_account_id OR aml.account_id = sp.interest_disbursement_account_id)
                    AND aml.member_id IS NOT NULL
                ORDER BY
                    sa.id, aml.date, aml.id
            ),
            running_balance AS (
                SELECT
                    md.id,
                    md.name,
                    md.savings_account_id,
                    md.date,
                    md.journal_entry_id,
                    md.journal_line_id,
                    md.type,
                    md.amount,
                    SUM(md.amount) OVER (
                        PARTITION BY md.savings_account_id
                        ORDER BY md.row_date, md.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS closing_balance,
                    COALESCE(SUM(md.amount) OVER (
                        PARTITION BY md.savings_account_id
                        ORDER BY md.row_date, md.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0) AS opening_balance
                FROM
                    move_data md
            )
            SELECT
                rb.id,
                COALESCE(rb.name, 'Transaction') as name,
                rb.savings_account_id,
                rb.date,
                rb.journal_entry_id,
                rb.journal_line_id,
                rb.type,
                ABS(rb.amount) as amount,
                rb.opening_balance,
                rb.closing_balance
            FROM
                running_balance rb
            ORDER BY
                rb.savings_account_id, rb.date, rb.id
        )
        """
        
        self.env.cr.execute(query)
        
        # Create indexes for better performance
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS sacco_journal_account_line_savings_account_id_idx 
            ON sacco_journal_account_line (savings_account_id)
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS sacco_journal_account_line_date_idx 
            ON sacco_journal_account_line (date)
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