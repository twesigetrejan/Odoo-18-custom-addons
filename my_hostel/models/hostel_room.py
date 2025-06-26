from datetime import timedelta
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
    room_code = fields.Char(string='Room unique number')
    hostel_id = fields.Many2one('hostel.hostel', string='Hostel', required=True, help='Hostel to which the room belongs')
    category_id = fields.Many2one(
        'hostel.room.category', 
        string='Room Category',
        help='Category of this room',
        domain="[('active', '=', True)]",
        required=False
    )
    floor_number = fields.Integer(string='Floor Number')
    # capacity = fields.Integer(string='Capacity', help='Number of occupants the room can hold')
    rent_amount = fields.Monetary(string='Rent amount', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True)
    active = fields.Boolean(string='Active', default=True)
    notes = fields.Text(string='Notes')
    student_per_room = fields.Integer("Room capacity", required=True, help="Number of students allowed in this room")
    availability = fields.Float(compute = '_compute_check_availability', string='Availability', help="Room availability in hostel", store=True)
    date_terminate = fields.Date(string='Date of Termination', help='Date when the room was terminated or closed')
    # cost_price = fields.Float('Room cost', help='Cost of the room per month', default=0.0)
    
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
    previous_room_id = fields.Many2one('hostel.room', string='Previous Room')


    state = fields.Selection(
        [('draft', 'Unavailable'), ('available', 'Available'), ('closed', 'Closed'),], string='State', default='draft', help='State of the room')
    remarks = fields.Text(string='Remarks', help='Additional remarks about the room')

    @api.onchange('category_id')
    def _onchange_category_id(self):
        for room in self:
            if room.category_id:
                room.rent_amount = room.category_id.room_cost
                room.currency_id = room.category_id.currency_id.id

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
        self.date_terminate = False
        return super(HostelRoom, self).make_available()
    
        # self.change_state('available')

    # def make_closed(self):
    #     """Change the state of the room if change is allowed."""
    #     day_to_allocate = self.category_id.max_allow_days or 10
    #     self.date_return = fields.Date.today() + timedelta(days=day_to_allocate)
    #     return super(HostelRoom, self).make_closed()
    def make_closed(self):
        """Change the state of the room if change is allowed."""
        if not self.category_id:
            raise UserError(_("Please select a room category first"))
        day_to_allocate = self.category_id.max_allow_days or 10
        self.date_terminate = fields.Date.today() + timedelta(days=day_to_allocate)
        self.state = 'closed'
    
        # self.change_state('closed')


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

    def filter_members(self):
        all_rooms = self.search([])
        return self.rooms_with_multiple_members(all_rooms)

    def rooms_with_multiple_members(self, all_rooms):
        def predicate(room):
            if len(room.student_ids) > 1:
                _logger.info(f"Room {room.room_no} has multiple members: {len(room.student_ids)}")
                return True
            return False
        return all_rooms.filtered(predicate)


    @api.model
    def get_members_names(self, rooms):
        """Get names of all members in the given rooms."""
        return rooms.mapped('member_ids.name')

    # @api.model
    # def sort_rooms_by_capacity(self, rooms):
    #     return rooms.sorted(key= 'capacity', reverse=True)
    
    @api.model
    def create(self, values):
        """Override create method to ensure users who arent part of the hostel managers cannot create room remarks."""
        if not self.env.user.has_group('my_hostel.group_hostel_manager'):
            if values.get('remarks'):
                raise UserError(_("You are not allowed to create remarks for rooms."))
        return super(HostelRoom, self).create(values)
    
    def write(self, values):
        """Override write method to ensure users who arent part of the hostel managers cannot create room remarks."""
        if not self.env.user.has_group('my_hostel.group_hostel_manager'):
            if values.get('remarks'):
                raise UserError(_("You are not allowed to create remarks for rooms."))
        return super(HostelRoom, self).write(values)
    

    def name_get(self, name):
        """Override name_get to return room code and hostel name."""
        result = []
        for room in self:
            member = room.member_ids.mapped('name')
            name = '%s (%s)' % (room.name, ', '.join(member))
            result.append((room.id, name))
            return result

    # def name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
    #     args = args or []
    #     # Defensive: ensure args is always a list
    #     if not isinstance(args, list):
    #         args = list(args)

    #     if name:
    #         args = args + [('room_no', operator, name)]
    #     # Use search and name_get as Odoo expects
    #     return self.search(args, limit=limit).name_get()



    
    def get_average_cost(self):
        grouped_result  = self.read_group(
            [('cost_price', '!=', False)],
            ['category_id', 'cost_price:avg'],
            ['category_id']
        )
        return grouped_result
    
    @api.model
    def update_room_price1(self): 
        all_rooms = self.search([]) 
        for room in all_rooms: 
            room.cost_price += 10

    @api.model 
    def update_room_price(self, category, amount_to_increase): 
        category_rooms = self.search([('category_id', '=', category.id)]) 
        for room in category_rooms: 
            room.cost_price += amount_to_increase

    # @api.model
    # def action_remove_room(self):
    #     """Action to remove all members from the room."""
    #     if self.env.context.get('is_hostel_room'):
    #         self.room_id = False

    # def action_remove_room_members(self):
    #     """Action to remove all members from the room."""
    #     student.with_context(is_hostel_room = True).action_remove_room()
