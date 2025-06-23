from odoo import models, fields, api
from odoo.exceptions import UserError

class HostelMaintenanceRequest(models.Model):
    _name = 'hostel.maintenance.request'
    _description = 'Hostel Maintenance Request'
    _order = 'id desc, request_date'

    name = fields.Char(string='Issue Title', required=True, help='Short title for the maintenance issue')
    description = fields.Text(string='Detailed Description')
    request_date = fields.Datetime(string='Reported On', default=fields.Datetime.now)
    resolved_date = fields.Datetime(string='Resolved On')

    hostel_id = fields.Many2one('hostel.hostel', string='Hostel', help='Hostel where issue occurred')
    room_id = fields.Many2one('hostel.room', string='Room', domain="[('hostel_id', '=', hostel_id)]", help='Room affected by the issue')
    
    reported_by = fields.Many2one('res.users', string='Reported By', default=lambda self: self.env.user, readonly=True)
    priority = fields.Selection(
        [('low', 'Low'), ('medium', 'Medium'), ('high', 'High')],
        string='Priority', default='medium'
    )
    status = fields.Selection(
        [('new', 'New'),
         ('in_progress', 'In progress'),
         ('resolved', 'Resolved'),
         ('cancelled', 'Cancelled')],
        string='Status', default='new'
    )
    maintenance_image = fields.Binary(string='Image', help='Image or photo of the issue')
    remarks = fields.Text(string='Admin Remarks')

    duration = fields.Integer(string='Resolution Duration (days)', compute='_compute_duration', store=True)

    @api.depends('request_date', 'resolved_date')
    def _compute_duration(self):
        for record in self:
            if record.resolved_date and record.request_date:
                record.duration = (record.resolved_date.date() - record.request_date.date()).days
            else:
                record.duration = 0

    def action_mark_resolved(self):
        for rec in self:
            if rec.status != 'resolved':
                rec.status = 'resolved'
                rec.resolved_date = fields.Datetime.now()
