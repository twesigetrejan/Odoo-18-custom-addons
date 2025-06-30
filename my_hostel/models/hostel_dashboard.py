from odoo import models, api
import os
from pathlib import Path
from datetime import datetime, timedelta

class HostelDashboard(models.Model):
    _name = 'hostel.dashboard'
    _description = 'Hostel Dashboard Metrics'

    @api.model
    def _compute_metrics(self):
        total_hostels = self.env['hostel.hostel'].search_count([])
        total_rooms = self.env['hostel.room'].search_count([])
        total_students = self.env['hostel.student'].search_count([])
        rooms = self.env['hostel.room'].search([])
        total_rent = sum(room.rent_amount for room in rooms if room.rent_amount is not None) or 0.0
        total_amenities = self.env['hostel.room.amenity'].search_count([])
        avg_rent = total_rent / total_rooms if total_rooms else 0.0
        occupancy_rate = (total_students / (total_rooms * self.env['hostel.room'].search([], limit=1).student_per_room or 1) * 100) if total_rooms else 0.0

        # Existing metric
        occupied_rooms = self.env['hostel.room'].search_count([('student_ids', '!=', False)])

        # New metrics
        hostels = self.env['hostel.hostel'].search([])
        avg_room_occupancy_rate = sum(
            (self.env['hostel.room'].search_count([('hostel_id', '=', hostel.id), ('student_ids', '!=', False)]) /
             self.env['hostel.room'].search_count([('hostel_id', '=', hostel.id)]) * 100 if
             self.env['hostel.room'].search_count([('hostel_id', '=', hostel.id)]) else 0.0)
            for hostel in hostels
        ) / total_hostels if total_hostels else 0.0

        amenity_counts = self.env['hostel.room.amenity'].read_group(
            [('active', '=', True)], ['amenity_type_id'], ['amenity_type_id']
        )
        most_common_amenity = max(amenity_counts, key=lambda x: x['amenity_type_id_count'], default={'amenity_type_id': False})
        most_common_amenity_name = self.env['hostel.amenity.type'].browse(most_common_amenity['amenity_type_id'][0]).name if most_common_amenity['amenity_type_id'] else 'None'

        # Updated unpaid rent calculation
        unpaid_rent = sum(room.rent_amount for room in rooms if room.rent_amount and not room.is_rent_paid) or 0.0

        # Simulate unpaid rent over time with ISO strings
        unpaid_rent_data = [
            {'date': (datetime.now() - timedelta(days=i)).isoformat(), 'amount': unpaid_rent * (1 + i * 0.1)}
            for i in range(30)  # Last 30 days
        ]

        return {
            'total_hostels': total_hostels,
            'total_rooms': total_rooms,
            'total_students': total_students,
            'total_rent': total_rent,
            'total_amenities': total_amenities,
            'avg_rent': avg_rent,
            'occupancy_rate': occupancy_rate,
            'occupied_rooms': occupied_rooms,
            'avg_room_occupancy_rate': avg_room_occupancy_rate,
            'most_common_amenity': most_common_amenity_name,
            'unpaid_rent': unpaid_rent,
            'unpaid_rent_data': unpaid_rent_data,
        }

    @api.model
    def get_overview_metrics(self):
        return self._compute_metrics()

    @api.model
    def generate_pdf_report(self):
        metrics = self._compute_metrics()
        latex_content = r"""
\documentclass[a4paper,12pt]{article}
\usepackage[utf8]{inputenc}
\usepackage{geometry}
\geometry{a4paper, margin=1in}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{colortbl}
\usepackage{amsmath}
\usepackage{amsfonts}
\usepackage{fancyhdr}
\pagestyle{fancy}
\fancyhf{}
\fancyhead[L]{Hostel Management Report}
\fancyhead[R]{Date: \today}
\fancyfoot[C]{\thepage}

\begin{document}

\section*{Hostel Overview Report}
\hrule
Generating detailed hostel statistics for management review.

\begin{center}
\begin{tabular}{l r}
\toprule
Metric & Value \\
\midrule
Total Hostels & {total_hostels} \\
Total Rooms & {total_rooms} \\
Total Students & {total_students} \\
Total Rent (UGX) & {total_rent:.2f} \\
Total Amenities & {total_amenities} \\
Average Rent (UGX) & {avg_rent:.2f} \\
Occupancy Rate (%) & {occupancy_rate:.2f} \\
Occupied Rooms & {occupied_rooms} \\
Avg Room Occupancy Rate (%) & {avg_room_occupancy_rate:.2f} \\
Most Common Amenity & {most_common_amenity} \\
Unpaid Rent (UGX) & {unpaid_rent:.2f} \\
\bottomrule
\end{tabular}
\end{center}

\end{document}
""".format(
            total_hostels=metrics['total_hostels'],
            total_rooms=metrics['total_rooms'],
            total_students=metrics['total_students'],
            total_rent=metrics['total_rent'],
            total_amenities=metrics['total_amenities'],
            avg_rent=metrics['avg_rent'],
            occupancy_rate=metrics['occupancy_rate'],
            occupied_rooms=metrics['occupied_rooms'],
            avg_room_occupancy_rate=metrics['avg_room_occupancy_rate'],
            most_common_amenity=metrics['most_common_amenity'],
            unpaid_rent=metrics['unpaid_rent']
        )

        temp_file = Path('/tmp/hostel_report.tex')
        temp_file.write_text(latex_content, encoding='utf-8')

        pdf_path = '/tmp/hostel_report.pdf'
        os.system(f"latexmk -pdf {temp_file}")
        with open(pdf_path, 'rb') as f:
            pdf_data = f.read()

        return {
            'type': 'ir.actions.act_url',
            'url': 'data:application/pdf;base64,' + pdf_data.decode('utf-8').encode('base64').decode('utf-8'),
            'target': 'self',
        }