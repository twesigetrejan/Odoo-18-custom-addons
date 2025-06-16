from odoo import models, fields, api

class HostelAmenities(models.Model):
    _name = 'hostel.amenities'
    _description = 'Information about hostel amenities'
    _order = 'id desc, name'

    name = fields.Char(string='Amenity Name', help='Name of the amenity')
    active = fields.Boolean(string='Active', default=True, help='Activate/Deactivate whether amenity should be given to students')
  



# from odoo import models, fields, api


# class HostelAmenities(models.Model):
#     _name = 'hostel.amenities'
#     _description = 'Information about hostel amenities'
#     _order = 'id desc, name'
#     _rec_name = 'amenity_code'

#     name = fields.Char(string='Amenity Name',help='Name of the amenity')
#     active = fields.Boolean(string='Active', default=True, help='Activate/Deactivate whether amenity should be given to students')
