from odoo import models, api, fields
from odoo.exceptions import UserError

class HostelAnnouncements(models.Model):
    _name = "hostel.announcements"
    _description = "Hostel announcements"
    _rec_name = "announcement_title"
    _order = 'announcement_date desc'
    
    announcement_title = fields.Char(string="Announcement title", required= True)
    description = fields.Char(string="Description", required= True)
    announcement_date = fields.Datetime(string="Announcement date ",default = fields.Datetime.now)
    active = fields.Boolean(string='Active', default=True)
    hostel_id = fields.Many2one('hostel.hostel', string='Hostel')
    target_audience = fields.Selection([
        ('all', 'All Students'),
        ('male', 'Male Students'),
        ('female', 'Female Students'),
        ('category', 'By Room Category'),
    ], string='Target Audience', default='all')
    
    
    
    
    