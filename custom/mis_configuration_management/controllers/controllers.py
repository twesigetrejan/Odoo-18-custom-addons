# -*- coding: utf-8 -*-
# from odoo import http


# class Custom\misConfigurationManagement(http.Controller):
#     @http.route('/custom\mis_configuration_management/custom\mis_configuration_management', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/custom\mis_configuration_management/custom\mis_configuration_management/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('custom\mis_configuration_management.listing', {
#             'root': '/custom\mis_configuration_management/custom\mis_configuration_management',
#             'objects': http.request.env['custom\mis_configuration_management.custom\mis_configuration_management'].search([]),
#         })

#     @http.route('/custom\mis_configuration_management/custom\mis_configuration_management/objects/<model("custom\mis_configuration_management.custom\mis_configuration_management"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('custom\mis_configuration_management.object', {
#             'object': obj
#         })

