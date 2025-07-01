from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime, timedelta
import logging
_logger = logging.getLogger(__name__)

class InvestmentPool(models.Model):
    _name = 'sacco.investments.pool'
    _description = 'Investment Pool'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    
    name = fields.Char('Pool ID', default='/', copy=False, required=True)
    investment_product_id = fields.Many2one('sacco.investments.product', string='Investment Product', required=True)
    target_amount = fields.Float('Target Investment Amount', required=True)
    start_date = fields.Date('Start Date', default=fields.Date.today)
    end_date = fields.Date('End Date')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('collecting', 'Collecting Funds'),
        ('invested', 'Invested'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled')
    ], default='draft', string='Status', tracking=True)
    
    collected_amount = fields.Float('Total Collected Amount', compute='_compute_collected_amount', store=True)
    remaining_amount = fields.Float('Remaining Amount', compute='_compute_remaining_amount', store=True)
    actual_invested_amount = fields.Float('Actually Invested Amount', compute='_compute_actual_invested_amount', store=True)
    investment_duration = fields.Float('Investment Duration (Years)', compute='_compute_duration')
    participant_ids = fields.One2many('sacco.investments.pool.participant', 'pool_id', string='Participants')
    minimum_balance = fields.Float('Minimum Balance Required', related='investment_product_id.minimum_balance')
    actual_interest_rate = fields.Float('Actual Interest Rate (%)')
    maturity_date = fields.Date('Maturity Date')
    current_profit = fields.Float('Current Profit to Distribute', compute='_compute_current_profit', store=True, readonly=True, force_save="1",
                                  help="The current balance available in the investment profit expense account.")
    total_distributed_profit = fields.Float('Total Distributed Profit', compute='_compute_total_distributed_profit', store=True)
    last_profit_distribution = fields.Date('Last Profit Distribution Date')
    interest_transaction_ids = fields.One2many(
        'sacco.investments.transaction',
        'investment_pool_id',
        string='Interest Transactions',
        domain=[('transaction_type', '=', 'interest'), ('status', '=', 'confirmed')]
    )
    investment_profit_expense_account_id = fields.Many2one(
        'account.account', string='Investment Profit Expense Account',
        domain="[('account_type', '=', 'expense')]",
        required=True,
        help="The expense account where profits are recorded before distribution.",
        tracking=True
    )
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    def unlink(self):
        for pool in self:
            if pool.state != 'draft':
                raise ValidationError(_("You can only delete draft investment pools."))
        return super(InvestmentPool, self).unlink()
    
    @api.depends('participant_ids.investments_account_id.cash_balance')
    def _compute_collected_amount(self):
        for pool in self:
            pool.collected_amount = sum(participant.investments_account_id.cash_balance 
                                      for participant in pool.participant_ids)
    
    @api.depends('participant_ids.actual_invested_amount')
    def _compute_actual_invested_amount(self):
        for pool in self:
            pool.actual_invested_amount = sum(pool.participant_ids.mapped('actual_invested_amount'))

    @api.depends('target_amount', 'actual_invested_amount')
    def _compute_remaining_amount(self):
        for pool in self:
            pool.remaining_amount = pool.target_amount - pool.actual_invested_amount

    @api.depends('start_date', 'end_date')
    def _compute_duration(self):
        for pool in self:
            if pool.start_date and pool.end_date:
                delta = pool.end_date - pool.start_date
                pool.investment_duration = delta.days / 365.0
            else:
                pool.investment_duration = 0.0

    @api.depends('interest_transaction_ids.amount', 'interest_transaction_ids.status')
    def _compute_total_distributed_profit(self):
        for pool in self:
            pool.total_distributed_profit = sum(
                transaction.amount 
                for transaction in pool.interest_transaction_ids.filtered(
                    lambda t: t.status == 'confirmed'
                )
            )


    @api.depends('investment_profit_expense_account_id', 'company_id')
    def _compute_current_profit(self):
        """Compute the current profit as the balance of the investment profit expense account.
        Credits are considered positive (profit), debits are considered negative (loss)."""
        for pool in self:
            if not pool.investment_profit_expense_account_id:
                _logger.warning("No investment profit expense account set for pool %s (ID: %s)", pool.name, pool.id)
                pool.current_profit = 0.0
                continue

            # Log the account and company details
            _logger.info("Computing current profit for pool %s (ID: %s), Account ID: %s, Company ID: %s",
                        pool.name, pool.id, pool.investment_profit_expense_account_id.id, pool.company_id.id or "No Company")

            # Use SQL query to sum credits and debits for posted journal entries
            query = """
                SELECT 
                    COALESCE(SUM(credit), 0.0) as total_credit,
                    COALESCE(SUM(debit), 0.0) as total_debit
                FROM account_move_line aml
                JOIN account_move am ON aml.move_id = am.id
                WHERE aml.account_id = %s
                AND am.state = 'posted'
            """
            params = [pool.investment_profit_expense_account_id.id]

            # Add company filter if company_id is set
            if pool.company_id:
                query += " AND aml.company_id = %s"
                params.append(pool.company_id.id)

            self.env.cr.execute(query, params)
            result = self.env.cr.fetchone()

            if result:
                total_credit, total_debit = result
                pool.current_profit = total_credit - total_debit
                _logger.info("Pool %s (ID: %s): Total Credit = %s, Total Debit = %s, Current Profit = %s",
                            pool.name, pool.id, total_credit, total_debit, pool.current_profit)
            else:
                pool.current_profit = 0.0
                _logger.warning("No posted journal entries found for account %s (ID: %s) for pool %s (ID: %s)",
                                pool.investment_profit_expense_account_id.name,
                                pool.investment_profit_expense_account_id.id,
                                pool.name, pool.id)

    def action_start_collection(self):
        self.ensure_one()
        if self.target_amount <= 0:
            raise ValidationError(_("Target amount must be greater than zero."))
        for participant in self.participant_ids:
            participant.state = 'confirmed' 
        self.state = 'collecting'

    def action_mark_as_invested(self):
        self.ensure_one()
        if self.actual_invested_amount < self.target_amount:
            raise ValidationError(_("Cannot invest until target amount is reached."))
        
        self.state = 'invested'
        self._create_investment_purchases()
        self._create_investment_entries()

    def action_distribute_profits(self):
        """Distribute the current profit amount among participants based on the expense account balance."""
        self.ensure_one()
        
        if self.current_profit <= 0:
            raise ValidationError(_("No profits available to distribute. The current profit balance is zero or negative (indicating losses)."))
            
        if self.state != 'invested':
            raise ValidationError(_("Profits can only be distributed when the pool is in invested state."))
            
        total_invested = sum(self.participant_ids.mapped('actual_invested_amount'))
        if not total_invested:
            raise ValidationError(_("No investments found to distribute profits."))

        # Log initial values
        _logger.info("Starting profit distribution for pool %s (ID: %s)", self.name, self.id)
        _logger.info("Total Invested Amount: %s, Current Profit to Distribute: %s", total_invested, self.current_profit)

        # Get the currency
        currency = self.investment_product_id.currency_id
        total_profit = currency.round(self.current_profit)

        # Create journal entry to distribute profits
        journal = self.investment_product_id.investments_product_journal_id
        if not journal:
            raise ValidationError(_("No journal configured for the investment product."))

        move_vals = {
            'date': fields.Date.today(),
            'ref': f"Profit Distribution for {self.name}",
            'journal_id': journal.id,
            'company_id': journal.company_id.id,
        }
        move_lines = []

        # Calculate profit shares with currency precision
        profit_shares = []
        participants_list = self.participant_ids.filtered(lambda p: p.actual_invested_amount > 0)
        _logger.info("Number of participants with investments: %s", len(participants_list))

        for participant in participants_list:
            contribution_ratio = participant.actual_invested_amount / total_invested
            profit_share = currency.round(self.current_profit * contribution_ratio)
            profit_shares.append((participant, profit_share))
            _logger.info("Participant %s (ID: %s): Contribution Ratio: %s, Initial Profit Share: %s",
                        participant.member_id.name, participant.id, contribution_ratio, profit_share)

        # Adjust profit shares to match total_profit
        total_rounded = sum(profit_share for _, profit_share in profit_shares)
        difference = total_profit - total_rounded

        if difference != 0:
            # Adjust the largest profit share
            max_index = max(range(len(profit_shares)), key=lambda i: profit_shares[i][1])
            participant, profit_share = profit_shares[max_index]
            adjusted_profit_share = profit_share + difference
            profit_shares[max_index] = (participant, adjusted_profit_share)
            _logger.info("Adjusting profit share for Participant %s (ID: %s): From %s to %s",
                        participant.member_id.name, participant.id, profit_share, adjusted_profit_share)

        # Debit line with total_profit
        move_lines.append((0, 0, {
            'account_id': self.investment_profit_expense_account_id.id,
            'debit': total_profit,
            'credit': 0.0,
            'name': f"Profit Distribution: {self.name}",
            'date_maturity': fields.Date.today(),
        }))

        # Credit lines and transactions
        transactions = []
        for participant, profit_share in profit_shares:
            participant.profit_earned = profit_share
            participant.total_profit_earned = participant.total_profit_earned + profit_share

            move_lines.append((0, 0, {
                'partner_id': participant.member_id.id,
                'account_id': self.investment_product_id.investments_product_cash_profit_account_id.id,
                'credit': profit_share,
                'debit': 0.0,
                'name': f"Profit Share: {participant.member_id.name} - {self.name}",
                'date_maturity': fields.Date.today(),
                'member_id': participant.member_id.member_id if participant.member_id.member_id else False,
            }))

            # Create interest transaction
            transaction = self.env['sacco.investments.transaction'].create({
                'investments_account_id': participant.investments_account_id.id,
                'transaction_type': 'interest',
                'member_id': participant.member_id.id,
                'product_id': self.investment_product_id.id,
                'amount': profit_share,
                'transaction_date': fields.Date.today(),
                'status': 'pending',
                'investment_pool_id': self.id,
            })
            transactions.append(transaction)

        # Log journal entry details
        total_debit = sum(line[2]['debit'] for line in move_lines)
        total_credit = sum(line[2]['credit'] for line in move_lines)
        _logger.info("Journal Entry Summary - Total Debit: %s, Total Credit: %s", total_debit, total_credit)
        for line in move_lines:
            _logger.info("Move Line: Account ID %s, Debit: %s, Credit: %s, Name: %s",
                        line[2]['account_id'], line[2]['debit'], line[2]['credit'], line[2]['name'])

        # Create and post the journal entry
        move = self.env['account.move'].create(move_vals)
        move.line_ids = move_lines
        move.action_post()

        # Confirm transactions
        for transaction in transactions:
            transaction.journal_entry_id = move.id
            transaction.action_confirm_transaction()
            transaction.investments_account_id.action_refresh_journal_lines()

        # Update pool records
        self.write({
            'last_profit_distribution': fields.Date.today(),
        })
        
        self._compute_current_profit()
        _logger.info("Profit distribution completed for pool %s (ID: %s)", self.name, self.id)

    def action_complete_investment(self):
        self.ensure_one()
        if self.state != 'invested':
            raise ValidationError(_("Only invested pools can be marked as completed."))
        self.write({
            'state': 'completed',
            'end_date': fields.Date.today()
        })
        self.participant_ids.write({'state': 'completed'})

    def _create_investment_purchases(self):
        for participant in self.participant_ids:
            if participant.actual_invested_amount > 0:
                participant.state = 'invested'
                transaction = self.env['sacco.investments.transaction'].create({
                    'investments_account_id': participant.investments_account_id.id,
                    'transaction_type': 'investment_purchase',
                    'member_id': participant.member_id.id,
                    'product_id': self.investment_product_id.id,
                    'amount': participant.actual_invested_amount,
                    'transaction_date': fields.Date.today(),
                    'status': 'pending',
                    'investment_pool_id': self.id,
                })
                transaction.action_confirm_transaction() 
                       
    def _create_investment_entries(self):
        pass 

    def calculate_individual_investments(self):
        if self.participant_ids:
            for participant in self.participant_ids:
                participant.with_context({'force_delete':True}).unlink()
                
        eligible_accounts = self.env['sacco.investments.account'].search([
            ('state', '=', 'active'),
            ('product_id', '=', self.investment_product_id.id)
        ])

        total_available = sum(account.cash_balance for account in eligible_accounts)
        if total_available < self.target_amount:
            raise ValidationError(_("Insufficient total funds available for investment."))

        for account in eligible_accounts:
            contribution_amount = account.cash_balance
            proportion = account.cash_balance / total_available
            investment_amount = self.target_amount * proportion
            
            if (account.cash_balance - investment_amount) < self.minimum_balance:
                max_investment = account.cash_balance - self.minimum_balance
                if max_investment > 0:
                    self._create_pool_participant(account, contribution_amount, max_investment)
            else:
                self._create_pool_participant(account, contribution_amount, investment_amount)

    def _create_pool_participant(self, account, contribution_amount, investment_amount):
        return self.env['sacco.investments.pool.participant'].create({
            'pool_id': self.id,
            'investments_account_id': account.id,
            'contribution_amount': contribution_amount,  
            'actual_invested_amount': investment_amount, 
            'state': 'draft'
        })