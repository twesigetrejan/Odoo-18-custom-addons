from odoo import api, fields, models

class HostelRoomCopy(models.Model):
    _name = 'hostel.room.copy'
    _inherit = 'hostel.room'
    _description = 'Copy information about a hostel room'