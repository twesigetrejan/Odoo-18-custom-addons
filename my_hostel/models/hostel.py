import base64
from odoo import api, fields, models
from odoo.modules.module import get_module_resource
import logging
_logger = logging.getLogger(__name__)

class Hostel(models.Model):
    _name = 'hostel.hostel'
    _description = 'Information about a hostel'
    _order = 'id desc, name'
    _rec_name = 'hostel_code'
    _inherit = ['image.mixin']

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
    image = fields.Binary(
        string='Hostel Image',
        default=lambda self: self._get_default_image(),
        attachment=True,
        prefetch= False,
        help="Upload your hostel image"
    )
    active = fields.Boolean('Active', default=True, help='Activate/Deactivate hostel record')
    type = fields.Selection(
        [("male", "Boys"), ("female", "Girls"), ("common", "Common")],
        help='Type of hostel',
        required=True,
        default='common'
    )
    other_info = fields.Text(string='Other information', help='Additional information about the hostel')
    description = fields.Html('Description')
    hostel_rating = fields.Float(
        string='Hostel average rating',
        digits=(14, 4),
        help='Average rating of the hostel based on user feedback'
    )
    category_id = fields.Many2one('hostel.category', string='Category')
    ref_doc_id = fields.Reference(
        selection='_referencable_models',
        string='Reference Document',
        help='Reference to a document related to the hostel'
    )
    hostel_capacity = fields.Integer(
        string='Hostel Capacity',
        help='Total number of occupants the hostel can accommodate'
    )
    amenity_id = fields.One2many(
        'hostel.room.amenity',
        'room_id',
        string='Hostel amenities available',
        required=False
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
    
    @api.model
    def _get_default_image(self):
        """Return default image as base64 with better error handling"""
        try:
            image_path = get_module_resource('my_hostel', 'static/src/img', 'hostel-default.jpg')
            if not image_path:
                raise FileNotFoundError
            
            with open(image_path, 'rb') as f:
                return base64.b64encode(f.read())
        except Exception as e:
            _logger.warning("Failed to load default hostel image: %s", str(e))
            return False

    @api.model
    def create(self, vals):
        # Ensure image is properly processed
        if 'image' in vals and vals['image']:
            if isinstance(vals['image'], str) and vals['image'].startswith('data:image'):
                vals['image'] = vals['image'].split('base64,')[-1]
        return super().create(vals)

    def write(self, vals):
        # Handle image updates
        if 'image' in vals and vals['image']:
            if isinstance(vals['image'], str) and vals['image'].startswith('data:image'):
                vals['image'] = vals['image'].split('base64,')[-1]
            elif vals['image'] is False:
                vals['image'] = None
        return super().write(vals)