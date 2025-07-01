from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from psycopg2.sql import SQL, Identifier
from odoo import tools

class SaccoSharesJournalAccountLine(models.Model):
    _name = 'sacco.shares.journal.account.line'
    _description = 'SACCO Shares Journal Account Line'
    _auto = False  # This tells Odoo not to create a table for this model
    _order = 'date asc, id asc'

    id = fields.Integer('ID', readonly=True)
    name = fields.Char('Description', readonly=True)
    shares_account_id = fields.Many2one('sacco.shares.account', string='Shares Account', readonly=True)
    date = fields.Date(string='Date', readonly=True)
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    journal_line_id = fields.Many2one('account.move.line', string='Journal Item', readonly=True)
    transaction_type = fields.Selection([
        ('deposit', 'Deposit'),
    ], string='Transaction Type', readonly=True)
    original_shares_amount = fields.Float('Original Shares Value', readonly=True, digits='Account')
    premium_shares_amount = fields.Float('Shares Premium Value', readonly=True, digits='Account')
    total_amount = fields.Float('Total Amount', readonly=True, digits='Account')
    number_of_shares = fields.Float('Number of Shares', readonly=True, digits='Account')
    currency_id = fields.Many2one(related='shares_account_id.currency_id', string='Currency')

    def init(self):
        """Initialize the SQL view"""
        
        # First, check if the object exists and what type it is
        self.env.cr.execute("""
            SELECT CASE 
                WHEN EXISTS (SELECT 1 FROM information_schema.tables 
                            WHERE table_name = 'sacco_shares_journal_account_line' 
                            AND table_type = 'BASE TABLE') 
                THEN 'TABLE'
                WHEN EXISTS (SELECT 1 FROM pg_matviews 
                            WHERE matviewname = 'sacco_shares_journal_account_line') 
                THEN 'MATERIALIZED VIEW'
                WHEN EXISTS (SELECT 1 FROM pg_views 
                            WHERE viewname = 'sacco_shares_journal_account_line') 
                THEN 'VIEW'
                ELSE 'NONE'
            END as object_type
        """)
        object_type = self.env.cr.fetchone()[0]
        
        # Drop the object based on its type
        if object_type == 'TABLE':
            self.env.cr.execute("DROP TABLE IF EXISTS sacco_shares_journal_account_line CASCADE")
        elif object_type == 'MATERIALIZED VIEW':
            self.env.cr.execute("DROP MATERIALIZED VIEW IF EXISTS sacco_shares_journal_account_line CASCADE")
        elif object_type == 'VIEW':
            self.env.cr.execute("DROP VIEW IF EXISTS sacco_shares_journal_account_line CASCADE")
        
        # Create the SQL view as a materialized view for better performance
        query = """
        CREATE MATERIALIZED VIEW sacco_shares_journal_account_line AS (
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
            original_shares_lines AS (
                SELECT
                    aml.move_id,
                    aml.id AS line_id,
                    aml.credit AS original_amount,
                    aml.member_id,
                    aml.name,
                    aml.partner_id,
                    sa.id AS shares_account_id
                FROM
                    account_move_line aml
                JOIN
                    res_partner rp ON aml.member_id = rp."member_id"
                JOIN
                    sacco_shares_account sa ON sa.member_id = rp.id
                JOIN
                    sacco_shares_product sp ON sa.product_id = sp.id
                WHERE
                    aml.credit > 0 AND
                    aml.account_id = sp.original_shares_product_account_id AND
                    aml.account_product_type = 'shares' AND
                    aml.member_id IS NOT NULL
            ),
            premium_shares_lines AS (
                SELECT
                    aml.move_id,
                    aml.id AS line_id,
                    aml.credit AS premium_amount,
                    aml.member_id,
                    sa.id AS shares_account_id
                FROM
                    account_move_line aml
                JOIN
                    res_partner rp ON aml.member_id = rp."member_id"
                JOIN
                    sacco_shares_account sa ON sa.member_id = rp.id
                JOIN
                    sacco_shares_product sp ON sa.product_id = sp.id
                WHERE
                    aml.credit > 0 AND
                    aml.account_id = sp.current_shares_product_account_id AND
                    aml.account_product_type = 'shares' AND
                    aml.member_id IS NOT NULL
            ),
            receiving_account_lines AS (
                SELECT
                    aml.move_id,
                    aml.id AS line_id,
                    aml.debit AS total_amount,
                    aml.partner_id,
                    aml.member_id
                FROM
                    account_move_line aml
                JOIN
                    account_account aa ON aml.account_id = aa.id
                WHERE
                    aml.debit > 0
            )
            
            SELECT
                ROW_NUMBER() OVER () AS id,
                COALESCE(osl.name, je.move_ref, 'Shares Transaction') AS name,
                osl.shares_account_id,
                je.move_date AS date,
                osl.move_id AS journal_entry_id,
                osl.line_id AS journal_line_id,
                'deposit' AS transaction_type,
                COALESCE(osl.original_amount, 0) AS original_shares_amount,
                COALESCE(psl.premium_amount, 0) AS premium_shares_amount,
                COALESCE(ral.total_amount, COALESCE(osl.original_amount, 0) + COALESCE(psl.premium_amount, 0)) AS total_amount,
                CASE
                    WHEN sp.original_shares_amount > 0 THEN COALESCE(osl.original_amount / sp.original_shares_amount, 0)
                    ELSE 0
                END AS number_of_shares
            FROM
                original_shares_lines osl
            JOIN
                journal_entries je ON osl.move_id = je.move_id
            JOIN
                sacco_shares_account sa ON osl.shares_account_id = sa.id
            JOIN
                sacco_shares_product sp ON sa.product_id = sp.id
            LEFT JOIN
                premium_shares_lines psl ON osl.move_id = psl.move_id AND osl.member_id = psl.member_id
            LEFT JOIN
                receiving_account_lines ral ON osl.move_id = ral.move_id AND osl.member_id = ral.member_id
            WHERE
                je.state = 'posted'
            ORDER BY
                je.move_date, osl.move_id
        )
        """
        
        self.env.cr.execute(query)
        
        # Create indexes for better performance
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS sacco_shares_journal_account_line_shares_account_id_idx 
            ON sacco_shares_journal_account_line (shares_account_id)
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS sacco_shares_journal_account_line_date_idx 
            ON sacco_shares_journal_account_line (date)
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