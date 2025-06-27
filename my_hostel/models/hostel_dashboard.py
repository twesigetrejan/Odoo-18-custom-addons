from odoo import models, api

class HostelDashboard(models.Model):
    _name = 'hostel.dashboard'
    _description = 'Hostel Dashboard Metrics'

    @api.model
    def get_overview_metrics(self):
        total_hostels = self.env['hostel.hostel'].search_count([])
        total_rooms = self.env['hostel.room'].search_count([])
        total_students = self.env['hostel.student'].search_count([])
        total_rent = sum(self.env['hostel.room'].search([]).mapped('rent_amount'))

        return {
            'total_hostels': total_hostels,
            'total_rooms': total_rooms,
            'total_students': total_students,
            'total_rent': total_rent,
        }
