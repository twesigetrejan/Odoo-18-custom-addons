from odoo import models, fields, api
from odoo.exceptions import ValidationError
class HostelRoom(models.Model):
    _name = 'hostel.room'
    _description = 'Information about a hostel room'
    _order = 'id desc, room_code'
    _rec_name = 'room_code'
    _sql_constraints = [
        ('room_no_unique', 'UNIQUE(room_no)', 'Room number must be unique!'),]
    
    room_no = fields.Char(string='Room number', required=True)
    room_code = fields.Char(string='Room number')
    hostel_id = fields.Many2one('hostel.hostel', string='Hostel', required=True, help='Hostel to which the room belongs')
    floor_number = fields.Integer(string='Floor Number')
    capacity = fields.Integer(string='Capacity', help='Number of occupants the room can hold')
    rent_amount = fields.Monetary(string='Rent amount', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True)
    active = fields.Boolean(string='Active', default=True)
    notes = fields.Text(string='Notes')
    student_per_room = fields.Integer("Student per room", required=True, help="Number of students allowed in this room")
    availability = fields.Float(compute = '_compute_check_availability', string='Availability', help="Room availability in hostel", store=True)
    
    student_ids = fields.One2many(
        'hostel.student', 'room_id', string='Students',
        help='Students assigned to this room'
    )

    hostel_amenities_ids = fields.Many2many(
        "hostel.amenities",
        "hostel_room_amenities_rel",
        "room_id",
        "amenity_id",
        string="Hostel amenities",
        domain="[('active', '=', True)]",
        help="Amenities available in this room"
    )

    @api.constrains('rent_amount')
    def _check_rent_amount(self):
        """Ensure that the rent amount is not negative."""
        if self.rent_amount < 0:
            raise ValidationError("Rent amount per month cannot be negative value.")
       
    @api.depends('student_per_room', 'student_ids')
    def _compute_check_availability(self):
        """Compute the availability of the room based on the number of students assigned."""
        for record in self:
           record.availability = record.student_per_room - len(record.student_ids.ids)








# from odoo import models, fields, api


# class HostelRoom(models.Model):
#     _name = 'hostel.room'
#     _description = 'Information about a hostel room'
#     _order = 'id desc, room_code'
#     _rec_name = 'room_code'

#     room_code = fields.Char(string='Room code', required=True, help='Unique code for the room')
#     hostel_id = fields.Many2one('hostel.hostel', string='Hostel', required=True)
#     floor_number = fields.Integer(string='Floor Number')
#     capacity = fields.Integer(string='Capacity', help='Number of occupants the room can hold')
#     rent_amount = fields.Monetary(string='Rent amount', currency_field='currency_id')
#     currency_id = fields.Many2one('res.currency', string='Currency', required=True)
#     active = fields.Boolean(string='Active', default=True)
#     notes = fields.Text(string='Notes')
#     hostel_id = fields.Many2one('hostel.hostel', string='Hostel', help='Hostel to which the room belongs')
#     student_ids = fields.One2many('hostel.student', 'room_id', string='Students', help='Students assigned to this room')
#     hostel_amenities_ids = fields.Many2many("hostel.amenities","hostel_room_amenities_rel", "room_id", "amenity_id", string="Hostel amenities", domain="[('active', '=', True)]", help="Amenities available in this room")
