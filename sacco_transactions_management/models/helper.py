from odoo import models, api

class SaccoHelper(models.AbstractModel):
    _name = 'sacco.helper'
    _description = 'SACCO Helper Methods'

    @api.model
    def ensure_member_journal(self):
        """Ensure the Member Journal exists, creating it if necessary."""
        journal = self.env['account.journal'].search([('code', '=', 'MEMJ'), ('company_id', '=', self.env.company.id)], limit=1)
        if not journal:
            journal = self.env['account.journal'].create({
                'name': 'Member Journal',
                'code': 'MEMJ',
                'type': 'general',
                'sequence': 10,
                'company_id': self.env.company.id,
            })
        return journal.id

    @api.model
    def get_member_journal_id(self):
        """Dynamically fetch the Member Journal ID."""
        journal_id = self.ensure_member_journal()
        return journal_id

    @api.model
    def get_member_account_product_types(self):
        """Dynamically fetch the account product types for member-related accounts."""
        selection = self.env['account.move.line'].fields_get(['account_product_type'])['account_product_type']['selection']
        member_types = [key for key, value in selection if key in ['savings', 'savings_interest', 'shares', 'loans', 'loans_interest']]
        return member_types

    @api.model
    def get_member_journal_action(self):
        """Generate the action for the Member Journal menu with a dynamic domain and context."""
        member_journal_id = self.get_member_journal_id()
        account_product_types = self.get_member_account_product_types()

        # Define the domain dynamically
        domain = [
            ('journal_id', '=', member_journal_id),
            ('move_id.state', '=', 'posted'),
            ('account_product_type', 'in', account_product_types),
        ]

        # Define the context for default search filters
        context = {
            'search_default_journal_id': member_journal_id,  # Set the default journal to Member Journal
            'search_default_state_posted': 1,
            'search_default_account_product_type_savings': 1,
            'search_default_account_product_type_savings_interest': 1,
            'search_default_account_product_type_shares': 1,
            'search_default_account_product_type_loans': 1,
            'search_default_account_product_type_loans_interest': 1,
        }

        return {
            'type': 'ir.actions.act_window',
            'name': 'Member Journal',
            'res_model': 'account.move.line',
            'view_mode': 'tree,form',
            'search_view_id': self.env.ref('sacco_transactions_management.view_member_journal_search').id,
            'domain': domain,
            'context': context,
        }