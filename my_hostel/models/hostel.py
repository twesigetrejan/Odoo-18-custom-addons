
from odoo import api, fields, models

class Hostel(models.Model):
    _name = 'hostel.hostel'
    _description = 'Information about a hostel'
    _order = 'id desc, name'
    _rec_name = 'hostel_code'

    name = fields.Char(string='Hostel Name', required=True)
    hostel_code = fields.Char(string='Code', required=True, help='Unique code for the hostel')
    street = fields.Char(string='Street')
    street2 = fields.Char(string='Street 2')
    zip = fields.Char('Zip', change_default=True, help='Postal code of the hostel location')
    city = fields.Char(string='City')
    state_id = fields.Many2one('res.country.state', string='State')
    country_id = fields.Many2one('res.country', string='Country')
    phone = fields.Char(string='Phone', required=True, help='Contact number for the hostel')
    mobile = fields.Char(string='Mobile', required=True)
    email = fields.Char(string='Email')
    display_name = fields.Char(compute='_compute_display_name', store=True)
    hostel_floors = fields.Integer(string='Total number of floors')
    image = fields.Binary('Hostel Image')
    active = fields.Boolean('Active', default=True, help='Activate/Deactivate hostel record')
    type = fields.Selection([("male", "Boys"), ("female", "Girls"), ("common", "Common")], help='Type of hostel', required=True, default='common'
    )
    other_info = fields.Text(string='Other information', help='Additional information about the hostel')
    description = fields.Html('Description')
    hostel_rating = fields.Float(string='Hostel average rating', digits=(14, 4), help='Average rating of the hostel based on user feedback')
    categoy_id = fields.Many2one('hostel.category')
    ref_doc_id = fields.Reference(
        selection='_referencable_models',
        string='Reference Document',
        help='Reference to a document related to the hostel'
    )

    @api.depends('hostel_code')
    def _compute_display_name(self):
        for record in self:
            name = record.name
            if record.hostel_code:
                name = f'{name} ({record.hostel_code})'
            record.display_name = name
            
    @api.model
    def _referencable_models(self):
        models = self.env['ir.model'].search([('field_id.name', '=', 'message_ids')])
        return [(x.model, x.name) for x in models]
    

# class HostelRoom(models.Model):
#     _name = 'hostel.room'
#     _description = 'Information about a hostel room'
#     _order = 'id desc, room_code'
#     _rec_name = 'room_code'

#     room_code = fields.Char(string='Room Code', required=True, help='Unique code for the room')
#     hostel_id = fields.Many2one('hostel.hostel', string='Hostel', required=True)
#     floor_number = fields.Integer(string='Floor Number')
#     capacity = fields.Integer(string='Capacity', help='Number of occupants the room can hold')
#     rent_amount = fields.Monetary(string='Rent Amount', currency_field='currency_id')
#     currency_id = fields.Many2one('res.currency', string='Currency', required=True)
#     active = fields.Boolean(string='Active', default=True)
#     notes = fields.Text(string='Notes')
