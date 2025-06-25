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
    
    def action_discharge(self):
        for rec in self:
            rec.status = 'discharge'

    def action_message(self):
        for rec in self:
            message = f"Student {rec.name} is in room {rec.room_id.room_no if rec.room_id else 'N/A'}"
            self.env.user.notify_info(message)

    
    
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

