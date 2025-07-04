# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenEduCat Inc
#    Copyright (C) 2009-TODAY OpenEduCat Inc(<https://www.openeducat.org>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Lesser General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from datetime import datetime

from dateutil.relativedelta import relativedelta
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class OpAdmission(models.Model):
    _name = "op.admission"
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = "application_number"
    _description = "Admission"
    _order = 'id DESC'

    name = fields.Char(
        'Name', required=True, translate=True)
    first_name = fields.Char(
        'First Name', required=True, translate=True)
    middle_name = fields.Char(
        'Middle Name', translate=True)
    last_name = fields.Char(
        'Last Name', required=True, translate=True)
    title = fields.Many2one(
        'res.partner.title', 'Title')
    application_number = fields.Char(
        'Application Number', size=16, copy=False,
        readonly=True, store=True)
    admission_date = fields.Date(
        'Admission Date', copy=False)
    application_date = fields.Datetime(
        'Application Date', required=True, copy=False,
        default=lambda self: fields.Datetime.now())
    birth_date = fields.Date(
        'Birth Date', required=True)
    course_id = fields.Many2one(
        'op.course', 'Course', required=True)
    batch_id = fields.Many2one(
        'op.batch', 'Batch', required=False)
    street = fields.Char(
        'Street', size=256)
    street2 = fields.Char(
        'Street2', size=256)
    phone = fields.Char(
        'Phone', size=16)
    mobile = fields.Char(
        'Mobile', size=16)
    email = fields.Char(
        'Email', size=256, required=True)
    city = fields.Char('City', size=64)
    zip = fields.Char('Zip', size=8)
    country_id = fields.Many2one(
        'res.country', 'Country')
    state_id = fields.Many2one(
        'res.country.state', 'States' ,domain="[('country_id', '=', country_id)]")
    fees = fields.Float('Fees')
    image = fields.Image('image')
    state = fields.Selection(
        [('draft', 'Draft'), ('submit', 'Submitted'),
         ('confirm', 'Confirmed'), ('admission', 'Admission Confirm'),
         ('reject', 'Rejected'), ('pending', 'Pending'),
         ('cancel', 'Cancelled'), ('done', 'Done')],
        'State', default='draft', tracking=True)
    due_date = fields.Date('Due Date')
    prev_institute_id = fields.Char('Previous Institute')
    prev_course_id = fields.Char('Previous Course')
    prev_result = fields.Char(
        'Previous Result', size=256)
    family_business = fields.Char(
        'Family Business', size=256)
    family_income = fields.Float(
        'Family Income')
    gender = fields.Selection(
        [('m', 'Male'), ('f', 'Female'), ('o', 'Other')],
        string='Gender',
        required=True)
    student_id = fields.Many2one(
        'op.student', 'Student')
    nbr = fields.Integer('No of Admission', readonly=True)
    register_id = fields.Many2one(
        'op.admission.register', 'Admission Register', required=True)
    partner_id = fields.Many2one('res.partner', 'Partner')
    is_student = fields.Boolean('Is Already Student')
    fees_term_id = fields.Many2one('op.fees.terms', 'Fees Term')
    active = fields.Boolean(default=True)
    discount = fields.Float(string='Discount (%)',
                            digits='Discount', default=0.0)

    fees_start_date = fields.Date('Fees Start Date')
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.user.company_id)

    _sql_constraints = [
        ('unique_application_number',
         'unique(application_number)',
         'Application Number must be unique per Application!'),
    ]

    @api.onchange('first_name', 'middle_name', 'last_name')
    def _onchange_name(self):
        if not self.middle_name:
            self.name = str(self.first_name) + " " + str(
                self.last_name
            )
        else:
            self.name = str(self.first_name) + " " + str(
                self.middle_name) + " " + str(self.last_name)

    @api.onchange('student_id', 'is_student')
    def onchange_student(self):
        if self.is_student and self.student_id:
            sd = self.student_id
            self.title = sd.title and sd.title.id or False
            self.first_name = sd.first_name
            self.middle_name = sd.middle_name
            self.last_name = sd.last_name
            self.birth_date = sd.birth_date
            self.gender = sd.gender
            self.image = sd.image_1920 or False
            self.street = sd.street or False
            self.street2 = sd.street2 or False
            self.phone = sd.phone or False
            self.mobile = sd.mobile or False
            self.email = sd.email or False
            self.zip = sd.zip or False
            self.city = sd.city or False
            self.country_id = sd.country_id and sd.country_id.id or False
            self.state_id = sd.state_id and sd.state_id.id or False
            self.partner_id = sd.partner_id and sd.partner_id.id or False
        else:
            self.birth_date = ''
            self.gender = ''
            self.image = False
            self.street = ''
            self.street2 = ''
            self.phone = ''
            self.mobile = ''
            self.zip = ''
            self.city = ''
            self.country_id = False
            self.state_id = False
            self.partner_id = False

    @api.onchange('register_id')
    def onchange_register(self):
        self.course_id = self.register_id.course_id
        self.fees = self.register_id.product_id.lst_price
        self.company_id = self.register_id.company_id

    @api.onchange('course_id')
    def onchange_course(self):
        self.batch_id = False
        term_id = False
        if self.course_id and self.course_id.fees_term_id:
            term_id = self.course_id.fees_term_id.id
        self.fees_term_id = term_id

    @api.onchange('state_id')
    def _onchange_state(self):
        if self.state_id.country_id and self.country_id != self.state_id.country_id:
            self.country_id = self.state_id.country_id

    @api.constrains('register_id', 'application_date')
    def _check_admission_register(self):
        for rec in self:
            start_date = fields.Date.from_string(rec.register_id.start_date)
            end_date = fields.Date.from_string(rec.register_id.end_date)
            application_date = fields.Date.from_string(rec.application_date)
            if application_date < start_date or application_date > end_date:
                raise ValidationError(_(
                    "Application Date should be between Start Date & End Date of Admission Register."))

    @api.constrains('birth_date')
    def _check_birthdate(self):
        for record in self:
            if record.birth_date and  record.birth_date > fields.Date.today():
                raise ValidationError(_(
                    "Birth Date can't be greater than current date!"))
            elif record and record.birth_date:
                today_date = fields.Date.today()
                day = (today_date - record.birth_date).days
                years = day // 365
                if years < self.register_id.minimum_age_criteria:
                    raise ValidationError(_(
                        "Not Eligible for Admission minimum "
                        "required age is :"
                        " %s " % self.register_id.minimum_age_criteria))

    @api.constrains('name')
    def create_sequence(self):
        if not self.application_number:
            self.application_number = self.env['ir.sequence'].next_by_code(
                        'op.admission') or '/'

    def submit_form(self):
        self.state = 'submit'

    def admission_confirm(self):
        self.state = 'admission'

    def confirm_in_progress(self):
        for record in self:
            record.state = 'confirm'

    def get_student_vals(self):
        enable_create_student_user=self.env['ir.config_parameter'].get_param('openeducat_admission.enable_create_student_user')
        for student in self:
            student_user=False
            if enable_create_student_user:
                student_user = self.env['res.users'].create({
                    'name': student.name,
                    'login': student.email if student.email else student.application_number,
                    'email': student.email if student.email else student.application_number,
                    'image_1920': self.image or False,
                    'is_student': True,
                    'company_id': self.company_id.id,
                    'company_ids': [(4, self.company_id.id)],
                    'groups_id': [
                        (6, 0,
                        [self.env.ref('base.group_portal').id])]
                })
            details = {
                'name':student.name,
                'phone': student.phone,
                'mobile': student.mobile,
                'email': student.email,
                'street': student.street,
                'street2': student.street2,
                'city': student.city,
                'country_id':
                    student.country_id and student.country_id.id or False,
                'state_id': student.state_id and student.state_id.id or False,
                'image_1920': student.image,
                'zip': student.zip,
            }
            if enable_create_student_user:
                student_user.partner_id.write(details)
            details.update({
                'title': student.title and student.title.id or False,
                'first_name': student.first_name,
                'middle_name': student.middle_name,
                'last_name': student.last_name,
                'birth_date': student.birth_date,
                'gender': student.gender if student.gender else False,
                'image_1920': student.image or False,
                'course_detail_ids': [[0, False, {
                    'course_id':
                        student.course_id and student.course_id.id or False,
                    'batch_id':
                        student.batch_id and student.batch_id.id or False,
                    'academic_years_id':
                        student.register_id.academic_years_id.id or False,
                    'academic_term_id':
                        student.register_id.academic_term_id.id or False,
                    'fees_term_id': student.fees_term_id.id,
                    'fees_start_date': student.fees_start_date,
                    'product_id': student.register_id.product_id.id,
                }]],
                'user_id': student_user.id if student_user else False,
                'company_id': self.company_id.id,
                'partner_id': student_user.partner_id.id
            })
            return details

    def enroll_student(self):
        for record in self:
            if record.register_id.max_count:
                total_admission = self.env['op.admission'].search_count(
                    [('register_id', '=', record.register_id.id),
                     ('state', '=', 'done')])
                if not total_admission < record.register_id.max_count:
                    msg = 'Max Admission In Admission Register :- (%s)' % (
                        record.register_id.max_count)
                    raise ValidationError(_(msg))
            if not record.student_id:
                vals = record.get_student_vals()
                if vals:
                    record.student_id = student_id = self.env[
                        'op.student'].create(vals).id
                    record.partner_id = record.student_id.partner_id.id if record else False

            else:
                student_id = record.student_id.id
                record.student_id.write({
                    'course_detail_ids': [[0, False, {
                        'course_id':
                            record.course_id and record.course_id.id or False,
                        'batch_id':
                            record.batch_id and record.batch_id.id or False,
                        'fees_term_id': record.fees_term_id.id,
                        'fees_start_date': record.fees_start_date,
                        'product_id': record.register_id.product_id.id,
                    }]],
                })
            if record.fees_term_id.fees_terms in ['fixed_days', 'fixed_date']:
                val = []
                product_id = record.register_id.product_id.id
                for line in record.fees_term_id.line_ids:
                    no_days = line.due_days
                    per_amount = line.value
                    amount = (per_amount * record.fees) / 100
                    dict_val = {
                        'fees_line_id': line.id,
                        'amount': amount,
                        'fees_factor': per_amount,
                        'product_id': product_id,
                        'discount': record.discount or record.fees_term_id.discount,
                        'state': 'draft',
                        'course_id': record.course_id and record.course_id.id or False,
                        'batch_id': record.batch_id and record.batch_id.id or False,
                    }
                    if line.due_date:
                        date = line.due_date
                        dict_val.update({
                            'date': date
                        })
                    elif self.fees_start_date:
                        date = self.fees_start_date + relativedelta(
                            days=no_days)
                        dict_val.update({
                            'date': date,
                        })
                    else:
                        date_now = (datetime.today() + relativedelta(
                            days=no_days)).date()
                        dict_val.update({
                            'date': date_now,
                        })
                    val.append([0, False, dict_val])
                record.student_id.write({
                    'fees_detail_ids': val
                })
            record.write({
                'nbr': 1,
                'state': 'done',
                'admission_date': fields.Date.today(),
                'student_id': student_id,
                'is_student': True,
            })
            reg_id = self.env['op.subject.registration'].create({
                'student_id': student_id,
                'batch_id': record.batch_id.id,
                'course_id': record.course_id.id,
                'min_unit_load': record.course_id.min_unit_load or 0.0,
                'max_unit_load': record.course_id.max_unit_load or 0.0,
                'state': 'draft',
            })
            # if not record.mobile:
            #     raise UserError(
            #         _('Please fill in the mobile number'))
            reg_id.get_subjects()

    def confirm_rejected(self):
        self.state = 'reject'

    def confirm_pending(self):
        self.state = 'pending'

    def confirm_to_draft(self):
        self.state = 'draft'

    def confirm_cancel(self):
        self.state = 'cancel'
        if self.is_student and self.student_id.fees_detail_ids:
            self.student_id.fees_detail_ids.state = 'cancel'

    def payment_process(self):
        self.state = 'fees_paid'

    def open_student(self):
        form_view = self.env.ref('openeducat_core.view_op_student_form')
        tree_view = self.env.ref('openeducat_core.view_op_student_tree')
        value = {
            'domain': str([('id', '=', self.student_id.id)]),
            'view_type': 'form',
            'view_mode': 'tree, form',
            'res_model': 'op.student',
            'view_id': False,
            'views': [(form_view and form_view.id or False, 'form'),
                      (tree_view and tree_view.id or False, 'tree')],
            'type': 'ir.actions.act_window',
            'res_id': self.student_id.id,
            'target': 'current',
            'nodestroy': True
        }
        self.state = 'done'
        return value

    def create_invoice(self):
        """ Create invoice for fee payment process of student """

        partner_id = self.env['res.partner'].create({'name': self.name})
        account_id = False
        product = self.register_id.product_id
        if product.id:
            account_id = product.property_account_income_id.id
        if not account_id:
            account_id = product.categ_id.property_account_income_categ_id.id
        if not account_id:
            raise UserError(
                _('There is no income account defined for this product: "%s". \
                   You may have to install a chart of account from Accounting \
                   app, settings menu.') % (product.name,))
        if self.fees <= 0.00:
            raise UserError(
                _('The value of the deposit amount must be positive.'))
        amount = self.fees
        name = product.name
        invoice = self.env['account.invoice'].create({
            'name': self.name,
            'origin': self.application_number,
            'move_type': 'out_invoice',
            'reference': False,
            'account_id': partner_id.property_account_receivable_id.id,
            'partner_id': partner_id.id,
            'invoice_line_ids': [(0, 0, {
                'name': name,
                'origin': self.application_number,
                'account_id': account_id,
                'price_unit': amount,
                'quantity': 1.0,
                'discount': 0.0,
                'uom_id': self.register_id.product_id.uom_id.id,
                'product_id': product.id,
            })],
        })
        invoice.compute_taxes()
        form_view = self.env.ref('account.invoice_form')
        tree_view = self.env.ref('account.invoice_tree')
        value = {
            'domain': str([('id', '=', invoice.id)]),
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'account.invoice',
            'view_id': False,
            'views': [(form_view and form_view.id or False, 'form'),
                      (tree_view and tree_view.id or False, 'tree')],
            'type': 'ir.actions.act_window',
            'res_id': invoice.id,
            'target': 'current',
            'nodestroy': True
        }
        self.partner_id = partner_id
        self.state = 'payment_process'
        return value

    @api.model
    def get_import_templates(self):
        return [{
            'label': _('Import Template for Admission'),
            'template': '/openeducat_admission/static/xls/op_admission.xls'
        }]


class OpStudentCourseInherit(models.Model):
    _inherit = "op.student.course"

    product_id = fields.Many2one(
        'product.product', 'Course Fees',
        domain=[('type', '=', 'service')], tracking=True)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    enable_create_student_user = fields.Boolean(config_parameter='openeducat_admission.enable_create_student_user',
    string='Enable Create Student User')
