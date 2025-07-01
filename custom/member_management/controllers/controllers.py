# -*- coding: utf-8 -*-
# from odoo import http


# class MemberManagement(http.Controller):
#     @http.route('/member_management/member_management', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/member_management/member_management/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('member_management.listing', {
#             'root': '/member_management/member_management',
#             'objects': http.request.env['member_management.member_management'].search([]),
#         })

#     @http.route('/member_management/member_management/objects/<model("member_management.member_management"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('member_management.object', {
#             'object': obj
#         })

