from odoo import models, api, fields, _
from odoo.exceptions import ValidationError, UserError
import requests
import logging
import base64
from datetime import datetime, timedelta
from ..config import (get_config, GET_FILTERED_TRANSACTIONS_COLLECTION_ENDPOINT, DOWNLOAD_FILE_ENDPOINT)

_logger = logging.getLogger(__name__)

class TransactionSync(models.Model):
    _name = 'sacco.transaction.sync'
    _description = 'Transaction Sync Model'
    _inherit = ['api.token.mixin']

    def sync_transactions(self):
        """Consolidated method to sync all transaction types"""
        _logger.info("Starting consolidated transaction sync")
        
        config = get_config(self.env)
        if not config.get('USERNAME') or not config.get('PASSWORD'):
            _logger.info("External system not configured, skipping transaction sync.")
            return self._show_notification(
                'Warning',
                'External system not configured. Transaction sync skipped.',
                'warning'
            )

        token, account_id = self._get_authentication_token()
        if not token:
            return self._show_notification('Error', 'Failed to obtain authentication token', 'danger')

        headers = self._get_request_headers()
        domain = self._prepare_sync_domain()

        try:
            data = self._fetch_all_transactions(headers, domain)
            _logger.info(f"Fetched {len(data.get('rows', []))} transactions from API")
            
            stats = self._process_transactions(data.get('rows', []))
            _logger.info(f"Sync completed with stats: {stats}")
            return self._show_sync_results(stats)
            
        except Exception as e:
            _logger.error(f"Sync failed: {str(e)}", exc_info=True)
            return self._show_notification('Error', f'Sync failed: {str(e)}', 'danger')

    def _fetch_all_transactions(self, headers, domain):
        """Fetch all transactions using pagination"""
        _logger.info("Starting to fetch all transactions")
        
        all_transactions = []
        page = 1
        limit = 5000
        config = get_config(self.env)
        api_url = f"{config['BASE_URL']}/{GET_FILTERED_TRANSACTIONS_COLLECTION_ENDPOINT}"

        while True:
            try:
                params = {'page': page, 'limit': limit}
                _logger.info(f"Fetching transactions - Page: {page}, Limit: {limit}")
                
                response = requests.post(api_url, headers=headers, json=domain, params=params)
                response.raise_for_status()
                
                data = response.json()
                current_transactions = data.get('rows', [])
                
                if not current_transactions:
                    break
                    
                all_transactions.extend(current_transactions)
                
                if len(current_transactions) < limit:
                    break
                    
                _logger.info(f"Fetched {len(current_transactions)} transactions from page {page}")
                page += 1
                
            except requests.RequestException as e:
                error_msg = f"Failed to fetch transactions from API: {str(e)}"
                _logger.error(error_msg, exc_info=True)
                raise ValidationError(_(error_msg))
                
        _logger.info(f"Total transactions fetched: {len(all_transactions)}")
        return {'rows': all_transactions}

    def _prepare_sync_domain(self):
        """Prepare domain for sync query using last_sync_date"""
        domain = {
            "status": "$text_filter:equals Paid or:equals Approved"
        }
        last_sync_date = self._get_latest_local_sync_date()
        if last_sync_date:
            date_str = last_sync_date.strftime('%Y-%m-%dT%H:%M:%S')
            domain["lastUpdated"] = f"$date_filter:gt {date_str}"
            _logger.info(f"Syncing transactions since last_sync_date: {date_str}")
        else:
            # Fallback to 30 days if no last_sync_date
            default_date = (datetime.now() - timedelta(days=30)).isoformat()
            domain["lastUpdated"] = f"$date_filter:gt {default_date}"
            _logger.info(f"No last_sync_date found, using default sync range: {default_date}")
        return domain

    def _get_latest_local_sync_date(self):
        """Get the latest last_sync_date from sacco.general.transaction records"""
        latest_transaction = self.env['sacco.general.transaction'].search([
            ('last_sync_date', '!=', False)
        ], order='last_sync_date desc', limit=1)
        return latest_transaction.last_sync_date if latest_transaction else None

    def _download_attachment(self, proof_of_payment):
        """Download proof of payment attachment from the external system."""
        if not proof_of_payment or not isinstance(proof_of_payment, str):
            _logger.warning("Invalid or empty proofOfPayment field, skipping attachment download")
            return None

        filename = proof_of_payment.split('/')[-1] if '/' in proof_of_payment else proof_of_payment
        config = get_config(self.env)
        api_url = f"{config['BASE_URL']}/{DOWNLOAD_FILE_ENDPOINT}/{filename}/download"
        headers = self._get_request_headers()

        if not headers:
            raise UserError(_("Authentication credentials missing for attachment download."))

        _logger.info(f"Attempting to download proof of payment: {filename} from {api_url}")

        try:
            response = requests.get(api_url, headers=headers, stream=True)
            _logger.info(f"Download response status: {response.status_code} for {filename}")
            response.raise_for_status()
            content = response.content
            if not content:
                _logger.error(f"Empty file received for {filename}")
                raise ValidationError(_(f"Empty file received for {filename}"))
            _logger.info(f"Downloaded {len(content)} bytes for {filename}")
            encoded_content = base64.b64encode(content).decode('utf-8')
            return {
                'name': filename,
                'datas': encoded_content,
                'type': 'binary',
                'description': 'Proof of Payment',
            }
        except requests.RequestException as e:
            _logger.error(f"Failed to download proof of payment {filename}: {str(e)}")
            raise ValidationError(_(f"Failed to download proof of payment {filename}: {str(e)}"))

    def _process_transactions(self, transactions):
        """Process all transactions in batches, creating general transactions"""
        BATCH_SIZE = 100
        stats = {
            'general': {'success': 0, 'error': 0},
            'savings': {'success': 0, 'error': 0},
            'investment': {'success': 0, 'error': 0},
            'loan': {'success': 0, 'error': 0}
        }

        _logger.info(f"Starting to process {len(transactions)} transactions")
        
        sorted_transactions = sorted(
            transactions,
            key=lambda x: self._parse_transaction_date(x.get('transactionDate', '1970-01-01T00:00:00'))
        )
        
        for i in range(0, len(sorted_transactions), BATCH_SIZE):
            batch = sorted_transactions[i:i + BATCH_SIZE]
            _logger.info(f"Processing batch of {len(batch)} transactions")
            self._process_transaction_batch(batch, stats)
            self.env.cr.commit()
            
        return stats

    def _process_transaction_batch(self, batch, stats):
        """Process a batch of transactions, grouping deposits under general transactions"""
        for transaction in batch:
            try:
                mongo_db_id = transaction.get('_id')
                ref_id = transaction.get('refID')
                remarks = transaction.get('remarks', '')
                
                # Check if general transaction already exists
                existing_transaction = self.env['sacco.general.transaction'].search([
                    '|',
                    ('mongo_db_id', '=', mongo_db_id),
                    ('ref_id', '=', ref_id)
                ], limit=1)
                if existing_transaction:
                    _logger.info(f"Skipping existing general transaction: {existing_transaction.name} (mongo_db_id: {mongo_db_id}, ref_id: {ref_id})")
                    continue

                deposits = transaction.get('deposits', [])
                if not deposits:
                    _logger.warning(f"No deposits found for transaction {mongo_db_id}")
                    continue

                _logger.info(f"Processing transaction {mongo_db_id} with deposits: {deposits}")

                # Calculate total amount for the general transaction
                total_amount = sum(float(deposit['amount']) for deposit in deposits)
                currency = self._get_currency(transaction['currency'])
                member = self._get_member(transaction['memberId'])
                transaction_date = self._parse_transaction_date(transaction['transactionDate'])

                # Get receiving account
                provider_name = transaction.get('providerName')
                receiving_account = self.env['sacco.receiving.account'].search([
                    ('name', '=', provider_name),
                    ('status', '=', 'active')
                ], limit=1)
                if not receiving_account and provider_name:
                    raise ValidationError(
                        f"No active receiving account found for provider '{provider_name}'. "
                        "Please configure a receiving account in Odoo with a valid accounting account."
                    )

                # Prepare general transaction values
                general_transaction_vals = {
                    'member_id': member.id,
                    'transaction_date': transaction_date.date(),
                    'total_amount': total_amount,
                    'currency_id': currency.id,
                    'receiving_account_id': receiving_account.id if receiving_account else False,
                    'state': 'verified',
                    'remarks': remarks,
                    'mongo_db_id': mongo_db_id,
                    'ref_id': ref_id,
                    'in_sync': True,
                    'last_sync_date': self._parse_transaction_date(transaction.get('lastUpdated', transaction['transactionDate']))
                }
                with self.env.cr.savepoint():
                    general_transaction = self.env['sacco.general.transaction'].create(general_transaction_vals)
                    _logger.info(f"Created general transaction {general_transaction.name} for transaction {mongo_db_id}")

                    # Process proof of payment attachment if present
                    proof_of_payment = transaction.get('proofOfPayment')
                    if proof_of_payment and isinstance(proof_of_payment, str) and proof_of_payment.strip():
                        try:
                            attachment_data = self._download_attachment(proof_of_payment)
                            if attachment_data:
                                attachment = self.env['ir.attachment'].create({
                                    'name': attachment_data['name'],
                                    'datas': attachment_data['datas'],
                                    'type': attachment_data['type'],
                                    'res_model': 'sacco.general.transaction',
                                    'res_id': general_transaction.id,
                                    'description': attachment_data['description'],
                                })
                                _logger.info(f"Created attachment {attachment_data['name']} (ID: {attachment.id}) for transaction {general_transaction.name}")
                        except Exception as e:
                            _logger.warning(f"Failed to process proof of payment for transaction {mongo_db_id}: {str(e)}")
                            # Continue processing even if attachment fails

                    # Process each deposit and link to the general transaction
                    at_least_one_successful = False
                    for deposit in deposits:
                        product_type = deposit.get('productType')
                        _logger.info(f"Processing deposit {deposit['id']} with productType: {product_type}")
                        
                        success = False
                        transaction_record = False
                        if product_type == 'Savings':
                            success, transaction_record = self._process_savings_deposit(transaction, deposit, general_transaction)
                            self._update_stats(stats['savings'], success)
                            _logger.info(f"Savings deposit {deposit['id']} processed: {'Success' if success else 'Failed'}")
                        elif product_type == 'Investment':
                            success, transaction_record = self._process_investment_deposit(transaction, deposit, general_transaction)
                            self._update_stats(stats['investment'], success)
                            _logger.info(f"Investment deposit {deposit['id']} processed: {'Success' if success else 'Failed'}")
                        elif product_type == 'Loan':
                            success, transaction_record = self._process_loan_payment(transaction, deposit, general_transaction)
                            self._update_stats(stats['loan'], success)
                            _logger.info(f"Loan payment {deposit['id']} processed: {'Success' if success else 'Failed'}")
                        else:
                            _logger.warning(f"Unknown productType '{product_type}' for deposit {deposit['id']}")
                            success = False

                        if success and transaction_record:
                            # Create transaction link
                            self.env['sacco.transaction.link'].create({
                                'general_transaction_id': general_transaction.id,
                                'transaction_model': transaction_record._name,
                                'transaction_id': transaction_record.id,
                                'transaction_name': transaction_record.name,
                                'transaction_amount': getattr(transaction_record, 'amount', 0.0),
                                'transaction_status': getattr(transaction_record, 'status', 'N/A'),
                            })
                            at_least_one_successful = True
                        elif success and not transaction_record:
                            # Loan payment with missing loan still counts as successful for partial processing
                            at_least_one_successful = True

                    # If no deposits were successful, roll back the general transaction
                    if not at_least_one_successful:
                        general_transaction.unlink()
                        self._update_stats(stats['general'], False)
                        _logger.warning(f"General transaction for {mongo_db_id} rolled back due to no successful deposits")
                    else:
                        self._update_stats(stats['general'], True)
                        _logger.info(f"General transaction {general_transaction.name} created successfully in verified state")

                self.env.cr.commit()

            except Exception as e:
                self.env.cr.rollback()
                self._update_stats(stats['general'], False)
                _logger.error(f"Failed processing transaction {transaction.get('_id')}: {str(e)}", exc_info=True)
                continue

        _logger.info(f"Batch processing completed. Current stats: {stats}")
        return stats

    def _parse_transaction_date(self, date_str):
        """Parse transaction date handling multiple formats"""
        formats_to_try = [
            '%Y-%m-%dT%H:%M:%S.%f',
            '%Y-%m-%dT%H:%M:%S.%f%z',
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%dT%H:%M:%S'
        ]

        if '+00:00' in date_str:
            date_str = date_str.replace('+00:00', '')

        for date_format in formats_to_try:
            try:
                return datetime.strptime(date_str, date_format)
            except ValueError:
                continue

        raise ValidationError(_(f"Unable to parse date string: {date_str}"))

    def _process_savings_deposit(self, transaction, deposit, general_transaction):
        """Process a single savings deposit under a general transaction"""
        try:
            if self._transaction_exists('savings.transaction', deposit['id'], deposit.get('refID')):
                return True, None

            currency = self._get_currency(transaction['currency'])
            member = self._get_member(transaction['memberId'])
            transaction_date = self._parse_transaction_date(transaction['transactionDate'])
            
            savings_product = self.env['sacco.savings.product'].search([
                ('name', '=', deposit.get('product'))
            ], limit=1)
            if not savings_product:
                raise ValidationError(f"Savings product not found: {deposit.get('product')}")

            values = {
                'member_id': member.id,
                'product_id': savings_product.id,
                'transaction_type': 'deposit',
                'amount': float(deposit['amount']),
                'currency_id': currency.id,
                'transaction_date': transaction_date.date(),
                'status': 'pending',
                'ref_id': deposit.get('refID'),
                'mongo_db_id': deposit['id'],
                'created_by': transaction.get('createdBy'),
                'receiving_account_id': general_transaction.receiving_account_id.id if general_transaction.receiving_account_id else False,
                'general_transaction_id': general_transaction.id,
            }

            savings_transaction = self.env['savings.transaction'].create(values)
            return savings_transaction.exists(), savings_transaction
            
        except Exception as e:
            _logger.error(f"Error processing savings deposit {deposit['id']}: {str(e)}")
            return False, None

    def _process_investment_deposit(self, transaction, deposit, general_transaction):
        """Process a single investment deposit under a general transaction"""
        try:
            if self._transaction_exists('sacco.investments.transaction', deposit['id'], deposit.get('refID')):
                return True, None

            currency = self._get_currency(transaction['currency'])
            member = self._get_member(transaction['memberId'])
            transaction_date = self._parse_transaction_date(transaction['transactionDate'])
            
            investment_product = self.env['sacco.investments.product'].search([
                ('name', '=', deposit.get('product'))
            ], limit=1)
            if not investment_product:
                raise ValidationError(f"Investment product not found: {deposit.get('product')}")

            values = {
                'member_id': member.id,
                'product_id': investment_product.id,
                'transaction_type': 'deposit',
                'amount': float(deposit['amount']),
                'currency_id': currency.id,
                'transaction_date': transaction_date.date(),
                'status': 'pending',
                'ref_id': deposit.get('refID'),
                'mongo_db_id': deposit['id'],
                'created_by': transaction.get('createdBy'),
                'receiving_account_id': general_transaction.receiving_account_id.id if general_transaction.receiving_account_id else False,
                'general_transaction_id': general_transaction.id,
            }

            investment_transaction = self.env['sacco.investments.transaction'].create(values)
            return investment_transaction.exists(), investment_transaction
            
        except Exception as e:
            _logger.error(f"Error processing investment deposit {deposit['id']}: {str(e)}")
            return False, None

    def _process_loan_payment(self, transaction, deposit, general_transaction):
        """Process a single loan payment under a general transaction"""
        try:
            if self._transaction_exists('sacco.loan.payments', deposit['id'], deposit.get('refID')):
                return True, None

            currency = self._get_currency(transaction['currency'])
            member = self._get_member(transaction['memberId'])
            transaction_date = self._parse_transaction_date(transaction['transactionDate'])
            
            loan = self.env['sacco.loan.loan'].search([
                ('loan_type_id.name', '=', deposit.get('product')),
                ('client_id', '=', member.id),
                ('state', 'in', ['open', 'close'])
            ], limit=1)
            
            values = {
                'client_id': member.id,
                'amount': float(deposit['amount']),
                'currency_id': loan.currency_id.id if loan else self.env.company.currency_id.id,
                'payment_date': transaction_date.date(),
                'status': 'pending',
                'ref_id': deposit.get('refID'),
                'mongo_db_id': deposit['id'],
                'created_by': transaction.get('createdBy'),
                'receiving_account_id': general_transaction.receiving_account_id.id if general_transaction.receiving_account_id else False,
                'receipt_account': general_transaction.receiving_account_id.account_id.id if general_transaction.receiving_account_id else False,
                'general_transaction_id': general_transaction.id,
            }

            if loan:
                values.update({
                    'loan_id': loan.id,
                    'loan_type_id': loan.loan_type_id.id,
                    'missing_loan': False,
                })
            else:
                # Create a placeholder loan type if none exists
                loan_type = self.env['sacco.loan.type'].search([
                    ('name', '=', deposit.get('product'))
                ], limit=1)
                if not loan_type:
                    loan_type = self.env['sacco.loan.type'].create({
                        'name': deposit.get('product'),
                        'code': deposit.get('refID', 'LOAN')[:10],
                    })
                values.update({
                    'loan_type_id': loan_type.id,
                    'missing_loan': True,
                })
                _logger.warning(f"Loan not found for product {deposit.get('product')} and member {member.member_id}. Created loan payment with missing_loan=True.")

            loan_payment = self.env['sacco.loan.payments'].create(values)
            return True, loan_payment
            
        except Exception as e:
            _logger.error(f"Error processing loan payment {deposit['id']}: {str(e)}")
            return False, None

    def _transaction_exists(self, model, mongo_db_id, ref_id):
        """Check if transaction already exists based on mongo_db_id or ref_id"""
        return bool(self.env[model].search([
            '|',
            ('mongo_db_id', '=', mongo_db_id),
            ('ref_id', '=', ref_id)
        ], limit=1))

    def _update_stats(self, stat_dict, success):
        """Update success/error statistics"""
        if success:
            stat_dict['success'] += 1
        else:
            stat_dict['error'] += 1

    def _show_sync_results(self, stats):
        """Show sync results notification"""
        message = (
            f"General Transactions: {stats['general']['success']} success, {stats['general']['error']} errors\n"
            f"Savings: {stats['savings']['success']} success, {stats['savings']['error']} errors\n"
            f"Investments: {stats['investment']['success']}: success, {stats['investment']['error']} errors\n"
            f"Loans: {stats['loan']['success']}: success, {stats['loan']['error']} errors"
        )
        
        _logger.info(f"Sync results: {message}")
        
        has_errors = any(s['error'] > 0 for s in stats.values())
        
        return self._show_notification(
            'Sync Complete',
            message,
            'warning' if has_errors else 'success'
        )

    def _show_notification(self, title, message, type='info'):
        """Show notification in UI"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'sticky': True,
                'type': type
            }
        }

    def _get_currency(self, currency_code):
        """Get currency record from currency code"""
        currency = self.env['res.currency'].with_context(active_test=False).search([
            ('name', '=', currency_code)
        ], limit=1)
        
        if not currency:
            raise ValidationError(f"Invalid currency code: {currency_code}")
            
        if not currency.active:
            currency.write({'active': True})
            
        return currency

    def _get_member(self, member_id):
        """Get member record from member Id"""
        member = self.env['res.partner'].search([
            '|',
            ('member_id', '=', member_id),
            ('username', '=', member_id)
        ], limit=1)
        if not member:
            raise ValidationError(_(f"Member or Username with ID {member_id} not found"))
        return member