# -*- coding: utf-8 -*-
import logging
from datetime import timedelta
from odoo import models, fields, api, _
from odoo.tools import get_lang, format_date
from odoo.exceptions import UserError
from collections import defaultdict

_logger = logging.getLogger(__name__)

class MemberLedgerReportHandler(models.AbstractModel):
    _name = 'member.ledger.report.handler'
    _inherit = 'account.report.custom.handler'
    _description = 'Member Ledger Report Handler'

    def _get_custom_display_config(self):
        """Customize the UI of the report."""
        return {
            'templates': {
                'AccountReportLineName': 'sacco_transactions_management.MemberLedgerLineName',
            },
        }

    def _custom_options_initializer(self, report, options, previous_options=None):
        """Initialize custom options for the report."""
        super()._custom_options_initializer(report, options, previous_options=previous_options)

        # Remove multi-currency columns since we don't need them
        options['columns'] = [
            column for column in options['columns']
            if column['expression_label'] != 'amount_currency'
        ]

        # Ensure all existing columns have a column_group_key (if not already present)
        default_column_group_key = next(iter(options['column_groups']), 'default')  # Use the first column group or a fallback
        for column in options['columns']:
            if 'column_group_key' not in column:
                column['column_group_key'] = default_column_group_key

        # Add Share Number column with a column_group_key
        options['columns'].append({
            'name': _('Share Number'),
            'expression_label': 'share_number',
            'sortable': True,
            'figure_type': 'float',
            'column_group_key': default_column_group_key,  # Add this key
        })

        # Automatically unfold the report when printing, unless specific lines are unfolded
        options['unfold_all'] = (options['export_mode'] == 'print' and not options.get('unfolded_lines')) or options['unfold_all']

        # Add a custom filter to ensure only the Member Journal is selected
        member_journal_id = self.env['sacco.helper'].get_member_journal_id()
        options['journal_ids'] = [member_journal_id]

        # Base domain
        forced_domain = [
            ('journal_id', '=', member_journal_id),
            ('move_id.state', '=', 'posted'),
            ('account_product_type', 'in', self.env['sacco.helper'].get_member_account_product_types()),
        ]

        # Add member_id filter if provided
        if options.get('member_id'):
            member_id = options['member_id']
            if isinstance(member_id, str) and member_id.isdigit():
                member_id = int(member_id)
            forced_domain.append(('member_id', '=', member_id))

        options['forced_domain'] = forced_domain

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals, warnings=None):
        """Generate the dynamic lines for the report."""
        lines = []
        date_from = fields.Date.from_string(options['date']['date_from'])
        company_currency = self.env.company.currency_id

        # Step 1: Fetch all account move lines for the accounts in the report
        accounts_results = self._query_values(report, options)
        account_ids = [account.id for account, _ in accounts_results]

        # Step 2: Fetch move totals for all moves involved, only summing equity lines
        aml_query, aml_params = self._get_query_amls(report, options, account_ids)
        self._cr.execute(aml_query, aml_params)
        aml_results = self._cr.dictfetchall()
        move_ids = set(aml['move_id'] for aml in aml_results if aml.get('move_id'))
        move_totals = {}
        if move_ids:
            move_totals_query = """
                SELECT
                    move.id AS move_id,
                    SUM(line.debit) AS total_debit,
                    SUM(line.credit) AS total_credit
                FROM account_move move
                JOIN account_move_line line ON line.move_id = move.id
                JOIN account_account account ON account.id = line.account_id
                WHERE move.id IN %s
                AND account.account_type LIKE 'equity%%'
                GROUP BY move.id
            """
            self._cr.execute(move_totals_query, [tuple(move_ids)])
            move_totals = {row['move_id']: {'total_debit': row['total_debit'], 'total_credit': row['total_credit']} for row in self._cr.dictfetchall()}

        # Step 3: Fetch account types
        accounts = self.env['account.account'].browse(account_ids)
        account_types = {account.id: account.account_type for account in accounts}

        # Step 4: Compute totals for each account
        totals_by_column_group = defaultdict(lambda: {'debit': 0, 'credit': 0})
        for account, column_group_results in accounts_results:
            eval_dict = {}
            has_lines = False
            is_shares_account = False
            is_equity_account = account_types.get(account.id, '').startswith('equity')

            # Check if the account is a shares account (we need to inspect the account.move.line records)
            for aml in aml_results:
                if aml['account_id'] == account.id and aml.get('account_product_type') == 'shares':
                    is_shares_account = True
                    break

            # For shares accounts in the equity family, use move_totals
            if is_shares_account and is_equity_account:
                account_debit = 0.0
                account_credit = 0.0
                account_balance = 0.0
                processed_moves = set()
                for aml in aml_results:
                    if aml['account_id'] == account.id:
                        move_id = aml['move_id']
                        if move_id in move_totals and move_id not in processed_moves:
                            move_total = move_totals[move_id]
                            account_debit += move_total['total_debit']
                            account_credit += move_total['total_credit']
                            account_balance += (move_total['total_debit'] - move_total['total_credit'])
                            processed_moves.add(move_id)
                        max_date = aml.get('date')
                        has_lines = has_lines or (max_date and max_date >= date_from)
            else:
                # For non-shares or non-equity accounts, use the default aggregation
                for column_group_key, results in column_group_results.items():
                    account_sum = results.get('sum', {})
                    account_un_earn = results.get('unaffected_earnings', {})

                    account_debit = account_sum.get('debit', 0.0) + account_un_earn.get('debit', 0.0)
                    account_credit = account_sum.get('credit', 0.0) + account_un_earn.get('credit', 0.0)
                    account_balance = account_sum.get('balance', 0.0) + account_un_earn.get('balance', 0.0)

                    max_date = account_sum.get('max_date')
                    has_lines = has_lines or (max_date and max_date >= date_from)

            # Populate eval_dict for the current column group
            for column_group_key in options['column_groups']:
                eval_dict[column_group_key] = {
                    'debit': account_debit,
                    'credit': account_credit,
                    'balance': account_balance,
                }
                totals_by_column_group[column_group_key]['debit'] += account_debit
                totals_by_column_group[column_group_key]['credit'] += account_credit

            lines.append(self._get_account_title_line(report, options, account, has_lines, eval_dict))

        # Total line
        for totals in totals_by_column_group.values():
            totals['balance'] = company_currency.round(totals.get('balance', 0.0))

        lines.append(self._get_total_line(report, options, totals_by_column_group))

        return [(0, line) for line in lines]

    def _custom_unfold_all_batch_data_generator(self, report, options, lines_to_expand_by_function):
        """Generate batch data for unfolding all lines."""
        account_ids_to_expand = []
        for line_dict in lines_to_expand_by_function.get('_report_expand_unfoldable_line_member_ledger', []):
            model, model_id = report._get_model_info_from_id(line_dict['id'])
            if model == 'account.account':
                account_ids_to_expand.append(model_id)

        limit_to_load = report.load_more_limit if report.load_more_limit and not options.get('export_mode') else None
        has_more_per_account_id = {}

        unlimited_aml_results_per_account_id = self._get_aml_values(report, options, account_ids_to_expand)[0]
        if limit_to_load:
            aml_results_per_account_id = {}
            for account_id, account_aml_results in unlimited_aml_results_per_account_id.items():
                account_values = {}
                for key, value in account_aml_results.items():
                    if len(account_values) == limit_to_load:
                        has_more_per_account_id[account_id] = True
                        break
                    account_values[key] = value
                aml_results_per_account_id[account_id] = account_values
        else:
            aml_results_per_account_id = unlimited_aml_results_per_account_id

        return {
            'initial_balances': self._get_initial_balance_values(report, account_ids_to_expand, options),
            'aml_results': aml_results_per_account_id,
            'has_more': has_more_per_account_id,
        }

    def _query_values(self, report, options):
        """Execute queries and perform computations for the report."""
        query, params = self._get_query_sums(report, options)

        if not query:
            return []

        groupby_accounts = {}
        groupby_companies = {}

        self._cr.execute(query, params)
        for res in self._cr.dictfetchall():
            if res['groupby'] is None:
                continue

            column_group_key = res['column_group_key']
            key = res['key']
            if key == 'sum':
                groupby_accounts.setdefault(res['groupby'], {col_group_key: {} for col_group_key in options['column_groups']})
                groupby_accounts[res['groupby']][column_group_key][key] = res
            elif key == 'initial_balance':
                groupby_accounts.setdefault(res['groupby'], {col_group_key: {} for col_group_key in options['column_groups']})
                groupby_accounts[res['groupby']][column_group_key][key] = res
            elif key == 'unaffected_earnings':
                groupby_companies.setdefault(res['groupby'], {col_group_key: {} for col_group_key in options['column_groups']})
                groupby_companies[res['groupby']][column_group_key] = res

        if groupby_companies:
            candidates_account_ids = self.env['account.account']._name_search('', [
                *self.env['account.account']._check_company_domain(list(groupby_companies.keys())),
                ('account_type', '=', 'equity_unaffected'),
            ])
            for account in self.env['account.account'].browse(candidates_account_ids):
                company_unaffected_earnings = groupby_companies.get(account.company_id.id)
                if not company_unaffected_earnings:
                    continue
                for column_group_key in options['column_groups']:
                    unaffected_earnings = company_unaffected_earnings[column_group_key]
                    groupby_accounts.setdefault(account.id, {col_group_key: {} for col_group_key in options['column_groups']})
                    groupby_accounts[account.id][column_group_key]['unaffected_earnings'] = unaffected_earnings
                del groupby_companies[account.company_id.id]

        if groupby_accounts:
            accounts = self.env['account.account'].search([('id', 'in', list(groupby_accounts.keys()))])
        else:
            accounts = []

        return [(account, groupby_accounts[account.id]) for account in accounts]

    def _get_query_sums(self, report, options):
        """Construct a query to retrieve aggregated sums for the report."""
        options_by_column_group = report._split_options_per_column_group(options)

        params = []
        queries = []
        ct_query = report._get_query_currency_table(options)

        for column_group_key, options_group in options_by_column_group.items():
            if not options.get('member_ledger_strict_range'):
                options_group = self._get_options_sum_balance(options_group)

            sum_date_scope = 'strict_range' if options_group.get('member_ledger_strict_range') else 'normal'
            query_domain = options_group.get('forced_domain', [])  # Include forced_domain with member_id filter

            tables, where_clause, where_params = report._query_get(options_group, sum_date_scope, domain=query_domain)
            params.append(column_group_key)
            params += where_params
            queries.append(f"""
                SELECT
                    account_move_line.account_id                            AS groupby,
                    'sum'                                                   AS key,
                    MAX(account_move_line.date)                             AS max_date,
                    %s                                                      AS column_group_key,
                    COALESCE(SUM(account_move_line.amount_currency), 0.0)   AS amount_currency,
                    SUM(ROUND(account_move_line.debit * currency_table.rate, currency_table.precision))   AS debit,
                    SUM(ROUND(account_move_line.credit * currency_table.rate, currency_table.precision))  AS credit,
                    SUM(ROUND(account_move_line.balance * currency_table.rate, currency_table.precision)) AS balance
                FROM {tables}
                LEFT JOIN {ct_query} ON currency_table.company_id = account_move_line.company_id
                WHERE {where_clause}
                GROUP BY account_move_line.account_id
            """)

            # Unaffected earnings query (if applicable)
            if not options_group.get('member_ledger_strict_range'):
                unaff_earnings_domain = [('account_id.include_initial_balance', '=', False)]
                new_options = self._get_options_unaffected_earnings(options_group)
                tables, where_clause, where_params = report._query_get(new_options, 'strict_range', domain=unaff_earnings_domain + query_domain)
                params.append(column_group_key)
                params += where_params
                queries.append(f"""
                    SELECT
                        account_move_line.company_id                            AS groupby,
                        'unaffected_earnings'                                   AS key,
                        NULL                                                    AS max_date,
                        %s                                                      AS column_group_key,
                        COALESCE(SUM(account_move_line.amount_currency), 0.0)   AS amount_currency,
                        SUM(ROUND(account_move_line.debit * currency_table.rate, currency_table.precision))   AS debit,
                        SUM(ROUND(account_move_line.credit * currency_table.rate, currency_table.precision))  AS credit,
                        SUM(ROUND(account_move_line.balance * currency_table.rate, currency_table.precision)) AS balance
                    FROM {tables}
                    LEFT JOIN {ct_query} ON currency_table.company_id = account_move_line.company_id
                    WHERE {where_clause}
                    GROUP BY account_move_line.company_id
                """)

        return ' UNION ALL '.join(queries), params

    def _get_options_unaffected_earnings(self, options):
        """Create options to compute unaffected earnings."""
        new_options = options.copy()
        fiscalyear_dates = self.env.company.compute_fiscalyear_dates(fields.Date.from_string(options['date']['date_from']))
        new_date_to = fiscalyear_dates['date_from'] - timedelta(days=1)

        new_options['date'] = {
            'mode': 'single',
            'date_to': fields.Date.to_string(new_date_to),
        }
        return new_options

    def _get_aml_values(self, report, options, expanded_account_ids, offset=0, limit=None):
        """Retrieve account move lines for expanded accounts."""
        _logger.info("Entering _get_aml_values with expanded_account_ids: %s", expanded_account_ids)
        rslt = {account_id: {} for account_id in expanded_account_ids}
        aml_query, aml_params = self._get_query_amls(report, options, expanded_account_ids, offset=offset, limit=limit)
        self._cr.execute(aml_query, aml_params)
        aml_results_number = 0
        has_more = False

        # Step 1: Fetch all account move lines
        aml_results = self._cr.dictfetchall()
        _logger.info("Fetched %d account move lines: %s", len(aml_results), aml_results)

        # Step 2: Group move IDs to fetch their totals, only summing lines with account_type starting with 'equity'
        move_ids = set(aml['move_id'] for aml in aml_results if aml.get('move_id'))
        move_totals = {}
        if move_ids:
            move_totals_query = """
                SELECT
                    move.id AS move_id,
                    SUM(line.debit) AS total_debit,
                    SUM(line.credit) AS total_credit
                FROM account_move move
                JOIN account_move_line line ON line.move_id = move.id
                JOIN account_account account ON account.id = line.account_id
                WHERE move.id IN %s
                AND account.account_type LIKE 'equity%%'
                GROUP BY move.id
            """
            self._cr.execute(move_totals_query, [tuple(move_ids)])
            move_totals = {row['move_id']: {'total_debit': row['total_debit'], 'total_credit': row['total_credit']} for row in self._cr.dictfetchall()}
            _logger.info("Fetched move totals for %d moves (only equity accounts): %s", len(move_totals), move_totals)

        # Step 3: Fetch account types to identify shares accounts in the equity family
        account_ids = set(aml['account_id'] for aml in aml_results)
        accounts = self.env['account.account'].browse(account_ids)
        account_types = {account.id: account.account_type for account in accounts}
        _logger.info("Account types: %s", account_types)

        # Step 4: Process each account move line
        for aml_result in aml_results:
            aml_results_number += 1
            if limit and aml_results_number > limit:
                has_more = True
                break

            if aml_result['ref']:
                aml_result['communication'] = f"{aml_result['ref']} - {aml_result['name']}"
            else:
                aml_result['communication'] = aml_result['name']

            # Check if the account is a shares account and belongs to the equity family
            account_id = aml_result['account_id']
            account_type = account_types.get(account_id, '')
            is_shares_account = aml_result.get('account_product_type') == 'shares'
            is_equity_account = account_type.startswith('equity')
            original_shares_amount = aml_result.get('original_shares_amount', 0.0)

            _logger.info(
                "Processing AML ID %s: account_id=%s, account_product_type=%s, account_type=%s, is_shares_account=%s, is_equity_account=%s, move_id=%s",
                aml_result['id'], account_id, aml_result.get('account_product_type'), account_type, is_shares_account, is_equity_account, aml_result.get('move_id')
            )
            
            if is_shares_account and is_equity_account and original_shares_amount > 0:
                move_id = aml_result.get('move_id')
                if move_id in move_totals:
                    move_total = move_totals[move_id]
                    balance = move_total['total_debit'] - move_total['total_credit']
                    aml_result['share_number'] = balance / original_shares_amount
                else:
                    aml_result['share_number'] = 0.0
            else:
                aml_result['share_number'] = 0.0

            # If it's a shares account in the equity family, replace the amounts with the account.move total (only equity lines)
            if is_shares_account and is_equity_account:
                move_id = aml_result.get('move_id')
                if move_id in move_totals:
                    move_total = move_totals[move_id]
                    _logger.info(
                        "Replacing amounts for AML ID %s: original debit=%s, credit=%s, balance=%s; new debit=%s, credit=%s, balance=%s",
                        aml_result['id'], aml_result['debit'], aml_result['credit'], aml_result['balance'],
                        move_total['total_debit'], move_total['total_credit'], move_total['total_debit'] - move_total['total_credit']
                    )
                    aml_result['debit'] = move_total['total_debit']
                    aml_result['credit'] = move_total['total_credit']
                    aml_result['balance'] = move_total['total_debit'] - move_total['total_credit']
                    aml_result['amount_currency'] = aml_result['balance']
                else:
                    _logger.warning("Move ID %s not found in move_totals for AML ID %s", move_id, aml_result['id'])

            aml_key = (aml_result['id'], aml_result['date'])
            account_result = rslt[aml_result['account_id']]
            if aml_key not in account_result:
                account_result[aml_key] = {col_group_key: {} for col_group_key in options['column_groups']}

            already_present_result = account_result[aml_key][aml_result['column_group_key']]
            if already_present_result:
                already_present_result['debit'] += aml_result['debit']
                already_present_result['credit'] += aml_result['credit']
                already_present_result['balance'] += aml_result['balance']
                already_present_result['amount_currency'] += aml_result['amount_currency']
                already_present_result['share_number'] += aml_result['share_number']
            else:
                account_result[aml_key][aml_result['column_group_key']] = aml_result

        _logger.info("Returning results for %d accounts, has_more=%s", len(rslt), has_more)
        return rslt, has_more

    def _get_query_amls(self, report, options, expanded_account_ids, offset=0, limit=None):
        """Construct a query to retrieve account move lines."""
        additional_domain = [('account_id', 'in', expanded_account_ids)] if expanded_account_ids is not None else None
        queries = []
        all_params = []
        lang = self.env.user.lang or get_lang(self.env).code
        journal_name = f"COALESCE(journal.name->>'{lang}', journal.name->>'en_US')" if \
            self.pool['account.journal'].name.translate else 'journal.name'
        account_name = f"COALESCE(account.name->>'{lang}', account.name->>'en_US')" if \
            self.pool['account.account'].name.translate else 'account.name'

        for column_group_key, group_options in report._split_options_per_column_group(options).items():
            domain = group_options.get('forced_domain', [])  # Include forced_domain with member_id filter
            if additional_domain:
                domain += additional_domain
            tables, where_clause, where_params = report._query_get(group_options, 'strict_range', domain=domain)
            ct_query = report._get_query_currency_table(group_options)
            query = f'''
                    (SELECT
                        account_move_line.id,
                        account_move_line.date,
                        account_move_line.name,
                        account_move_line.ref,
                        account_move_line.company_id,
                        account_move_line.account_id,
                        account_move_line.move_id,
                        account_move_line.payment_id,
                        account_move_line.partner_id,
                        account_move_line.currency_id,
                        account_move_line.amount_currency,
                        COALESCE(account_move_line.invoice_date, account_move_line.date) AS invoice_date,
                        ROUND(account_move_line.debit * currency_table.rate, currency_table.precision) AS debit,
                        ROUND(account_move_line.credit * currency_table.rate, currency_table.precision) AS credit,
                        ROUND(account_move_line.balance * currency_table.rate, currency_table.precision) AS balance,
                        move.name AS move_name,
                        company.currency_id AS company_currency_id,
                        partner.name AS partner_name,
                        move.move_type AS move_type,
                        account.code AS account_code,
                        {account_name} AS account_name,
                        journal.code AS journal_code,
                        {journal_name} AS journal_name,
                        full_rec.id AS full_rec_name,
                        account_move_line.member_id AS member_id,
                        account_move_line.account_product_type AS account_product_type,
                        account.original_shares_amount AS original_shares_amount,  -- Add this line
                        %s AS column_group_key
                    FROM {tables}
                    JOIN account_move move ON move.id = account_move_line.move_id
                    LEFT JOIN {ct_query} ON currency_table.company_id = account_move_line.company_id
                    LEFT JOIN res_company company ON company.id = account_move_line.company_id
                    LEFT JOIN res_partner partner ON partner.id = account_move_line.partner_id
                    LEFT JOIN account_account account ON account.id = account_move_line.account_id
                    LEFT JOIN account_journal journal ON journal.id = account_move_line.journal_id
                    LEFT JOIN account_full_reconcile full_rec ON full_rec.id = account_move_line.full_reconcile_id
                    WHERE {where_clause}
                    ORDER BY account_move_line.date, account_move_line.move_name, account_move_line.id)
                '''

            queries.append(query)
            all_params.append(column_group_key)
            all_params += where_params

        full_query = " UNION ALL ".join(queries)

        if offset:
            full_query += ' OFFSET %s '
            all_params.append(offset)
        if limit:
            full_query += ' LIMIT %s '
            all_params.append(limit)

        return full_query, all_params

    def _get_initial_balance_values(self, report, account_ids, options):
        """Get sums for the initial balance."""
        queries = []
        params = []
        for column_group_key, options_group in report._split_options_per_column_group(options).items():
            new_options = self._get_options_initial_balance(options_group)
            ct_query = report._get_query_currency_table(new_options)
            domain = [('account_id', 'in', account_ids)]
            if new_options.get('include_current_year_in_unaff_earnings'):
                domain += [('account_id.include_initial_balance', '=', True)]
            tables, where_clause, where_params = report._query_get(new_options, 'normal', domain=domain)
            params.append(column_group_key)
            params += where_params
            queries.append(f"""
                SELECT
                    account_move_line.account_id                                                          AS groupby,
                    'initial_balance'                                                                     AS key,
                    NULL                                                                                  AS max_date,
                    %s                                                                                    AS column_group_key,
                    COALESCE(SUM(account_move_line.amount_currency), 0.0)                                 AS amount_currency,
                    SUM(ROUND(account_move_line.debit * currency_table.rate, currency_table.precision))   AS debit,
                    SUM(ROUND(account_move_line.credit * currency_table.rate, currency_table.precision))  AS credit,
                    SUM(ROUND(account_move_line.balance * currency_table.rate, currency_table.precision)) AS balance
                FROM {tables}
                LEFT JOIN {ct_query} ON currency_table.company_id = account_move_line.company_id
                WHERE {where_clause}
                GROUP BY account_move_line.account_id
            """)

        self._cr.execute(" UNION ALL ".join(queries), params)

        init_balance_by_col_group = {
            account_id: {column_group_key: {} for column_group_key in options['column_groups']}
            for account_id in account_ids
        }
        for result in self._cr.dictfetchall():
            init_balance_by_col_group[result['groupby']][result['column_group_key']] = result

        accounts = self.env['account.account'].browse(account_ids)
        return {
            account.id: (account, init_balance_by_col_group[account.id])
            for account in accounts
        }

    def _get_options_initial_balance(self, options):
        """Create options to compute initial balances."""
        new_options = options.copy()
        date_to = new_options['comparison']['periods'][-1]['date_from'] if new_options.get('comparison', {}).get('periods') else new_options['date']['date_from']
        new_date_to = fields.Date.from_string(date_to) - timedelta(days=1)

        date_from = fields.Date.from_string(new_options['date']['date_from'])
        current_fiscalyear_dates = self.env.company.compute_fiscalyear_dates(date_from)

        if date_from == current_fiscalyear_dates['date_from']:
            previous_fiscalyear_dates = self.env.company.compute_fiscalyear_dates(date_from - timedelta(days=1))
            new_date_from = previous_fiscalyear_dates['date_from']
            include_current_year_in_unaff_earnings = True
        else:
            new_date_from = current_fiscalyear_dates['date_from']
            include_current_year_in_unaff_earnings = False

        new_options['date'] = {
            'mode': 'range',
            'date_from': fields.Date.to_string(new_date_from),
            'date_to': fields.Date.to_string(new_date_to),
        }
        new_options['include_current_year_in_unaff_earnings'] = include_current_year_in_unaff_earnings

        return new_options

    def _get_options_sum_balance(self, options):
        """Create options to compute the sum balance."""
        new_options = options.copy()
        if not options.get('member_ledger_strict_range'):
            date_from = fields.Date.from_string(new_options['date']['date_from'])
            current_fiscalyear_dates = self.env.company.compute_fiscalyear_dates(date_from)
            new_date_from = current_fiscalyear_dates['date_from']
            new_date_to = new_options['date']['date_to']

            new_options['date'] = {
                'mode': 'range',
                'date_from': fields.Date.to_string(new_date_from),
                'date_to': new_date_to,
            }
        return new_options

    def _get_account_title_line(self, report, options, account, has_lines, eval_dict):
        """Generate the account title line."""
        line_columns = []
        for column in options['columns']:
            col_value = eval_dict[column['column_group_key']].get(column['expression_label'])
            line_columns.append(report._build_column_dict(
                col_value,
                column,
                options=options,
            ))

        line_id = report._get_generic_line_id('account.account', account.id)
        is_in_unfolded_lines = any(
            report._get_res_id_from_line_id(line_id, 'account.account') == account.id
            for line_id in options.get('unfolded_lines')
        )
        return {
            'id': line_id,
            'name': f'{account.code} {account.name}',
            'columns': line_columns,
            'level': 1,
            'unfoldable': has_lines,
            'unfolded': has_lines and (is_in_unfolded_lines or options.get('unfold_all')),
            'expand_function': '_report_expand_unfoldable_line_member_ledger',
        }

    def _get_aml_line(self, report, parent_line_id, options, eval_dict, init_bal_by_col_group):
        """Generate an account move line."""
        _logger.info("Generating AML line with eval_dict: %s", eval_dict)
        line_columns = []
        for column in options['columns']:
            col_expr_label = column['expression_label']
            col_value = eval_dict[column['column_group_key']].get(col_expr_label)

            if col_value is not None and col_expr_label == 'balance':
                col_value += (init_bal_by_col_group[column['column_group_key']] or 0)

            line_columns.append(report._build_column_dict(
                col_value,
                column,
                options=options,
            ))

        aml_id = None
        move_name = None
        caret_type = None
        for column_group_dict in eval_dict.values():
            aml_id = column_group_dict.get('id', '')
            if aml_id:
                if column_group_dict.get('payment_id'):
                    caret_type = 'account.payment'
                else:
                    caret_type = 'account.move.line'
                move_name = column_group_dict['move_name']
                date = str(column_group_dict.get('date', ''))
                break

        line = {
            'id': report._get_generic_line_id('account.move.line', aml_id, parent_line_id=parent_line_id, markup=date),
            'caret_options': caret_type,
            'parent_id': parent_line_id,
            'name': move_name,
            'columns': line_columns,
            'level': 3,
        }
        _logger.info("Generated AML line: %s", line)
        return line

    def _get_total_line(self, report, options, eval_dict):
        """Generate the total line."""
        line_columns = []
        for column in options['columns']:
            col_value = eval_dict[column['column_group_key']].get(column['expression_label'])
            line_columns.append(report._build_column_dict(col_value, column, options=options))

        return {
            'id': report._get_generic_line_id(None, None, markup='total'),
            'name': _('Total'),
            'level': 1,
            'columns': line_columns,
        }

    def _report_expand_unfoldable_line_member_ledger(self, line_dict_id, groupby, options, progress, offset, unfold_all_batch_data=None):
        """Expand an unfoldable line."""
        def init_load_more_progress(line_dict):
            return {
                column['column_group_key']: line_col.get('no_format', 0)
                for column, line_col in zip(options['columns'], line_dict['columns'])
                if column['expression_label'] == 'balance'
            }

        report = self.env.ref('sacco_transactions_management.member_ledger_report')
        model, model_id = report._get_model_info_from_id(line_dict_id)

        if model != 'account.account':
            raise UserError(_("Wrong ID for member ledger line to expand: %s", line_dict_id))

        lines = []

        if offset == 0:
            if unfold_all_batch_data:
                account, init_balance_by_col_group = unfold_all_batch_data['initial_balances'][model_id]
            else:
                account, init_balance_by_col_group = self._get_initial_balance_values(report, [model_id], options)[model_id]

            initial_balance_line = report._get_partner_and_general_ledger_initial_balance_line(options, line_dict_id, init_balance_by_col_group, account.currency_id)

            if initial_balance_line:
                lines.append(initial_balance_line)
                progress = init_load_more_progress(initial_balance_line)

        limit_to_load = report.load_more_limit + 1 if report.load_more_limit and options['export_mode'] != 'print' else None
        if unfold_all_batch_data:
            aml_results = unfold_all_batch_data['aml_results'][model_id]
            has_more = unfold_all_batch_data['has_more'].get(model_id, False)
        else:
            aml_results, has_more = self._get_aml_values(report, options, [model_id], offset=offset, limit=limit_to_load)
            aml_results = aml_results[model_id]

        next_progress = progress
        for aml_result in aml_results.values():
            new_line = self._get_aml_line(report, line_dict_id, options, aml_result, next_progress)
            lines.append(new_line)
            next_progress = init_load_more_progress(new_line)

        return {
            'lines': lines,
            'offset_increment': report.load_more_limit,
            'has_more': has_more,
            'progress': next_progress,
        }

    def action_generate_member_statement(self, options):
        """Generate a PDF member statement for the selected member."""
        # Step 1: Validate that a single member is selected
        partner_id = options.get('partner_id')
        if not partner_id:
            raise UserError(_("Please select a single member to generate the statement."))

        # Step 2: Fetch the member details
        partner = self.env['res.partner'].browse(partner_id)
        if not partner:
            raise UserError(_("Selected member does not exist."))

        member_id = partner.ref or partner.id  # Assuming 'ref' is the member ID field
        member_name = partner.name

        # Step 3: Get the date range from the options
        date_from = options['date']['date_from']
        date_to = options['date']['date_to']
        request_date = fields.Date.today()
        
        aml_fields = [
            'id', 'date', 'name', 'ref', 'move_id', 'account_id', 'debit', 'credit', 'partner_id',
            'member_id', 'account_product_type',
        ]

        # New Step: Calculate brought-forward balances (transactions before date_from)
        brought_forward_domain = [
            ('partner_id', '=', partner_id),
            ('date', '<', date_from),  # Fetch everything before the start date
            ('move_id.state', '=', 'posted'),
            ('journal_id', '=', self.env['sacco.helper'].get_member_journal_id()),
            ('account_product_type', 'in', self.env['sacco.helper'].get_member_account_product_types()),
        ]
        brought_forward_results = self.env['account.move.line'].search_read(brought_forward_domain, aml_fields)

        # Initialize brought-forward totals
        brought_forward_totals = {
            'savings': 0.0,
            'savings_interest': 0.0,
            'loan': 0.0,
            'loan_interest': 0.0,
            'shares': 0.0,
            'share_number': 0.0,
        }
        bf_move_ids = set(aml['move_id'][0] for aml in brought_forward_results if aml.get('move_id'))
        bf_move_totals = {}
        if bf_move_ids:
            bf_move_totals_query = """
                SELECT
                    move.id AS move_id,
                    SUM(line.debit) AS total_debit,
                    SUM(line.credit) AS total_credit
                FROM account_move move
                JOIN account_move_line line ON line.move_id = move.id
                JOIN account_account account ON account.id = line.account_id
                WHERE move.id IN %s
                AND account.account_type LIKE 'equity%%'
                GROUP BY move.id
            """
            self._cr.execute(bf_move_totals_query, [tuple(bf_move_ids)])
            bf_move_totals = {row['move_id']: {'total_debit': row['total_debit'], 'total_credit': row['total_credit']} for row in self._cr.dictfetchall()}

        bf_account_ids = set(aml['account_id'][0] for aml in brought_forward_results)
        bf_accounts = self.env['account.account'].browse(bf_account_ids)
        bf_account_types = {account.id: account.account_type for account in bf_accounts}
        bf_original_shares_amounts = {account.id: account.original_shares_amount for account in bf_accounts}
        bf_processed_moves = set()

        for aml in brought_forward_results:
            account_id = aml['account_id'][0]
            account_type = bf_account_types.get(account_id, '')
            is_shares_account = aml.get('account_product_type') == 'shares'
            is_equity_account = account_type.startswith('equity')
            move_id = aml['move_id'][0]
            original_shares_amount = bf_original_shares_amounts.get(account_id, 0.0)

            if is_shares_account and is_equity_account and move_id in bf_processed_moves:
                continue

            if is_shares_account and is_equity_account:
                if move_id in bf_move_totals:
                    move_total = bf_move_totals[move_id]
                    debit = move_total['total_debit']
                    credit = move_total['total_credit']
                    shares = credit - debit
                    if original_shares_amount > 0:
                        brought_forward_totals['share_number'] += shares / original_shares_amount
                    brought_forward_totals['shares'] += shares
                    bf_processed_moves.add(move_id)
            else:
                debit = aml['debit']
                credit = aml['credit']
                product_type = aml.get('account_product_type')
                if product_type == 'savings':
                    brought_forward_totals['savings'] += credit - debit
                elif product_type == 'savings_interest':
                    brought_forward_totals['savings_interest'] += credit - debit
                elif product_type == 'loans':
                    brought_forward_totals['loan'] += debit - credit
                elif product_type == 'loans_interest':
                    brought_forward_totals['loan_interest'] += debit - credit

        # Step 4: Fetch the account move lines for the member within the date range
        domain = [
            ('partner_id', '=', partner_id),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
            ('move_id.state', '=', 'posted'),
            ('journal_id', '=', self.env['sacco.helper'].get_member_journal_id()),
            ('account_product_type', 'in', self.env['sacco.helper'].get_member_account_product_types()),
        ]
        aml_results = self.env['account.move.line'].search_read(domain, aml_fields)

        # Step 5: Compute move totals for shares
        move_ids = set(aml['move_id'][0] for aml in aml_results if aml.get('move_id'))
        move_totals = {}
        if move_ids:
            move_totals_query = """
                SELECT
                    move.id AS move_id,
                    SUM(line.debit) AS total_debit,
                    SUM(line.credit) AS total_credit
                FROM account_move move
                JOIN account_move_line line ON line.move_id = move.id
                JOIN account_account account ON account.id = line.account_id
                WHERE move.id IN %s
                AND account.account_type LIKE 'equity%%'
                GROUP BY move.id
            """
            self._cr.execute(move_totals_query, [tuple(move_ids)])
            move_totals = {row['move_id']: {'total_debit': row['total_debit'], 'total_credit': row['total_credit']} for row in self._cr.dictfetchall()}

        # Step 6: Fetch account types
        account_ids = set(aml['account_id'][0] for aml in aml_results)
        accounts = self.env['account.account'].browse(account_ids)
        account_types = {account.id: account.account_type for account in accounts}
        original_shares_amounts = {account.id: account.original_shares_amount for account in accounts}

        # Step 7: Prepare the statement data
        statement_lines = []
        totals = {
            'savings': brought_forward_totals['savings'],  # Initialize with brought-forward
            'savings_interest': brought_forward_totals['savings_interest'],
            'loan': brought_forward_totals['loan'],
            'loan_interest': brought_forward_totals['loan_interest'],
            'shares': brought_forward_totals['shares'],
            'share_number': brought_forward_totals['share_number'],
        }
        processed_moves = set()

        # Optionally add a "Brought Forward" line as the first entry
        if any(brought_forward_totals.values()):
            statement_lines.append({
                'date': fields.Date.from_string(date_from) - timedelta(days=1),  # Day before start date
                'savings': brought_forward_totals['savings'],
                'savings_interest': brought_forward_totals['savings_interest'],
                'loan': brought_forward_totals['loan'],
                'loan_interest': brought_forward_totals['loan_interest'],
                'shares': brought_forward_totals['shares'],
                'share_number': brought_forward_totals['share_number'],
                'description': 'Brought Forward',
            })

        for aml in aml_results:
            account_id = aml['account_id'][0]
            account_type = account_types.get(account_id, '')
            is_shares_account = aml.get('account_product_type') == 'shares'
            is_equity_account = account_type.startswith('equity')
            move_id = aml['move_id'][0]
            original_shares_amount = original_shares_amounts.get(account_id, 0.0)

            if is_shares_account and is_equity_account and move_id in processed_moves:
                continue

            savings = savings_interest = loan = loan_interest = shares = 0.0
            description = f"{aml['ref']} - {aml['name']}" if aml.get('ref') else aml['name']

            if is_shares_account and is_equity_account:
                if move_id in move_totals:
                    move_total = move_totals[move_id]
                    debit = move_total['total_debit']
                    credit = move_total['total_credit']
                    shares = credit - debit
                    processed_moves.add(move_id)
            else:
                debit = aml['debit']
                credit = aml['credit']

            product_type = aml.get('account_product_type')
            if product_type == 'savings':
                savings = credit - debit
                totals['savings'] += savings
            elif product_type == 'savings_interest':
                savings_interest = credit - debit
                totals['savings_interest'] += savings_interest
            elif product_type == 'loans':
                loan = debit - credit
                totals['loan'] += loan
            elif product_type == 'loans_interest':
                loan_interest = debit - credit
                totals['loan_interest'] += loan_interest
            elif product_type == 'shares' and is_shares_account and is_equity_account:
                totals['shares'] += shares
                
            share_number = 0.0
            if is_shares_account and is_equity_account:
                if move_id in move_totals:
                    move_total = move_totals[move_id]
                    balance = move_total['total_credit'] - move_total['total_debit']
                    if original_shares_amount > 0:
                        share_number = balance / original_shares_amount
                    totals['share_number'] += share_number
                    processed_moves.add(move_id)

            if any([savings, savings_interest, loan, loan_interest, shares]):
                statement_lines.append({
                    'date': aml['date'],
                    'savings': savings,
                    'savings_interest': savings_interest,
                    'loan': loan,
                    'loan_interest': loan_interest,
                    'shares': shares,
                    'share_number': share_number,
                    'description': description,
                })
        
        # Sort statement_lines by date (earliest to latest)
        statement_lines = sorted(statement_lines, key=lambda x: x['date'])

        # Step 8: Prepare the data for the report
        report_data = {
            'member_id': member_id,
            'member_name': member_name,
            'date_from': date_from,
            'date_to': date_to,
            'request_date': request_date,
            'lines': statement_lines,
            'totals': totals,
        }

        member_id = report_data['member_id']
        
        request_date_str = fields.Date.to_string(report_data['request_date']).replace('-', '_')  # Format date as string and replace hyphens
        
        # _logger.info("Report Data: %s", report_data)  # Add this to check the data
        if not report_data.get('lines'):
            _logger.warning("No statement lines found for member %s", partner_id)
            
        filename = f"Member_Statement_{member_id}_{request_date_str}.pdf"
        report_action = self.env.ref('sacco_transactions_management.action_member_statement_report')

        # Return the report action with a custom filename
        action = report_action.report_action(
            None,  # No records needed for abstract model
            data=report_data,
            config=False
        )
        action['name'] = filename  # Set the filename in the action
        return action