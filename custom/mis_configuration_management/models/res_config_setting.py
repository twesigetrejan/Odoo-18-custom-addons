from datetime import datetime, timedelta
from odoo import models, fields, api, _

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    transaction_sync_from_date = fields.Datetime(
        string="Sync Transactions From",
        config_parameter='mis_config.transaction_sync_from_date',
        default=lambda self: datetime.now() - timedelta(days=30)
    )

    def set_values(self):
        """Save the transaction sync date to ir.config_parameter"""
        super().set_values()
        # Convert to ISO format for storage
        if self.transaction_sync_from_date:
            sync_date_str = self.transaction_sync_from_date.strftime('%Y-%m-%dT%H:%M:%S')
        else:
            sync_date_str = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S')
        self.env['ir.config_parameter'].sudo().set_param(
            'mis_config.transaction_sync_from_date', 
            sync_date_str
        )

    def get_values(self):
        """Retrieve the transaction sync date from ir.config_parameter"""
        res = super().get_values()
        sync_date_str = self.env['ir.config_parameter'].sudo().get_param(
            'mis_config.transaction_sync_from_date',
            default=(datetime.now() - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%S')
        )
        # Convert ISO format to Odoo's expected format
        try:
            sync_date = datetime.strptime(sync_date_str, '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            # Fallback in case of unexpected format
            sync_date = datetime.now() - timedelta(days=30)
        res['transaction_sync_from_date'] = sync_date
        return res

    def action_reset_sync_date(self):
        """Reset the sync date to one month before current date"""
        default_date = datetime.now() - timedelta(days=30)
        self.env['ir.config_parameter'].sudo().set_param(
            'mis_config.transaction_sync_from_date', 
            default_date.strftime('%Y-%m-%dT%H:%M:%S')
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

    def action_sync_transactions(self):
        """Trigger the transaction sync"""
        transaction_sync = self.env['sacco.transaction.sync'].create({})
        return transaction_sync.sync_transactions()