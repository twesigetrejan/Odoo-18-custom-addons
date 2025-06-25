
from odoo.exceptions import ValidationError
from odoo import models, api, fields

class HostelCategory(models.Model):
    _name = 'hostel.category'
    _parent_store = True
    _parent_name = 'parent_id'
    _description = 'Hostel Category'

    name = fields.Char('Hostel Category', required=True)
    description = fields.Text('Description')

    parent_id = fields.Many2one(
        'hostel.category',
        string='Parent Category',
        ondelete='restrict',
        index=True,
    )
    parent_path = fields.Char(index=True, unnaccent= False)
    child_ids = fields.One2many(
        'hostel.category',
        'parent_id',
        string='Child Categories',
    )

    category_type = fields.Selection(
        [('male', 'Male Only'), ('female', 'Female Only'), ('mixed', 'Mixed')],
        string='Type',
        default='mixed'
    )
    is_premium = fields.Boolean(string='Premium Category?')
    amenity_ids = fields.Many2many(
        'hostel.amenity.type',
        'hostel_category_amenity_rel',
        'category_id',
        'amenity_id',
        string='Available Amenities'
    )
    hostel_ids = fields.One2many('hostel.hostel', 'category_id', string='Hostels in this Category')

    active = fields.Boolean(default=True)

    @api.constrains('parent_id')
    def _check_heirarchy(self):
        if not self._check_recursion():
            raise models.ValidationError(
                'Error! You cannot create recursive categories.'
            )

# class HostelCategory(models.Model):
#     _name = 'hostel.category'
#     _parent_store = True
#     _parent_name = 'parent_id'
#     _description = 'Hostel Category'
    
#     name = fields.Char('Hostel category')
    
#     parent_id = fields.Many2one(
#         'hostel.category',
#         string = 'Parent Category',
#         ondelete = 'restrict',
#         index = True,
#     )
#     parent_path = fields.Char(index= True, unaccent=False)
#     child_ids = fields.One2many(
#         'hostel.category',
#         'parent_id',
#         string = 'Child Categories',
#     )

#     @api.constrains('parent_id')
#     def _check_heirarchy(self):
#         if not self._check_recursion():
#             raise models.ValidationError(
#                 'Error! You cannot create recursive categories.'
#             )
        
    