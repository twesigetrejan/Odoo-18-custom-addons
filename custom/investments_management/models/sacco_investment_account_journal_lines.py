from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class SaccoInvestmentAccountJournalLine(models.Model):
    _name = 'sacco.investment.account.journal.line'
    _description = 'SACCO Investment Account Journal Line'
    _auto = False  # Materialized view, no table creation
    _order = 'date asc, id asc'

    id = fields.Integer('ID', readonly=True)
    name = fields.Char('Description', readonly=True)
    investment_account_id = fields.Many2one('sacco.investments.account', string='Investment Account', readonly=True)
    date = fields.Date(string='Date', readonly=True)
    journal_entry_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    journal_line_id = fields.Many2one('account.move.line', string='Journal Item', readonly=True)
    type = fields.Selection([
        ('deposit', 'Deposit'),
        ('withdrawal', 'Withdrawal'),
        ('investment_purchase', 'Investment Purchase'),
        ('investment_sale', 'Investment Sale'),
        ('interest', 'Interest'),
        ('other', 'Other')
    ], string='Transaction Type', readonly=True)
    opening_cash_balance = fields.Float('Opening Cash Balance', readonly=True, digits='Account')
    opening_investment_balance = fields.Float('Opening Investment Balance', readonly=True, digits='Account')
    amount = fields.Float('Amount', readonly=True, digits='Account')
    closing_cash_balance = fields.Float('Closing Cash Balance', readonly=True, digits='Account')
    closing_investment_balance = fields.Float('Closing Investment Balance', readonly=True, digits='Account')
    currency_id = fields.Many2one(related='investment_account_id.currency_id', string='Currency')

    def init(self):
        """Initialize the SQL materialized view"""
        # Drop existing object if it exists
        self.env.cr.execute("""
            SELECT CASE 
                WHEN EXISTS (SELECT 1 FROM information_schema.tables 
                            WHERE table_name = 'sacco_investment_account_journal_line' 
                            AND table_type = 'BASE TABLE') 
                THEN 'TABLE'
                WHEN EXISTS (SELECT 1 FROM pg_matviews 
                            WHERE matviewname = 'sacco_investment_account_journal_line') 
                THEN 'MATERIALIZED VIEW'
                WHEN EXISTS (SELECT 1 FROM pg_views 
                            WHERE viewname = 'sacco_investment_account_journal_line') 
                THEN 'VIEW'
                ELSE 'NONE'
            END as object_type
        """)
        object_type = self.env.cr.fetchone()[0]
        
        if object_type == 'TABLE':
            self.env.cr.execute("DROP TABLE IF EXISTS sacco_investment_account_journal_line CASCADE")
        elif object_type == 'MATERIALIZED VIEW':
            self.env.cr.execute("DROP MATERIALIZED VIEW IF EXISTS sacco_investment_account_journal_line CASCADE")
        elif object_type == 'VIEW':
            self.env.cr.execute("DROP VIEW IF EXISTS sacco_investment_account_journal_line CASCADE")

        # Create materialized view with updated balance logic
        query = """
        CREATE MATERIALIZED VIEW sacco_investment_account_journal_line AS (
            WITH move_data AS (
                SELECT
                    aml.id,
                    aml.name,
                    ia.id AS investment_account_id,
                    aml.date,
                    aml.move_id AS journal_entry_id,
                    aml.id AS journal_line_id,
                    CASE
                        WHEN aml.account_id = ip.investments_product_cash_account_id AND aml.credit > 0 THEN 'deposit'
                        WHEN aml.account_id = ip.investments_product_cash_account_id AND aml.debit > 0 THEN 'withdrawal'
                        WHEN aml.account_id = ip.investments_product_account_id AND aml.credit > 0 THEN 'investment_purchase'
                        WHEN aml.account_id = ip.investments_product_account_id AND aml.debit > 0 THEN 'investment_sale'
                        WHEN aml.account_id = ip.investments_product_cash_profit_account_id AND aml.credit > 0 THEN 'interest'
                        ELSE 'other'
                    END AS type,
                    CASE
                        WHEN aml.account_id = ip.investments_product_cash_account_id AND aml.credit > 0 THEN aml.credit  -- Deposit increases cash
                        WHEN aml.account_id = ip.investments_product_cash_account_id AND aml.debit > 0 THEN -aml.debit  -- Withdrawal decreases cash
                        WHEN aml.account_id = ip.investments_product_account_id AND aml.credit > 0 THEN aml.credit  -- Sale increases investment
                        WHEN aml.account_id = ip.investments_product_account_id AND aml.debit > 0 THEN -aml.debit  -- Purchase decreases investment
                        WHEN aml.account_id = ip.investments_product_cash_profit_account_id AND aml.credit > 0 THEN aml.credit  -- Interest increases cash
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
                    sacco_investments_account ia ON ia.member_id = rp.id
                JOIN
                    sacco_investments_product ip ON ia.product_id = ip.id
                WHERE
                    am.state = 'posted'
                    AND (aml.account_id = ip.investments_product_account_id 
                         OR aml.account_id = ip.investments_product_cash_account_id 
                         OR aml.account_id = ip.investments_product_cash_profit_account_id)
                    AND aml.member_id IS NOT NULL
                ORDER BY
                    ia.id, aml.date, aml.id
            ),
            running_balance AS (
                SELECT
                    md.id,
                    md.name,
                    md.investment_account_id,
                    md.date,
                    md.journal_entry_id,
                    md.journal_line_id,
                    md.type,
                    md.amount,
                    SUM(CASE 
                        WHEN md.type = 'deposit' THEN md.amount 
                        WHEN md.type = 'withdrawal' THEN md.amount 
                        WHEN md.type = 'interest' THEN md.amount 
                        ELSE 0 
                    END) OVER (
                        PARTITION BY md.investment_account_id
                        ORDER BY md.row_date, md.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS closing_cash_balance,
                    SUM(CASE 
                        WHEN md.type = 'investment_purchase' THEN md.amount 
                        WHEN md.type = 'investment_sale' THEN md.amount 
                        ELSE 0 
                    END) OVER (
                        PARTITION BY md.investment_account_id
                        ORDER BY md.row_date, md.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS closing_investment_balance,
                    COALESCE(SUM(CASE 
                        WHEN md.type = 'deposit' THEN md.amount 
                        WHEN md.type = 'withdrawal' THEN md.amount 
                        WHEN md.type = 'interest' THEN md.amount 
                        ELSE 0 
                    END) OVER (
                        PARTITION BY md.investment_account_id
                        ORDER BY md.row_date, md.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0) AS opening_cash_balance,
                    COALESCE(SUM(CASE 
                        WHEN md.type = 'investment_purchase' THEN md.amount 
                        WHEN md.type = 'investment_sale' THEN md.amount 
                        ELSE 0 
                    END) OVER (
                        PARTITION BY md.investment_account_id
                        ORDER BY md.row_date, md.id
                        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                    ), 0) AS opening_investment_balance
                FROM
                    move_data md
            )
            SELECT
                rb.id,
                COALESCE(rb.name, 'Transaction') as name,
                rb.investment_account_id,
                rb.date,
                rb.journal_entry_id,
                rb.journal_line_id,
                rb.type,
                ABS(rb.amount) as amount,
                rb.opening_cash_balance,
                rb.closing_cash_balance,
                rb.opening_investment_balance,
                rb.closing_investment_balance
            FROM
                running_balance rb
            ORDER BY
                rb.investment_account_id, rb.date, rb.id
        )
        """
        self.env.cr.execute(query)

        # Create indexes
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS sacco_investment_account_journal_line_investment_account_id_idx 
            ON sacco_investment_account_journal_line (investment_account_id)
        """)
        self.env.cr.execute("""
            CREATE INDEX IF NOT EXISTS sacco_investment_account_journal_line_date_idx 
            ON sacco_investment_account_journal_line (date)
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