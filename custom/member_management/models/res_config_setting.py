from odoo import models, fields, api, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    member_sync_from_date = fields.Datetime(string="Sync From Date")
    
    def action_sync_members_date_range(self):
        """Sync members from specific date range"""
        member_sync = self.env['member.sync'].create({
            'sync_from_date': self.member_sync_from_date,
            'sync_all': False
        })
        return member_sync.action_sync_members()

    def action_sync_all_members(self):
        """Sync all members regardless of date"""
        member_sync = self.env['member.sync'].create({
            'sync_all': True
        })
        return member_sync.action_sync_members()
    
    def action_sync_members(self):
        member_sync = self.env['member.sync'].create({})
        return member_sync.action_sync_members()
