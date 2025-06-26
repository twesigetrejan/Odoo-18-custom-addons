from odoo import models, fields, api

class RoomCategory(models.Model):
    _name = 'hostel.room.category'
    _description = 'Hostel Room Category'
    name = fields.Char(string='Category Name')
    _rec_name = 'name'


    description = fields.Text(string='Description', help='Description of the room category')
    parent_id = fields.Many2one(
        'hostel.room.category', string='Parent Category',
        ondelete='cascade', index=True
        )
    active = fields.Boolean(string='Active', default=True, help='Activate/Deactivate this room category')
    child_ids = fields.One2many(
        'hostel.room.category', 'parent_id', string='Child Categories'
    )
    max_allow_days = fields.Integer(string= 'Maximum Allowed Days', help='Maximum number of days a student can stay in this room category')

    capacity = fields.Integer(string='Capacity', help='Maximum number of occupants allowed in this room category')
    
    amenity_ids = fields.Many2many(
        'hostel.amenity.type',
        'room_category_amenity_rel',
        'category_id',
        'amenity_id',
        string='Amenities'
    )
    room_cost = fields.Monetary(string= 'Rent amount', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True)
    
    # @api.model
    # def create_default_categories(self):
    #     """Create default categories when module is installed"""
    #     categories = [
    #         {'name': 'Single Room', 'description': 'A room for one person'},
    #         {'name': 'Double Room', 'description': 'A room for two persons'},
    #         {'name': 'Deluxe Room', 'description': 'A room with additional amenities'},
    #     ]
    #     for vals in categories:
    #         if not self.search([('name', '=', vals['name'])]):
    #             self.create(vals)
    #     return True
    