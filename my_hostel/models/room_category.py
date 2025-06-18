from odoo import models, fields, api

class RoomCategory(models.Model):
    _name = 'hostel.room.category'
    _description = 'Hostel Room Category'
    name = fields.Char(string='Category Name')

    description = fields.Text(string='Description', help='Description of the room category')
    parent_id = fields.Many2one(
        'hostel.room.category', string='Parent Category',
        ondelete='restrict', index=True
        )
    child_ids = fields.One2many(
        'hostel.room.category', 'parent_id', string='Child Categories'
    )


    def create_category(self):
        categ1 =  {
            'name': 'Single Room',
            'description': 'A room for one person',
        }
        categ2 = {
            'name': 'Double Room',
            'description': 'A room for two persons',
        }
        categ3 = {
            'name': 'Deluxe Room',
            'description': 'A room with additional amenities',
        }
    
        parent_category_val = {
            'name': 'Parent Category',
            'description': 'This is a parent category for room categories',
            'child_ids': [
                (0, 0, categ1),
                (0, 0, categ2),
                (0, 0, categ3)
            ]
        }
        self.env['hostel.room.category'].create(parent_category_val)
        return True