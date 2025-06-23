from odoo import models, fields

class HostelRoomAmenity(models.Model):
    _name = 'hostel.room.amenity'
    _description = 'Hostel Room Amenity'
    _rec_name = 'amenity_type_id'

    amenity_type_id = fields.Many2one(
        'hostel.amenity.type',
        string='Amenity',
        required=True,
        help='Type of amenity'
    )

    description = fields.Text(string='Description', help='Description of the room amenity')
    amenity_price = fields.Float(string='Amenity Price', digits=(14, 2), help='Price for third-party amenity')
    hostel_id = fields.Many2one('hostel.hostel', string='Hostel')
    active = fields.Boolean(default=True)
    room_id = fields.Many2one('hostel.room', string='Room', required=True)
    image = fields.Binary(string='Amenity Image')
    amenity_type = fields.Selection(
        [('basic', 'Basic'), ('premium', 'Premium')],
        string='Amenity Type',
        default='basic'
    )
