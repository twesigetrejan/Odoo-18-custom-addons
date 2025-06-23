from odoo import models, fields

class HostelAmenityType(models.Model):
    _name = 'hostel.amenity.type'
    _description = 'Hostel Amenity Type'
    _rec_name = 'name'

    name = fields.Selection(
        [
            ('wifi', 'Wi-Fi'),
            ('study_table', 'Study Table'),
            ('wardrobe', 'Wardrobe'),
            ('fan', 'Fan'),
            ('reading_light', 'Reading Light'),
            ('laundry_service', 'Laundry Service'),
            ('mini_fridge', 'Mini Fridge'),
            ('balcony', 'Balcony'),
            ('tv', 'Television'),
            ('kitchen_access', 'Kitchen Access'),
            ('gym_access', 'Gym Access'),
            ('hot_water', 'Hot Water'),
        ],
        string='Amenity Name',
        required=True
    )
    description = fields.Text(string='Description')
