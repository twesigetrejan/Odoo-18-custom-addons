from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from odoo.tools.translate import _
import logging

_logger = logging.getLogger(__name__)
class HostelRoom(models.Model):
    _name = 'hostel.room'
    _description = 'Information about a hostel room'
    _order = 'id desc, room_code'
    _rec_name = 'room_code'
    _sql_constraints = [
        ('room_no_unique', 'UNIQUE(room_no)', 'Room number must be unique!'),]
    _inherit = ['base.archive']
    
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

    state = fields.Selection(
        [('draft', 'Unavailable'), ('available', 'Available'), ('closed', 'Closed'),], string='State', default='draft', help='State of the room')
    
    @api.model
    def is_allowed_transition(self, old_state, new_state):
        """Check if the transition from old_state to new_state is allowed."""
        allowed  = [('draft', 'available'), ('available', 'Available'), ('closed', 'Closed')]
        return (old_state, new_state) in allowed
    
    def change_state(self, new_state):
        """Change the state of the room if the transition is allowed."""
        for room in self:
            if room.is_allowed_transition(room.state, new_state):
                room.state = new_state
            else:
                msg = _("Transition from %s to %s is not allowed.") % (room.state, new_state)
                raise UserError(msg)
    
    def make_available(self):
        """Change the state of the room if change is allowed."""
        self.change_state('available')
    def make_closed(self):
        """Change the state of the room if change is allowed."""
        self.change_state('closed')


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


    def log_all_room_members(self):
        """Log all students assigned to this room."""
        for room in self:
            students = room.student_ids
            if students:
                student_names = ', '.join(students.mapped('name'))
                _logger.info(f"Room {room.room_no} has the following members: {student_names}")
            else:
                _logger.info(f"Room {room.room_no} has no members assigned.")
        return True
    

    def find_room(self):
        """Find a room based on the room number and name."""
        domain = [ 
            '|', 
                '&', ('name', 'ilike', 'Room Name'), 
                    ('category_id.name', 'ilike', 'Category Name'), 
                '&', ('name', 'ilike', 'Second Room Name 2'), 
                    ('category_id.name', 'ilike', 'SecondCategory Name 2') 
        ]

        