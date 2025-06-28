from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from logging import getLogger

_logger = getLogger(__name__)

class GeneralTransaction(models.Model):
    _name = 'sacco.general.transaction'
    _description = 'General Transaction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'transaction_date desc, id desc'

    name = fields.Char('Reference', default='/', copy=False, readonly=True)
    member_id = fields.Many2one('res.partner', string='Member', required=True, domain=[('is_sacco_member', '=', True)])
    transaction_date = fields.Date(string='Transaction Date', required=True, default=fields.Date.context_today)
    total_amount = fields.Float(string='Total Amount', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True)
    receiving_account_id = fields.Many2one('sacco.receiving.account', string='Receiving Account')
    receipt_account = fields.Many2one('account.account', string='Receipt Account', compute='_compute_receipt_account', store=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('approved', 'Approved'),
        ('deleted', 'Deleted'),
    ], string='Status', default='pending', tracking=True)
    attachment_document_ids = fields.One2many('ir.attachment', 'res_id', string='Attachment Document', domain=[('res_model', '=', 'sacco.general.transaction')])
    attachment_number = fields.Integer(compute='_compute_attachment_number', string='Number of Attachments')
    remarks = fields.Text(string='Remarks', help='Additional information about the transaction')

    transaction_link_ids = fields.One2many('sacco.transaction.link', 'general_transaction_id', string='Related Transactions')

    # Flags for model availability
    has_savings = fields.Boolean(compute='_compute_model_availability', store=False)
    has_investments = fields.Boolean(compute='_compute_model_availability', store=False)
    has_loans = fields.Boolean(compute='_compute_model_availability', store=False)
    has_shares = fields.Boolean(compute='_compute_model_availability', store=False)

    # MIS fields
    mongo_db_id = fields.Char(string='Mongo DB ID', readonly=True, copy=False)
    ref_id = fields.Char(string='Reference ID', readonly=True, copy=False)
    in_sync = fields.Boolean(string='In Sync', default=True, help='Indicates if the withdrawal is synchronized with the external system')
    last_sync_date = fields.Datetime(string='Last Sync Date', readonly=True)

    @api.depends('receiving_account_id')
    def _compute_receipt_account(self):
        for record in self:
            record.receipt_account = record.receiving_account_id.account_id if record.receiving_account_id else False

    @api.depends()
    def _compute_model_availability(self):
        for record in self:
            record.has_savings = 'savings.transaction' in self.env
            record.has_investments = 'sacco.investments.transaction' in self.env
            record.has_loans = 'sacco.loan.payments' in self.env
            record.has_shares = 'shares.transaction' in self.env

    @api.model
    def create(self, vals):
        if vals.get('name', '/') == '/':
            vals['name'] = self.env['ir.sequence'].next_by_code('sacco.general.transaction') or '/'
        record = super(GeneralTransaction, self).create(vals)
        _logger.info(f"Created general transaction {record.name} with ID {record.id}")
        return record

    def _compute_attachment_number(self):
        for general_transaction in self:
            general_transaction.attachment_number = len(general_transaction.attachment_document_ids.ids)
    
    def action_get_attachment_view(self):
        self.ensure_one()
        res = self.env['ir.actions.act_window']._for_xml_id('base.action_attachment')
        res['domain'] = [('res_model', '=', 'sacco.general.transaction'), ('res_id', 'in', self.ids)]
        res['context'] = {'default_res_model': 'sacco.general.transaction', 'default_res_id': self.id}
        return res   

    def _recreate_transaction_links(self):
        """Recreate associated transaction records from transaction_link_ids for a verified transaction."""
        self.ensure_one()
        if self.state != 'verified':
            _logger.warning(f"Cannot recreate transaction links for {self.name} in state {self.state}")
            return

        for link in self.transaction_link_ids:
            try:
                # Check if the transaction already exists
                tx = self.env[link.transaction_model].search([
                    '|',
                    ('mongo_db_id', '=', link.transaction_name.split('/')[-1] if '/' in link.transaction_name else False),
                    ('ref_id', '=', link.transaction_name.split('/')[-1] if '/' in link.transaction_name else False)
                ], limit=1)
                if tx.exists():
                    # Reset journal entry if it exists
                    if tx.journal_entry_id:
                        if tx.journal_entry_id.state == 'posted':
                            tx.journal_entry_id.button_draft()
                        tx.journal_entry_id.unlink()
                    tx.write({'status': 'pending', 'journal_entry_id': False})
                    _logger.info(f"Transaction {link.transaction_model}/{tx.id} reset for link {link.id}")
                    link.write({
                        'transaction_id': tx.id,
                        'transaction_name': tx.name,
                        'transaction_amount': getattr(tx, 'amount', link.transaction_amount),
                        'transaction_status': 'pending'
                    })
                    continue

                # Prepare common values for transaction creation
                values = {
                    'member_id': self.member_id.id,
                    'transaction_date': self.transaction_date,
                    'amount': link.transaction_amount,
                    'currency_id': self.currency_id.id,
                    'status': 'pending',
                    'ref_id': link.transaction_name.split('/')[-1] if '/' in link.transaction_name else False,
                    'mongo_db_id': link.transaction_name.split('/')[-1] if '/' in link.transaction_name else False,
                    'receiving_account_id': self.receiving_account_id.id if self.receiving_account_id else False,
                    'general_transaction_id': self.id,
                }

                transaction_record = False
                if link.transaction_model == 'savings.transaction' and 'savings.transaction' in self.env:
                    savings_product = self.env['sacco.savings.product'].search([], limit=1)  # Fallback product
                    if not savings_product:
                        raise ValidationError(_("No savings product found to recreate savings transaction."))
                    values.update({
                        'product_id': savings_product.id,
                        'transaction_type': 'deposit',
                    })
                    transaction_record = self.env['savings.transaction'].create(values)

                elif link.transaction_model == 'sacco.investments.transaction' and 'sacco.investments.transaction' in self.env:
                    investment_product = self.env['sacco.investments.product'].search([], limit=1)  # Fallback product
                    if not investment_product:
                        raise ValidationError(_("No investment product found to recreate investment transaction."))
                    values.update({
                        'product_id': investment_product.id,
                        'transaction_type': 'deposit',
                    })
                    transaction_record = self.env['sacco.investments.transaction'].create(values)

                elif link.transaction_model == 'sacco.loan.payments' and 'sacco.loan.payments' in self.env:
                    loan_type = self.env['sacco.loan.type'].search([], limit=1)
                    if not loan_type:
                        loan_type = self.env['sacco.loan.type'].create({
                            'name': 'Restored Loan',
                            'code': 'RESTORED'
                        })
                    values.update({
                        'client_id': self.member_id.id,
                        'payment_date': self.transaction_date,
                        'loan_type_id': loan_type.id,
                        'missing_loan': True,
                        'receipt_account': self.receiving_account_id.account_id.id if self.receiving_account_id else False,
                    })
                    transaction_record = self.env['sacco.loan.payments'].create(values)

                elif link.transaction_model == 'shares.transaction' and 'shares.transaction' in self.env:
                    shares_product = self.env['sacco.shares.product'].search([], limit=1)  # Fallback product
                    if not shares_product:
                        raise ValidationError(_("No shares product found to recreate shares transaction."))
                    values.update({
                        'product_id': shares_product.id,
                        'transaction_type': 'deposit',
                    })
                    transaction_record = self.env['shares.transaction'].create(values)

                if transaction_record:
                    link.write({
                        'transaction_id': transaction_record.id,
                        'transaction_name': transaction_record.name,
                        'transaction_amount': getattr(transaction_record, 'amount', link.transaction_amount),
                        'transaction_status': 'pending'
                    })
                    _logger.info(f"Recreated {link.transaction_model}/{transaction_record.id} for transaction {self.name}")
                else:
                    _logger.warning(f"Failed to recreate transaction for link {link.transaction_model}/{link.transaction_id}")

            except Exception as e:
                _logger.error(f"Error recreating transaction for link {link.transaction_model}/{link.transaction_id}: {str(e)}")
                continue

    def action_verify(self):
        """Set transaction from deleted state to verified and recreate associated transaction records."""
        self.ensure_one()
        if self.state != 'deleted':
            raise ValidationError(_("Only deleted transactions can be verified."))
        with self.env.cr.savepoint():
            self.state = 'verified'
            self._recreate_transaction_links()
            _logger.info(f"General transaction {self.name} set to verified from deleted state with recreated links")

    def action_mass_verify(self):
        """Mass verify selected general transactions from deleted state and recreate associated transaction records."""
        for record in self:
            if record.state != 'deleted':
                raise ValidationError(_("%s is not in deleted state and cannot be verified.") % record.name)
            with self.env.cr.savepoint():
                record.action_verify()
        _logger.info(f"Mass verified general transactions: {self.mapped('name')}")
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_approve(self):
        self.ensure_one()
        if self.state != 'verified':
            raise ValidationError(_("Only verified transactions can be approved."))

        _logger.info(f"Approving general transaction {self.name} with links: {self.transaction_link_ids.mapped('transaction_model')}")
        all_success = True
        # Define a clean context to prevent state interference
        clean_context = dict(self.env.context, default_state='draft', state=None)
        
        for link in self.transaction_link_ids:
            _logger.info(f"Processing link: {link.transaction_model} - {link.transaction_id}")
            try:
                tx = self.env[link.transaction_model].browse(link.transaction_id)
                if not tx.exists():
                    _logger.warning(f"Transaction {link.transaction_model}/{link.transaction_id} does not exist")
                    all_success = False
                    continue
                if tx.status != 'pending':
                    _logger.info(f"Skipping transaction {link.transaction_model}/{link.transaction_id} (status: {tx.status})")
                    continue

                # Reverse any existing journal entries
                if tx.journal_entry_id:
                    if tx.journal_entry_id.state == 'posted':
                        tx.journal_entry_id.button_draft()
                    tx.journal_entry_id.unlink()
                    tx.write({'journal_entry_id': False})

                # Apply clean context to transaction processing
                tx_with_context = tx.with_context(clean_context)
                if link.transaction_model == 'savings.transaction' and 'savings.transaction' in self.env:
                    tx_with_context.action_confirm_transaction()
                    tx.write({'status': 'confirmed'})
                elif link.transaction_model == 'sacco.investments.transaction' and 'sacco.investments.transaction' in self.env:
                    tx_with_context.action_confirm_transaction()
                    tx.write({'status': 'confirmed'})
                elif link.transaction_model == 'sacco.loan.payments' and 'sacco.loan.payments' in self.env:
                    if tx.missing_loan:
                        _logger.info(f"Skipping loan payment {tx.id} with missing loan during approval")
                        continue
                    tx_with_context.action_approve_payment()
                    tx.write({'status': 'approved'})
                elif link.transaction_model == 'shares.transaction' and 'shares.transaction' in self.env:
                    tx_with_context.action_confirm_transaction()
                    tx.write({'status': 'confirmed'})
            except Exception as e:
                _logger.error(f"Error processing transaction {link.transaction_model}/{link.transaction_id}: {str(e)}")
                all_success = False

        # Force recompute of transaction link details to reflect updated statuses
        self.transaction_link_ids._compute_transaction_details()

        if all_success:
            self.state = 'approved'
            _logger.info(f"General transaction {self.name} approved")
        else:
            incomplete_loans = self.transaction_link_ids.filtered(lambda l: l.transaction_model == 'sacco.loan.payments' and self.env[l.transaction_model].browse(l.transaction_id).missing_loan)
            if incomplete_loans and any(l.transaction_model != 'sacco.loan.payments' or not self.env[l.transaction_model].browse(l.transaction_id).missing_loan for l in self.transaction_link_ids):
                self.state = 'approved'
                _logger.info(f"General transaction {self.name} approved with incomplete loan payments")
            else:
                raise ValidationError(_("Some transactions failed to process. Please check the related transactions."))

    def action_mass_approve(self):
        for record in self:
            if record.state != 'verified':
                raise ValidationError(_("%s is not in verified state and cannot be approved.") % record.name)
            record.action_approve()
        _logger.info(f"Mass approved general transactions: {self.mapped('name')}")

    def action_mass_delete(self):
        """Mass delete selected general transactions."""
        # Lock records to prevent concurrent modifications
        self.env.cr.execute("SELECT id FROM sacco_general_transaction WHERE id IN %s FOR UPDATE", (tuple(self.ids),))
        
        to_unlink = self.env['sacco.general.transaction']
        for record in self.with_context(active_test=False):
            if not record.exists():
                _logger.warning(f"Skipping non-existent record ID {record.id}")
                continue
            if record.state == 'approved':
                raise ValidationError(_("%s is in approved state and cannot be deleted.") % record.name)
            if record.state != 'deleted':
                _logger.info(f"Deleting transaction {record.name} (ID: {record.id})")
                record.action_delete()
            if not record.transaction_link_ids:
                to_unlink |= record
        
        if to_unlink:
            _logger.info(f"Unlinking transactions: {to_unlink.mapped('name')}")
            to_unlink.with_context(active_test=False).unlink()
        
        self.unlink()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_delete(self):
        self.ensure_one()
        if self.state == 'deleted':
            raise ValidationError(_("Transaction is already deleted."))

        _logger.info(f"Deleting general transaction {self.name} with links: {self.transaction_link_ids.mapped('transaction_model')}")
        for link in self.transaction_link_ids:
            try:
                if link.transaction_model == 'savings.transaction' and 'savings.transaction' in self.env:
                    tx = self.env['savings.transaction'].browse(link.transaction_id)
                    if tx.exists():
                        if tx.journal_entry_id and tx.journal_entry_id.state == 'posted':
                            tx.journal_entry_id.button_draft()
                            tx.journal_entry_id.unlink()
                        tx.write({'general_transaction_id': False})
                        tx.unlink()
                elif link.transaction_model == 'sacco.investments.transaction' and 'sacco.investments.transaction' in self.env:
                    tx = self.env['sacco.investments.transaction'].browse(link.transaction_id)
                    if tx.exists():
                        if tx.journal_entry_id and tx.journal_entry_id.state == 'posted':
                            tx.journal_entry_id.button_draft()
                            tx.journal_entry_id.unlink()
                        tx.write({'general_transaction_id': False})
                        tx.unlink()
                elif link.transaction_model == 'sacco.loan.payments' and 'sacco.loan.payments' in self.env:
                    tx = self.env['sacco.loan.payments'].browse(link.transaction_id)
                    if tx.exists():
                        if tx.journal_entry_id and tx.journal_entry_id.state == 'posted':
                            tx.journal_entry_id.button_draft()
                            tx.journal_entry_id.unlink()
                        tx.write({'general_transaction_id': False})
                        tx.unlink()
                elif link.transaction_model == 'shares.transaction' and 'shares.transaction' in self.env:
                    tx = self.env['shares.transaction'].browse(link.transaction_id)
                    if tx.exists():
                        if tx.journal_entry_id and tx.journal_entry_id.state == 'posted':
                            tx.journal_entry_id.button_draft()
                            tx.journal_entry_id.unlink()
                        tx.write({'general_transaction_id': False})
                        tx.unlink()
            except Exception as e:
                _logger.error(f"Error deleting transaction {link.transaction_model}/{link.transaction_id}: {str(e)}")
                raise ValidationError(_("Failed to delete transaction %s/%s: %s") % (link.transaction_model, link.transaction_id, str(e)))

        self.state = 'deleted'
        _logger.info(f"General transaction {self.name} set to deleted state")

    def unlink(self):
        for record in self:
            if record.state != 'deleted':
                raise ValidationError(_("Please use the Mass Delete button to set the state to Deleted to remove this transaction."))
        return super(GeneralTransaction, self).unlink()

class TransactionLink(models.Model):
    _name = 'sacco.transaction.link'
    _description = 'Transaction Link'

    general_transaction_id = fields.Many2one('sacco.general.transaction', string='General Transaction', required=True, ondelete='cascade')
    transaction_model = fields.Char(string='Transaction Model', required=True)
    transaction_id = fields.Integer(string='Transaction ID', required=True)
    transaction_name = fields.Char(string='Transaction Reference', compute='_compute_transaction_details', store=True)
    transaction_amount = fields.Float(string='Amount', compute='_compute_transaction_details', store=True)
    transaction_status = fields.Char(string='Status', compute='_compute_transaction_details', store=True)
    transaction_type_display = fields.Char(string='Transaction Type', compute='_compute_transaction_type_display', store=True)

    @api.depends('transaction_model')
    def _compute_transaction_type_display(self):
        model_display_map = {
            'savings.transaction': 'Savings Transaction',
            'sacco.investments.transaction': 'Investments Transaction',
            'sacco.loan.payments': 'Loan Payment',
            'shares.transaction': 'Shares Transaction',
        }
        for link in self:
            link.transaction_type_display = model_display_map.get(link.transaction_model, link.transaction_model or 'Unknown')

    @api.depends('transaction_model', 'transaction_id')
    def _compute_transaction_details(self):
        for link in self:
            if link.transaction_model in self.env and link.transaction_id:
                try:
                    record = self.env[link.transaction_model].browse(link.transaction_id)
                    if record.exists():
                        link.transaction_name = record.name or f"{link.transaction_model}/{link.transaction_id}"
                        link.transaction_amount = getattr(record, 'amount', 0.0) or 0.0
                        link.transaction_status = getattr(record, 'status', 'N/A') or 'N/A'
                    else:
                        link.transaction_name = f"{link.transaction_model}/{link.transaction_id}"
                        link.transaction_amount = 0.0
                        link.transaction_status = 'N/A'
                except Exception as e:
                    _logger.error(f"Error computing transaction details for {link.transaction_model}/{link.transaction_id}: {str(e)}")
                    link.transaction_name = f"{link.transaction_model}/{link.transaction_id}"
                    link.transaction_amount = 0.0
                    link.transaction_status = 'N/A'
            else:
                link.transaction_name = f"{link.transaction_model}/{link.transaction_id}"
                link.transaction_amount = 0.0
                link.transaction_status = 'N/A'

    def action_open_transaction(self):
        self.ensure_one()
        if self.transaction_model not in self.env:
            raise ValidationError(_("The module for %s is not installed.") % self.transaction_model)
        try:
            record = self.env[self.transaction_model].browse(self.transaction_id)
            if not record.exists():
                raise ValidationError(_("The transaction %s/%s does not exist.") % (self.transaction_model, self.transaction_id))
            return {
                'type': 'ir.actions.act_window',
                'res_model': self.transaction_model,
                'res_id': self.transaction_id,
                'view_mode': 'form',
                'views': [[False, 'form']],
                'target': 'current',
            }
        except Exception as e:
            raise ValidationError(_("Error opening transaction: %s") % str(e))