from odoo import models, api

class HostelDashboard(models.Model):
    _name = 'hostel.dashboard'
    _description = 'Hostel Dashboard Metrics'

    @api.model
    def _compute_metrics(self):
        # Use search_count and search_read to fetch data
        total_hostels = self.env['hostel.hostel'].search_count([])
        total_rooms = self.env['hostel.room'].search_count([])
        total_students = self.env['hostel.student'].search_count([])
        # Fetch rent amounts and sum them safely
        rooms = self.env['hostel.room'].search([])
        total_rent = sum(room.rent_amount for room in rooms if room.rent_amount is not None) or 0.0

        return {
            'total_hostels': total_hostels,
            'total_rooms': total_rooms,
            'total_students': total_students,
            'total_rent': total_rent,
        }

    @api.model
    def get_overview_metrics(self):
        return self._compute_metrics()

# from odoo import models, api

# class HostelDashboard(models.Model):
#     _name = 'hostel.dashboard'
#     _description = 'Hostel Dashboard Metrics'

#     @api.model
#     def get_overview_metrics(self):
#         total_hostels = self.env['hostel.hostel'].search_count([])
#         total_rooms = self.env['hostel.room'].search_count([])
#         total_students = self.env['hostel.student'].search_count([])
#         total_rent = sum(self.env['hostel.room'].search([]).mapped('rent_amount'))

#         return {
#             'total_hostels': total_hostels,
#             'total_rooms': total_rooms,
#             'total_students': total_students,
#             'total_rent': total_rent,
#         }

