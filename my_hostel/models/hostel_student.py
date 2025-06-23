from datetime import timedelta
from odoo import models, fields, api
from odoo.exceptions import UserError

class HostelStudent(models.Model):
    _name = 'hostel.student'
    _description = 'Information about a hostel student'
    _order = 'id desc, name'
    _rec_name = 'student_code'

    student_code = fields.Char(string='Student Code', help='Unique hostel code')
    student_id_number = fields.Char(string='University ID Number')
    name = fields.Char(string='Student Name', required=True)
    date_of_birth = fields.Date(string='Date of Birth')
    gender = fields.Selection([('male', 'Male'), ('female', 'Female')], string='Gender')
    phone = fields.Char(string='Phone Number')
    email = fields.Char(string='Email Address')
    photo = fields.Binary(string='Photo')
    blood_group = fields.Selection(
        [('A+', 'A+'), ('A-', 'A-'), ('B+', 'B+'), ('B-', 'B-'),
         ('O+', 'O+'), ('O-', 'O-'), ('AB+', 'AB+'), ('AB-', 'AB-')],
        string='Blood Group'
    )
    allergies = fields.Text(string='Allergies or Conditions')
    is_special_needs = fields.Boolean(string='Special Accommodation Needed?')

    hostel_id = fields.Many2one('hostel.hostel', string='Hostel')
    room_id = fields.Many2one('hostel.room', string='Room', domain="[('hostel_id', '=', hostel_id)]", required=True)
    admission_date = fields.Date(default=fields.Datetime.today, string='Admission Date')
    discharge_date = fields.Date(string='Discharge Date')
    duration = fields.Integer(string='Duration', compute='_compute_check_duration', store=True, inverse='_inverse_duration')

    status = fields.Selection([
        ("draft", "Draft"),
        ("reservation", "Reservation"),
        ("pending", "Pending"),
        ("paid", "Done"),
        ("discharge", "Discharge"),
        ("cancel", "Cancel")
    ], string="Status", copy=False, default="draft")

    faculty = fields.Char(string='Faculty')
    year_of_study = fields.Selection(
        [('1', 'Year 1'), ('2', 'Year 2'), ('3', 'Year 3'), ('4', 'Year 4'), ('5', 'Year 5')],
        string='Year of Study'
    )

    guardian_name = fields.Char(string="Guardian's Name")
    guardian_contact = fields.Char(string="Guardian's Contact")
    emergency_contact = fields.Char(string="Emergency Contact")
    remarks = fields.Text(string="Remarks")

    partner_id = fields.Many2one('res.partner', ondelete='cascade')
    active = fields.Boolean(default=True)

    # allocation_ids = fields.One2many('hostel.allocation', 'student_id', string='Allocation History')
    # visitor_ids = fields.One2many('hostel.visitor.log', 'student_id', string='Visitor Logs')

    @api.depends('admission_date', 'discharge_date')
    def _compute_check_duration(self):
        for record in self:
            if record.discharge_date and record.admission_date:
                record.duration = (record.discharge_date - record.admission_date).days

    def _inverse_duration(self):
        for student in self:
            if student.discharge_date and student.admission_date:
                duration = (student.discharge_date - student.admission_date).days
                if duration != student.duration:
                    student.discharge_date = (student.admission_date + timedelta(days=student.duration)).strftime('%Y-%m-%d')



























# class HostelStudent(models.Model):
#     _name = 'hostel.student'
#     _description = 'Information about a hostel student'
#     _order = 'id desc, name'
#     _rec_name = 'student_code'
    
    

#     hostel_id = fields.Many2one('hostel.hostel', string='Hostel')
#     room_id = fields.Many2one('hostel.room', string='Room', required=True, domain="[('hostel_id', '=', hostel_id)]")

#     student_code = fields.Char(string='Student Code', help='Unique code for the student')
#     name = fields.Char(string='Student Name', required=True)

#     gender = fields.Selection([('male', 'Male'), ('female', 'Female')], string='Gender')
#     active = fields.Boolean(string='Active', default=True, help='Activate/Deactivate student record')
#     status = fields.Selection([("draft", "Draft"), 
#        ("reservation", "Reservation"), ("pending", "Pending"), 
#        ("paid", "Done"),("discharge", "Discharge"), ("cancel", "Cancel")], 
#        string="Status", copy=False, default="draft", 
#        help="State of the student hostel") 
#     admission_date = fields.Date(default=fields.Datetime.today, string='Admission Date', help='Date when the student was admitted to the hostel')
#     discharge_date = fields.Date(string='Discharge Date', help='Date when the student left the hostel')
#     duration = fields.Integer(string='Duration', compute='_compute_check_duration', store=True, help='Duration of stay in the hostel in days', inverse='_inverse_duration')

#     partner_id = fields.Many2one('res.partner', ondelete='cascade', ) #or without the inherit, use delegate=True to inherit fields from res.partner

#     @api.depends('admission_date', 'discharge_date')
#     def _compute_check_duration(self):
#         """Compute the duration of stay in the hostel based on admission and discharge dates."""
#         for record in self:
#             if record.discharge_date and record.admission_date:
#                 record.duration = (record.discharge_date - record.admission_date).days

#     def _inverse_duration(self):
#         """Inverse method to set discharge date based on durati."""
#         for student in self:
#             if student.discharge_date and student.admission_date:
#                 duration = (student.discharge_date - student.admission_date).days
#                 if duration != student.duration:
#                     student.discharge_date = (student.admission_date + timedelta(days=student.duration)).strftime('%Y-%m-%d')

    # def action_assign_room(self):
    #     self.ensure_one()
    #     if self.status != 'paid':
    #         raise UserError("You cannot assign a room to this student until the payment is made.")
    #     room_as_superuser = self.env['hostel.room'].sudo()

    #     room_rec = room_as_superuser.create({ 
    #        "name": "Room A-103", 
    #        "room_no": "A-103", 
    #        "floor_no": 1, 
    #        "room_category_id": self.env.ref("my_hostel.single_room_categ").id, 
    #        "hostel_id": self.hostel_id.id, 
    #    })
