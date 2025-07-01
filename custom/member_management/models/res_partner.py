from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from ..config import (BASE_URL, LOGIN_ENDPOINT, CREATE_MEMBERS_COLLECTION_ENDPOINT, CREATE_UPDATE_MEMBERS_COLLECTION_ENDPOINT, USERNAME, PASSWORD, get_config, UPLOAD_FILE_ENDPOINT)
import requests
import logging
import re
from datetime import datetime, date
from PIL import Image
import io
import base64
from lxml import etree

CLIENT_ACTION = 'ir.actions.client'

_logger = logging.getLogger(__name__)

class ResPartner(models.Model):
    _inherit = "res.partner"
    _inherit_mixin = ['api.token.mixin']
    _order = 'member_id asc'
    
    is_sacco_member = fields.Boolean('Register as SACCO member')
    member_id = fields.Char(string='Member Id')
    username = fields.Char(string='Username', readonly=True, copy=False)
    has_username = fields.Boolean(string='Has Username', compute='_compute_has_username', store=False)
    first_name = fields.Char(string="First Name")
    middle_name = fields.Char(string="Middle Name")
    last_name = fields.Char(string="Last Name")
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
    ], string="Gender", default='male')
    celebration_point = fields.Char(string="Celebration Point", help="The location where the member prefers to celebrate their service.") # Y-Save specific
    role = fields.Selection([('member', 'Sacco Member'), ('admin', 'Admin')], string="Role")
    date_of_birth = fields.Date(string="Date of Birth")
    id_type = fields.Selection([('nationalId', 'National ID'), ('passport', 'Passport'), ('drivingLicense', 'Driving License')], string="ID Type")
    id_number = fields.Char(string="ID Number")
    member_type = fields.Selection([
        ('individual', 'Individual'),
        ('group', 'Group'),
        ('joint', 'Joint'),
        ('church', 'Church'),
        ('company', 'Company'),
    ], string="Member Type")
    employment_status = fields.Selection([
        ('employed', 'Employed'),
        ('selfEmployed', 'Self Employed')
    ], string="Employment Status")
    marital_status = fields.Selection([
        ('single', 'Single'),
        ('married', 'Married'),
        ('divorced', 'Divorced'),
    ], string="Marital Status")
    registration_date = fields.Date(string="Registration Date")
    activation_status = fields.Selection([
        ('activated', 'Activated'),
        ('deactivated', 'Deactivated')
    ], string="Activation Status", default="deactivated")
    
    # Contact Details
    res_address_line1 = fields.Char(string="Address Line 1")
    res_address_line2 = fields.Char(string="Address Line 2")
    primary_phone = fields.Char(string="Primary Phone (Mobile Number)", help="Primary phone number for the member, typically a mobile number.")
    secondary_phone = fields.Char(string="Secondary Phone (Home Number)")
    village = fields.Char(string="Village")
    parish = fields.Char(string="Parish")
    sub_county = fields.Char(string="Sub County")
    district = fields.Char(string="District")
    postal_address = fields.Char(string="Postal Code")
    
    # Next of Kin Details
    next_of_kin_name = fields.Char(string="Name")    
    next_of_kin_relationship = fields.Char(string="Relationship")
    next_of_kin_dob = fields.Date(string="Date of Birth")
    next_of_kin_phone = fields.Char(string="Phone Number")
    next_of_kin_address = fields.Char(string="Address")
    next_of_kin_email = fields.Char(string="Email")
    next_of_kin_id_type = fields.Selection([
        ('nationalId', 'National ID'),
        ('passport', 'Passport'),
        ('drivingLicense', 'Driving License')
    ], string="ID Type")
    next_of_kin_id_number = fields.Char(string="ID Number")
    attachment_document_ids = fields.One2many('ir.attachment', 'res_id', string='Attachment Document', domain=[('res_model', '=', 'res.partner')], help="Attachments related to the member's profile, such as ID documents, photos, etc.")
    attachment_number = fields.Integer(compute='_compute_attachment_number', string='Number of Attachments')
    
    # Membership Details
    joining_date = fields.Date(string="Joining Date", default=fields.Date.context_today)
    membership_status = fields.Selection([
        ('details_processing', 'Processing Member Details'),
        ('fee_processing', 'Processing Membership Fee'),
        ('active', 'Activacted'),
        ('inactive', 'Deactivated'),
        ('closed', 'Closed'),
    ], string="Membership Status", default="details_processing")
    exit_date = fields.Date(string="Exit Date")
    branch_code = fields.Char(string="Branch Code")
    closure_id = fields.Char(string="Close Id", help="Id allocated to member on account closure")
    secondary_email = fields.Char(
        string="Secondary Email",
        help="Secondary email address, if applicable (e.g., for Joint Accounts or additional reference)."
    )
    secondary_date_of_birth = fields.Date(
        string="Secondary Date of Birth",
        help="Secondary date of birth, if applicable (i.e, for Joint Accounts)."
    )
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.user.company_id.id)
    
    # Membership Fee Fields
    membership_fee_amount = fields.Float(string="Membership Fee Amount", compute='_compute_membership_fee_amount', readonly=True, store=False)
    membership_fee_paid = fields.Boolean(string="Membership Fee Paid", compute='_compute_membership_fee_status', store=True)
    member_onboarded = fields.Boolean(string="Member Onboarded", default=False, store=True, help="Has the Member been onboarded? This is set to True when the member's details are fully processed and the membership fee is paid.")
    membership_fee_journal_entry_id = fields.Many2one('account.move', string='Membership Fee Journal Entry', readonly=True)
    paying_account_id = fields.Many2one('account.account', string='Paying Account',
        help="The account to debit for the membership fee payment", domain="[('account_type', '=like', 'asset%')]")
    
    # Currency selection for balance display
    balance_currency_id = fields.Many2one('res.currency', string='Balance Currency', 
        help="Select the currency to display balances in. Only accounts in this currency will be summed.",
        default=lambda self: self.env.company.currency_id)
    
    # MIS fields
    mongo_db_id = fields.Char(string='Mongo DB ID', help='Unique mongo db ID from the source system')
    ref_id = fields.Char(string="Reference ID")    
    last_sync_date = fields.Datetime(string='Last Sync Date')
    in_sync = fields.Boolean(string='In Sync', default=True)
    
    # Sequence tracking
    last_member_sequence = fields.Integer(string='Last Member Sequence', default=0, copy=False, help='Stores the last used sequence number for member_id')

    # New field for tracking attention needed
    needs_attention = fields.Boolean(
        string='Needs Attention',
        default=False,
        help="Indicates if the member requires attention due to issues like welcome pack delivery failure."
    )

    # Birthday related fields
    is_birthday_this_month = fields.Boolean(
        string="Birthday This Month",
        compute="_compute_is_birthday_this_month",
        store=False,
        help="Indicates if the member's birthday is in the current month."
    )
    birthday_month = fields.Integer(
        string="Birthday Month",
        compute="_compute_birthday_components",
        store=True, # Set to store==True for sorting
        help="Month of the member's birthday for sorting."
    )
    birthday_day = fields.Integer(
        string="Birthday Day",
        compute="_compute_birthday_components",
        store=True, # Set to store==True for sorting
        help="Day of the member's birthday for sorting."
    )
    
    _rec_names_search = ['complete_name', 'email', 'ref', 'vat', 'company_registry', 'member_id', 'username']
    
    @api.depends('company_id')
    def _compute_membership_fee_amount(self):
        """Compute the membership fee amount from configuration."""
        config = self.env['sacco.membership.config'].search([], limit=1)
        for partner in self:
            partner.membership_fee_amount = config.membership_fee if config else 0.0
            
    @api.depends('date_of_birth')
    def _compute_is_birthday_this_month(self):
        current_month = datetime.now().month
        for partner in self:
            partner.is_birthday_this_month = (
                partner.date_of_birth and
                partner.date_of_birth.month == current_month
            )

    @api.depends('date_of_birth')
    def _compute_birthday_components(self):
        for partner in self:
            if partner.date_of_birth:
                partner.birthday_month = partner.date_of_birth.month
                partner.birthday_day = partner.date_of_birth.day
            else:
                partner.birthday_month = 0
                partner.birthday_day = 0

    @api.constrains('member_id')
    def _check_unique_member_id(self):
        for record in self:
            if record.is_sacco_member and record.member_id:
                # Skip if unchanged during update
                if record._origin and record._origin.member_id == record.member_id:
                    continue
                existing = self.search([
                    ('member_id', '=', record.member_id),
                    ('is_sacco_member', '=', True),
                    ('id', '!=', record.id)
                ])
                if existing:
                    raise ValidationError(_("The Member Id '%s' is already in use.") % record.member_id)

    @api.constrains('username')
    def _check_unique_username(self):
        for record in self:
            if record.is_sacco_member and record.username:
                # Skip if unchanged during update
                if record._origin and record._origin.username == record.username:
                    continue
                existing = self.search([
                    ('username', '=', record.username),
                    ('is_sacco_member', '=', True),
                    ('id', '!=', record.id)
                ])
                if existing:
                    raise ValidationError(_("The Username '%s' is already in use.") % record.username)

    # @api.constrains('id_type', 'id_number', 'is_sacco_member')
    # def _check_unique_id_type_number(self):
    #     for record in self:
    #         if record.is_sacco_member and record.id_type and record.id_number:
    #             # Skip if both id_type and id_number are unchanged during update
    #             if (record._origin and 
    #                 record._origin.id_type == record.id_type and 
    #                 record._origin.id_number == record.id_number):
    #                 continue
    #             existing = self.search([
    #                 ('id_type', '=', record.id_type),
    #                 ('id_number', '=', record.id_number),
    #                 ('is_sacco_member', '=', True),
    #                 ('id', '!=', record.id)
    #             ])
    #             if existing:
    #                 raise ValidationError(_("The combination of ID Type '%s' and ID Number '%s' is already in use for SACCO members.") % (record.id_type, record.id_number))
    
    # @api.constrains('secondary_email', 'is_sacco_member')
    # def _check_secondary_email(self):
    #     for record in self:
    #         if record.is_sacco_member and record.secondary_email:
    #             # Validate email format
    #             if not re.match(r"[^@]+@[^@]+\.[^@]+", record.secondary_email):
    #                 raise ValidationError(_("Invalid secondary email format"))
    #             # Check for uniqueness
    #             existing = self.search([
    #                 ('secondary_email', '=', record.secondary_email),
    #                 ('is_sacco_member', '=', True),
    #                 ('id', '!=', record.id)
    #             ])
    #             if existing:
    #                 raise ValidationError(_("The Secondary Email '%s' is already in use.") % record.secondary_email)
    #             # Ensure secondary email is different from primary email
    #             if record.secondary_email == record.email:
    #                 raise ValidationError(_("Secondary email cannot be the same as the primary email."))

    @api.constrains('primary_phone', 'is_sacco_member')
    def _check_unique_primary_phone(self):
        for record in self:
            if record.is_sacco_member and record.primary_phone:
                # Skip if unchanged during update
                if record._origin and record._origin.primary_phone == record.primary_phone:
                    continue
                existing = self.search([
                    ('primary_phone', '=', record.primary_phone),
                    ('is_sacco_member', '=', True),
                    ('id', '!=', record.id)
                ])
                if existing:
                    raise ValidationError(_("The Primary phone '%s' is already in use for SACCO members.") % record.primary_phone)

    @api.constrains('secondary_phone', 'is_sacco_member')
    def _check_unique_secondary_phone(self):
        for record in self:
            if record.is_sacco_member and record.secondary_phone:
                # Skip if unchanged during update
                if record._origin and record._origin.secondary_phone == record.secondary_phone:
                    continue
                existing = self.search([
                    ('secondary_phone', '=', record.secondary_phone),
                    ('is_sacco_member', '=', True),
                    ('id', '!=', record.id)
                ])
                if existing:
                    raise ValidationError(_("The Secondary phone '%s' is already in use for SACCO members.") % record.secondary_phone)

    @api.constrains('email', 'is_sacco_member')
    def _check_email(self):
        for record in self:
            if record.is_sacco_member and not self.env.context.get('external_sync'):
                if not record.email:
                    raise ValidationError(_("Email is required for SACCO members"))
                if not re.match(r"[^@]+@[^@]+\.[^@]+", record.email):
                    raise ValidationError(_("Invalid email format"))
                existing = self.search([
                    ('email', '=', record.email),
                    ('is_sacco_member', '=', True),
                    ('id', '!=', record.id)
                ])
                if existing:
                    raise ValidationError(_("The Email '%s' is already in use.") % record.email)

    @api.depends('is_sacco_member', 'company_id.sacco_accronym')
    def _compute_has_username(self):
        """Compute whether username should be displayed based on is_sacco_member and company sacco_accronym."""
        for partner in self:
            partner.has_username = partner.is_sacco_member and bool(partner.company_id.sacco_accronym)

    def _compute_attachment_number(self):
        for member in self:
            member.attachment_number = len(member.attachment_document_ids.ids)

    def action_get_attachment_view(self):
        self.ensure_one()
        res = self.env['ir.actions.act_window']._for_xml_id('base.action_attachment')
        res['domain'] = [('res_model', '=', 'res.partner'), ('res_id', 'in', self.ids)]
        res['context'] = {'default_res_model': 'res.partner', 'default_res_id': self.id}
        return res   
    
    @api.depends('membership_fee_journal_entry_id', 'membership_fee_journal_entry_id.state')
    def _compute_membership_fee_status(self):
        """Compute if the membership fee is paid based on the journal entry state."""
        for partner in self:
            was_paid = partner.membership_fee_paid
            partner.membership_fee_paid = bool(partner.membership_fee_journal_entry_id and partner.membership_fee_journal_entry_id.state == 'posted')
            # Automatically set member_onboarded to True if membership_fee_paid becomes True
            # if not was_paid and partner.membership_fee_paid and partner.membership_status == 'fee_processing':
            #     partner.member_onboarded = True
            #     partner.action_onboard_member()

    # @api.constrains('primary_phone', 'secondary_phone')
    # def _check_phone_numbers(self):
    #     phone_regex = r'^\+?[1-9]\d{1,14}$'
        
    #     for record in self:
    #         # Validate phone format
    #         if record.primary_phone and not re.match(phone_regex, record.primary_phone):
    #             raise ValidationError("Primary phone number must be in international format (e.g., +1234567890).")
    #         if record.secondary_phone and not re.match(phone_regex, record.secondary_phone):
    #             raise ValidationError("Secondary phone number must be in international format (e.g., +1234567890).")

    #         # Check if primary and secondary phones are the same
    #         if record.primary_phone and record.secondary_phone and record.primary_phone == record.secondary_phone:
    #             raise ValidationError("Primary and secondary phone numbers cannot be the same.")

    #         # Check for duplicate phone numbers across records
    #         if record.primary_phone:
    #             duplicates = self.search([
    #                 ('id', '!=', record.id),
    #                 '|',
    #                 ('primary_phone', '=', record.primary_phone),
    #                 ('secondary_phone', '=', record.primary_phone)
    #             ])
    #             if duplicates:
    #                 raise ValidationError(f"The primary phone number {record.primary_phone} is already used by another contact.")

    #         if record.secondary_phone:
    #             duplicates = self.search([
    #                 ('id', '!=', record.id),
    #                 '|',
    #                 ('primary_phone', '=', record.secondary_phone),
    #                 ('secondary_phone', '=', record.secondary_phone)
    #             ])
    #             if duplicates:
    #                 raise ValidationError(f"The secondary phone number {record.secondary_phone} is already used by another contact.")

    @api.model
    def _get_next_sequence(self):
        """Get the next sequence number based on the numerically highest member_id."""
        # Fetch all member_id values for SACCO members
        members = self.search([('member_id', '!=', False), ('is_sacco_member', '=', True)])
        max_number = 0
        for member in members:
            try:
                # Convert member_id to integer for numerical comparison
                current_number = int(member.member_id)
                max_number = max(max_number, current_number)
            except ValueError:
                # Skip non-numeric member_id values
                continue
        # Increment the highest number or start at 1 if none found
        next_number = max_number + 1
        # Format as zero-padded string (e.g., '0001')
        return next_number

    @api.model
    def _generate_username(self, member_id):
        """Generate username as <sacco_accronym><member_id>."""
        company = self.env.company
        if not company.sacco_accronym:
            raise ValidationError(_("Please set the SACCO Accronym in Company Settings before creating a member."))
        if not member_id:
            raise ValidationError(_("Member ID is required to generate Username."))
        # Ensure member_id is numeric and not prefixed
        clean_member_id = member_id
        
        if member_id.startswith(company.sacco_accronym):
            clean_member_id = member_id[len(company.sacco_accronym):]
        return f"{company.sacco_accronym}{clean_member_id}"

    def _validate_image(self, image_data, is_sacco_member):
        """Validate image dimensions and size for SACCO members."""
        if not is_sacco_member or not image_data:
            return
        
        try:
            # Decode base64 image
            image_bytes = base64.b64decode(image_data)
            
            # Check file size (5 MB = 5 * 1024 * 1024 bytes)
            image_size = len(image_bytes)
            if image_size > 5 * 1024 * 1024:
                _logger.error(f"Image validation failed: File size {image_size} bytes exceeds 5 MB limit")
                raise ValidationError(_("Photo must be at least 300 × 300 px and ≤ 5 MB"))
            
            # Check dimensions
            image = Image.open(io.BytesIO(image_bytes))
            width, height = image.size
            if width < 300 or height < 300:
                _logger.error(f"Image validation failed: Dimensions {width}x{height} are less than 300x300 px")
                raise ValidationError(_("Photo must be at least 300 × 300 px and ≤ 5 MB"))
            
            # Additional format validation (ensure it's a supported image format)
            if image.format not in ['JPEG', 'JPG', 'PNG', 'GIF', 'BMP', 'TIFF', 'WEBP', 'ICO', 'SVG', 'PSD', 'EPS', 'RAW', 'HEIC', 'HEIF']:
                _logger.error(f"Image validation failed: Unsupported format {image.format}")
                raise ValidationError(_("Invalid image format. Please upload a valid image (e.g., PNG, JPEG). Photo must be at least 300 × 300 px and ≤ 5 MB"))
                
        except base64.binascii.Error:
            _logger.error("Image validation failed: Invalid base64 encoding")
            raise ValidationError(_("Invalid image format. Please upload a valid image (e.g., PNG, JPEG). Photo must be at least 300 × 300 px and ≤ 5 MB"))
        except Exception as e:
            _logger.error(f"Image validation failed: {str(e)}")
            raise ValidationError(_("Invalid image format. Please upload a valid image (e.g., PNG, JPEG). Photo must be at least 300 × 300 px and ≤ 5 MB"))

    @api.model_create_multi
    def create(self, vals_list):
        _logger.info('Creating values to res.partner')
        company = self.env.company
        if not company.sacco_accronym:
            raise ValidationError(_("Please set the SACCO Accronym in Company Settings before creating a member."))

        for vals in vals_list:
            # Validate image before Odoo processes it
            is_sacco_member = vals.get('is_sacco_member', False)
            if 'image_1920' in vals:
                self._validate_image(vals['image_1920'], is_sacco_member)

            if is_sacco_member:
                # Generate member_id if not provided
                if not vals.get('member_id'):
                    next_sequence = self._get_next_sequence()
                    vals['member_id'] = str(next_sequence).zfill(4)
                    vals['last_member_sequence'] = next_sequence
                
                # Generate username based on member_id
                if not vals.get('username'):
                    # Ensure member_id is numeric before generating username
                    member_id = vals.get('member_id', '').strip()
                    if member_id.startswith(company.sacco_accronym):
                        member_id = member_id[len(company.sacco_accronym):]
                    vals['username'] = self._generate_username(member_id)
                
                # Set name based on first_name, middle_name, last_name
                name_parts = [part for part in [vals.get('first_name', ''), vals.get('middle_name', ''), vals.get('last_name', '')] if part]
                vals['name'] = " ".join(name_parts).strip()
                # Set initial membership_status
                vals['membership_status'] = 'details_processing'
        
        records = super(ResPartner, self).create(vals_list)
        records._sync_birthday_mailing_list_subscription()
        return records

    def write(self, vals):
        _logger.info('Writing values to res.partner')
        company = self.env.company
        if not company.sacco_accronym:
            raise ValidationError(_("Please set the SACCO Accronym in Company Settings before updating a member."))
        
        # Validate image before Odoo processes it
        if 'image_1920' in vals:
            # Determine if any record in self (or the updated vals) is a SACCO member
            for partner in self:
                is_sacco_member = vals.get('is_sacco_member', partner.is_sacco_member)
                self._validate_image(vals['image_1920'], is_sacco_member)

        for partner in self:
            if partner.is_sacco_member or vals.get('is_sacco_member'):
                # Ensure member_id is set for SACCO members
                if not vals.get('member_id') and not partner.member_id:
                    next_sequence = self._get_next_sequence()
                    vals['member_id'] = str(next_sequence).zfill(4)
                    vals['last_member_sequence'] = next_sequence

                # Handle member_id changes
                if 'member_id' in vals:
                    new_member_id = vals['member_id']
                    _logger.info(f"Updating member_id for {partner.name} from {partner.member_id} to {new_member_id}")
                    if new_member_id and new_member_id != partner.member_id:
                        if self.search([('member_id', '=', new_member_id), ('id', '!=', partner.id)]):
                            raise ValidationError(_("The Member Id '%s' is already in use.") % new_member_id)
                    
                    # Ensure member_id is numeric and strip prefix if needed
                    if new_member_id and isinstance(new_member_id, str):
                        if new_member_id.startswith(company.sacco_accronym):
                            new_member_id = new_member_id[len(company.sacco_accronym):]
                        vals['member_id'] = new_member_id
                        
                        # Update username based on new member_id
                        vals['username'] = self._generate_username(new_member_id)
                        
                        # Update last_member_sequence only if member_id is numeric
                        try:
                            new_sequence = int(new_member_id)
                            if new_sequence > partner.last_member_sequence:
                                vals['last_member_sequence'] = new_sequence
                        except ValueError:
                            pass  # Skip sequence update for non-numeric member_id
                    elif not new_member_id:
                        raise ValidationError(_("Member ID is required for SACCO members."))
                
                # Ensure username is set if not provided
                if 'username' not in vals and (partner.is_sacco_member or vals.get('is_sacco_member')):
                    member_id = vals.get('member_id', partner.member_id)
                    if member_id and isinstance(member_id, str):
                        if member_id.startswith(company.sacco_accronym):
                            member_id = member_id[len(company.sacco_accronym):]
                        vals['username'] = self._generate_username(member_id)
                    elif not member_id:
                        raise ValidationError(_("Member ID is required to generate Username for SACCO members."))
                
                # Update name if any name fields change
                if any(field in vals for field in ['first_name', 'middle_name', 'last_name']):
                    first_name = vals.get('first_name', partner.first_name)
                    middle_name = vals.get('middle_name', partner.middle_name)
                    last_name = vals.get('last_name', partner.last_name)
                    name_parts = [part for part in [first_name, middle_name, last_name] if part]
                    vals['name'] = " ".join(name_parts).strip()

        result = super(ResPartner, self).write(vals)
        # Ensure mailing list subscription status is updated after write
        self._sync_mailing_list_subscription()
        self._sync_birthday_mailing_list_subscription()
        return result

    # @api.constrains('id_type', 'id_number', 'is_sacco_member')
    # def _check_id_number(self):
    #     for record in self:
    #         if record.is_sacco_member and record.id_type and record.id_number:
    #             existing = self.search_count([
    #                 ('id_type', '=', record.id_type),
    #                 ('id_number', '=', record.id_number),
    #                 ('is_sacco_member', '=', True),
    #                 ('id', '!=', record.id)
    #             ])
    #             if existing > 0:
    #                 raise ValidationError(_("The combination of ID Type and ID Number must be unique for SACCO members."))
                
    @api.constrains('member_id', 'username')
    def _check_member_id_username(self):
        company = self.env.company
        if not company.sacco_accronym:
            raise ValidationError(_("Please set the SACCO Accronym in Company Settings before creating a member."))
        
        for record in self:
            if record.is_sacco_member:
                if not record.member_id:
                    raise ValidationError(_("Member ID is required for SACCO members."))
                if not record.username:
                    # Generate username if missing (shouldn't reach here due to create/write logic)
                    record.username = self._generate_username(record.member_id)
        
    @api.constrains('image_1920', 'is_sacco_member')
    def _check_image_quality(self):
        # This is a fallback in case the validation in create/write is bypassed
        for record in self:
            self._validate_image(record.image_1920, record.is_sacco_member)
            
    @api.onchange('primary_phone')
    def _onchange_primary_phone(self):
        if self.primary_phone:
            self.mobile = self.primary_phone

    @api.onchange('secondary_phone')
    def _onchange_secondary_phone(self):
        if self.secondary_phone:
            self.phone = self.secondary_phone

    @api.onchange('first_name', 'middle_name', 'last_name', 'is_sacco_member')
    def _onchange_sacco_member_names(self):
        if self.is_sacco_member:
            name_parts = [part for part in [self.first_name, self.middle_name, self.last_name] if part]
            self.name = " ".join(name_parts).strip()

    @api.onchange('is_sacco_member')
    def _onchange_is_sacco_member(self):
        if self.is_sacco_member and not self.member_id:
            next_sequence = self._get_next_sequence()
            self.member_id = str(next_sequence).zfill(4)
            self.last_member_sequence = next_sequence
            self.username = self._generate_username(self.member_id)
            self.membership_status = 'details_processing'

    @api.onchange('member_id')
    def _onchange_member_id(self):
        if self.is_sacco_member and self.member_id:
            self.username = self._generate_username(self.member_id)

    @api.depends('name', 'member_id', 'username') 
    def _compute_display_name(self): 
        for record in self: 
            name = record.name 
            if record.member_id: 
                name = f'{name} - {record.member_id}'
            if record.username:
                name = f'{name} ({record.username})'
            record.display_name = name
    
    def set_to_edit_mode(self):
        self.activation_status = 'deactivated'
        self.membership_status = 'inactive'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }
    
    def action_process_membership_fee(self):
        """Transition membership status to fee_processing."""
        self.ensure_one()
        if not self.is_sacco_member:
            raise ValidationError(_("This action is only available for SACCO members."))
        if self.membership_status != 'details_processing':
            raise ValidationError(_("Membership status must be 'Processing Member Details' to process the membership fee."))
        self.write({
            'membership_status': 'fee_processing',
            'activation_status': 'deactivated',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

    def action_pay_membership_fee(self):
        """Create a journal entry for the membership fee payment."""
        self.ensure_one()
        if not self.is_sacco_member:
            raise ValidationError(_("This action is only available for SACCO members."))
        if self.membership_fee_paid:
            raise ValidationError(_("Membership fee has already been paid for this member."))
        if self.membership_status != 'fee_processing':
            raise ValidationError(_("Membership status must be 'Processing Membership Fee' to pay the membership fee."))

        # Get membership fee configuration
        config = self.env['sacco.membership.config'].search([], limit=1)
        if not config:
            raise ValidationError(_("Membership fee configuration is not set. Please configure it under Members > Configuration."))
        
        if not self.paying_account_id:
            raise ValidationError(_("Please select a paying account to debit for the membership fee payment."))

        # Create journal entry
        journal_entry_vals = {
            'date': date.today(),
            'ref': f"Membership Fee Payment - {self.username or self.member_id}",
            'journal_id': config.membership_fee_journal_id.id,
            'company_id': config.membership_fee_journal_id.company_id.id,
            'line_ids': [
                (0, 0, {
                    'partner_id': self.id,
                    'account_id': self.paying_account_id.id,
                    'debit': config.membership_fee,
                    'credit': 0.0,
                    'name': f"Membership Fee Payment - {self.username or self.member_id}",
                    'date_maturity': date.today(),
                }),
                (0, 0, {
                    'partner_id': self.id,
                    'account_id': config.membership_fee_account_id.id,
                    'debit': 0.0,
                    'credit': config.membership_fee,
                    'name': f"Membership Fee Payment - {self.username or self.member_id}",
                    'date_maturity': date.today(),
                }),
            ],
        }

        try:
            journal_entry = self.env['account.move'].create(journal_entry_vals)
            journal_entry.action_post()
            self.membership_fee_journal_entry_id = journal_entry.id
        except Exception as e:
            _logger.error(f"Error creating membership fee journal entry for member {self.username}: {str(e)}")
            raise ValidationError(_("Failed to record membership fee payment: %s") % str(e))

    def action_onboard_member(self):
        """Send welcome pack, activate member, and set member_onboarded to True."""
        self.ensure_one()
        if not self.is_sacco_member:
            raise ValidationError(_("This action is only available for SACCO members."))
        if not self.membership_fee_paid:
            raise ValidationError(_("Membership fee must be paid before onboarding the member."))
        if self.member_onboarded:
            raise ValidationError(_("Member has already been onboarded."))

        try:            
            # Activate member
            self.write({
                'membership_status': 'active',
                'activation_status': 'activated',
                'member_onboarded': True,
                'in_sync': True,
            })
            # Sync with external system
            config = get_config(self.env)
            username = config.get('USERNAME')
            password = config.get('PASSWORD')
            if username and password:
                result = self.mongo_db_id and self.update_member_details() or self.upload_member_details()
            return {
                'type': CLIENT_ACTION,
                'tag': 'display_notification',
                'params': {
                    'title': 'Success',
                    'message': 'Member onboarded successfully.',
                    'sticky': True,
                    'type': 'success',
                    'next': {
                        'type': CLIENT_ACTION,
                        'tag': 'reload',
                    }
                }
            }
        except Exception as e:
            _logger.error(f"Failed to onboard member {self.username}: {str(e)}")
            self.needs_attention = True
            self.env.cr.commit()
            return self._show_notification('Error', str(e), 'error')

    def action_send_welcome_pack(self):
        """Resend the welcome pack email."""
        self.ensure_one()
        if not self.is_sacco_member:
            raise ValidationError("This action is only available for SACCO members.")
        try:
            self._send_welcome_pack()
            return {
                'type': CLIENT_ACTION,
                'tag': 'display_notification',
                'params': {
                    'title': 'Success',
                    'message': 'Welcome pack resent successfully.',
                    'sticky': True,
                    'type': 'success',
                    'next': {
                        'type': CLIENT_ACTION,
                        'tag': 'reload',
                    }
                }
            }
        except Exception as e:
            _logger.error(f"Failed to resend welcome pack for member {self.username}: {str(e)}")
            self.needs_attention = True
            self.env.cr.commit()
            raise ValidationError(_("Failed to resend welcome pack: %s") % str(e))

    def action_send_birthday_email(self):
        """Force send birthday email to the member."""
        self.ensure_one()
        if not self.is_sacco_member:
            raise ValidationError("This action is only available for SACCO members.")
        try:
            self._send_birthday_email()
            return {
                'type': CLIENT_ACTION,
                'tag': 'display_notification',
                'params': {
                    'title': 'Success',
                    'message': 'Birthday email sent successfully.',
                    'sticky': True,
                    'type': 'success',
                    'next': {
                        'type': CLIENT_ACTION,
                        'tag': 'reload',
                    }
                }
            }
        except Exception as e:
            _logger.error(f"Failed to send birthday email for member {self.username}: {str(e)}")
            self.needs_attention = True
            self.env.cr.commit()
            raise ValidationError(_("Failed to send birthday email: %s") % str(e))

    def action_view_membership_payment(self):
        """View the membership fee journal entry."""
        self.ensure_one()
        if not self.membership_fee_journal_entry_id:
            raise ValidationError("No membership fee journal entry found for this member.")
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.membership_fee_journal_entry_id.id,
            'target': 'current',
        }

    def action_print_member_receipt(self):
        self.ensure_one()
        if not self.membership_fee_journal_entry_id:
            raise ValidationError(_("No membership fee journal entry found for this member."))
        if not self.exists():
            raise ValidationError(_("The member record does not exist or has been deleted."))
        
        # Get the user who created the journal entry
        creator_user = self.membership_fee_journal_entry_id.create_uid or self.create_uid
        if creator_user:
            creator_name = creator_user.name
        else:
            creator_name = ''
        # Ensure company_id is a valid res.company record
        company_id = self.company_id or self.env.company
        if not company_id:
            raise ValidationError(_("No company assigned to the member or in the current environment."))

        data = {
            'member_id': self.member_id or '',
            'member_name': self.name or '',
            'date': (self.membership_fee_journal_entry_id.date or fields.Date.context_today(self)).strftime('%Y-%m-%d'),
            'amount_total': self.membership_fee_journal_entry_id.amount_total or 0.0,
            'currency': self.membership_fee_journal_entry_id.currency_id.symbol or company_id.currency_id.symbol,
            'payment_ref': self.membership_fee_journal_entry_id.name or '',
            'creator_name': creator_name,
            'company_address': company_id.partner_id.contact_address or '',
            'company_phone': company_id.partner_id.phone or '',
            'company_email': company_id.partner_id.email or '',
        }

        report_action = self.env.ref('member_management.action_report_member_registration_payment_receipt').report_action(self, data=data)
        _logger.info("Report action generated: %s", report_action)
        return report_action

    def action_activate_member(self):
        """Activate member and handle upload/update, called internally by onboarding."""
        if not self.member_onboarded:
            raise ValidationError("Member must be onboarded before activation.")
        
        try:
            config = get_config(self.env)
        except Exception as e:
            _logger.error(f"Failed to fetch configuration in action_activate_member: {str(e)}")
            config = {}

        username = config.get('USERNAME')
        password = config.get('PASSWORD')

        if not username or not password:
            self.write({'membership_status': 'active', 'in_sync': True})
            self.write({'activation_status': 'activated'})
            return True

        try:
            result = self.mongo_db_id and self.update_member_details() or self.upload_member_details()
            if result['params']['type'] == 'success':
                self.write({'membership_status': 'active', 'in_sync': True})
                self.write({'activation_status': 'activated'})
                return True
            else:
                self.write({'membership_status': 'active', 'in_sync': False})
                self.write({'activation_status': 'activated'})
                return False
        except Exception as e:
            _logger.error(f"Error during member upload/update: {str(e)}")
            self.write({'membership_status': 'details_processing', 'in_sync': False})
            self.write({'activation_status': 'deactivated'})
            return False

    def action_deactivate_member(self):
        self.activation_status = 'deactivated'
        self.membership_status = 'inactive'
        self._sync_mailing_list_subscription()
        self._sync_birthday_mailing_list_subscription()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'current',
        }

    def _get_auth_token(self):
        login_url = f"{BASE_URL}/{LOGIN_ENDPOINT}"
        login_data = {"username": USERNAME, "password": PASSWORD}
        try:
            response = requests.post(login_url, json=login_data)
            response.raise_for_status()
            return response.json().get('access_token')
        except requests.RequestException as e:
            _logger.error(f"Failed to obtain auth token: {str(e)}")
            return None

    def _prepare_member_data(self):
        """Prepare common member data for upload/update."""
        return {
            'username': (self.username or "").lower(), # send username as lowercase letters
            'firstName': self.first_name,
            'middleName': self.middle_name or '',
            'lastName': self.last_name,
            'gender': self.gender,
            'memberType': self.member_type,
            'email': self.email or '',
            'role': 'Sacco Member',
            'memberDateOfBirth': self.date_of_birth.isoformat() if self.date_of_birth else None,
            'memberPhoneNumber': self.mobile or self.phone or '',
            'employmentStatus': self.employment_status,
            'maritalStatus': self.marital_status,
            'memberIdentificationDocument': self.id_type,
            'memberIdNumber': self.id_number,
            'activationStatus': self.activation_status,
            'joiningDate': self.joining_date.isoformat() if self.joining_date else None,
            'membershipStatus': self.membership_status,
            'exitDate': self.exit_date.isoformat() if self.exit_date else None,
            'branchCode': self.branch_code or '',
            'memberId': self.member_id or '',
        }

    def upload_member_details(self):
        """Delegate to MemberSync for uploading member details."""
        sync = self.env['member.sync'].create({})
        return sync.upload_member(self)

    def update_member_details(self):
        """Delegate to MemberSync for updating member details."""
        sync = self.env['member.sync'].create({})
        return sync.update_member(self)

    def action_mass_upload_members(self):
        """Delegate mass upload to MemberSync."""
        sync = self.env['member.sync'].create({})
        return sync.mass_upload_members(self)

    def action_mass_update_members(self):
        """Delegate mass update to MemberSync."""
        sync = self.env['member.sync'].create({})
        return sync.mass_update_members(self)

    def action_mass_send_birthday_emails(self):
        """Send birthday emails to selected SACCO members with birthdays in the current month."""
        if not all(partner.is_sacco_member for partner in self):
            return self._show_notification(
                'Error',
                'This action is only available for SACCO members.',
                'error'
            )

        current_month = fields.Date.today().month
        failed_members = []
        for partner in self:
            if partner.date_of_birth and partner.date_of_birth.month == current_month:
                try:
                    partner._send_birthday_email()
                except Exception as e:
                    failed_members.append(partner.username or partner.name)
                    partner.needs_attention = True
                    self.env.cr.commit()

        if failed_members:
            return self._show_notification(
                'Warning',
                f"Failed to send birthday emails to: {', '.join(failed_members)}",
                'warning'
            )
        return self._show_notification(
            'Success',
            'Birthday emails sent successfully.',
            'success'
        )

    def _show_notification(self, title, message, type='info', reload=False):
        _logger.info(f"Showing notification - Title: {title}, Message: {message}, Type: {type}, Reload: {reload}")
        result = {
            'type': CLIENT_ACTION,
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'sticky': True,
                'type': type,
            }
        }
        
        if reload:
            result['params']['next'] = {
                'type': CLIENT_ACTION,
                'tag': 'reload',
            }
        
        return result

    def _send_welcome_pack(self):
        """Send the welcome pack email with attachments using the configured template."""
        _logger.info(f"Starting _send_welcome_pack for member {self.username} (Partner ID: {self.id})")
        config = self.env['sacco.membership.config'].search([], limit=1)
        if not config:
            _logger.error(f"No SACCO membership configuration found for member {self.username}.")
            self.needs_attention = True
            self.env.cr.commit()
            return
        if not config.welcome_pack_template_id:
            _logger.error(f"No welcome pack template configured for member {self.username}.")
            raise ValidationError(_("No welcome pack email template selected. Please select a template in the SACCO Membership Configuration under Members > Configuration."))

        template = config.welcome_pack_template_id
        if not template:
            _logger.error(f"No welcome pack template configured for member {self.username}.")
            self.needs_attention = True
            self.env.cr.commit()
            return

        if not self.email:
            _logger.warning(f"No email address found for member {self.username}.")
            self.needs_attention = True
            self.env.cr.commit()
            return

        # Check SMTP configuration
        smtp_server = self.env['ir.mail_server'].search([], limit=1)
        if not smtp_server:
            _logger.error(f"No SMTP server configured for member {self.username}.")
            self.needs_attention = True
            self.env.cr.commit()
            raise ValidationError(_("No SMTP server configured. Please configure an outgoing mail server in Settings > General Settings > Outgoing Email Servers."))

        try:
            # Ensure company_id is set, fallback to env.company
            if not self.company_id:
                self.write({'company_id': self.env.company.id})
                _logger.info(f"Set company_id to {self.env.company.id} for member {self.username} (Partner ID: {self.id})")

            # Prepare email values with attachments
            email_values = {
                'email_to': self.email,
                'attachment_ids': [(4, att.id) for att in config.welcome_pack_attachments] if config.welcome_pack_attachments else [],
            }
            _logger.info(f"Email values prepared for member {self.username}: {email_values}")

            # Determine which body to use based on the toggle
            if config.use_default_template or not config.welcome_pack_body.strip():
                _logger.info(f"Using default template body for member {self.username}.")
                email_values.update(template._generate_template([self.id], ['body_html'])[self.id])
            else:
                _logger.info(f"Using custom welcome pack body for member {self.username}. Partner ID: {self.id}, Company ID: {self.company_id.id}, Company Name: {self.company_id.name}, Company Email: {self.company_id.email}")
                try:
                    rendered_body = self.env['mail.render.mixin']._render_template(
                        template_src=config.welcome_pack_body,
                        model='res.partner',
                        res_ids=[self.id],
                        engine='qweb',
                        options={'post_process': True}
                    )[self.id]
                    email_values['body_html'] = rendered_body
                    _logger.info(f"Custom body rendered successfully for member {self.username}: {rendered_body[:200]}...")
                except Exception as e:
                    _logger.error(f"Failed to render custom welcome pack body for member {self.username}: {str(e)}")
                    self.needs_attention = True
                    self.env.cr.commit()
                    return

            # Send the email and capture the mail message ID
            _logger.info(f"Attempting to send email for member {self.username} using template {template.id}")
            mail_id = template.with_context(lang=self.lang or 'en_US').send_mail(
                self.id,
                force_send=True,
                email_values=email_values,
            )
            _logger.info(f"Email queued successfully for member {self.username}, mail message ID: {mail_id}")

            # Verify the email is in the mail queue
            mail_message = self.env['mail.message'].browse(mail_id)
            if not mail_message:
                _logger.error(f"No mail message found for ID {mail_id} for member {self.username}.")
                self.needs_attention = True
                self.env.cr.commit()
                return

            # Check if the email was actually sent
            mail_mail = self.env['mail.mail'].search([('mail_message_id', '=', mail_id)], limit=1)
            if not mail_mail:
                _logger.error(f"No mail.mail record found for message ID {mail_id} for member {self.username}.")
                self.needs_attention = True
                self.env.cr.commit()
                return

            _logger.info(f"Mail record created for member {self.username}: State={mail_mail.state}, Recipient={mail_mail.recipient_ids.mapped('email')}")
            if mail_mail.state == 'exception':
                _logger.error(f"Email sending failed for member {self.username}: {mail_mail.failure_reason}")
                self.needs_attention = True
                self.env.cr.commit()
                return

            _logger.info(f"Welcome pack sent successfully to member {self.username} at {self.email}.")
            self.needs_attention = False
            self.env.cr.commit()

        except Exception as e:
            _logger.error(f"Failed to send welcome pack to member {self.username}: {str(e)}")
            self.needs_attention = True
            self.env.cr.commit()
            raise ValidationError(_("Failed to send welcome pack: %s") % str(e))

    def _send_birthday_email(self):
        """Send the birthday email with attachments using the configured template."""
        _logger.info(f"Starting _send_birthday_email for member {self.username} (Partner ID: {self.id})")
        config = self.env['sacco.membership.config'].search([], limit=1)
        if not config:
            _logger.error(f"No SACCO membership configuration for member {self.username}.")
            self.needs_attention = True
            self.env.cr.commit()
            return

        _logger.info(f"Birthday Packs {config.send_birthday_packs})")
        if not config.send_birthday_packs:
            _logger.error(f"Birthday email sending is disabled for member {self.username}.")
            raise ValidationError(_("Birthday email sending is disabled. Please enable 'Send Birthday Packs' in the SACCO Membership Configuration under Members > Configuration."))

        if not config.birthday_template_id:
            _logger.error(f"No birthday template configured for member {self.username}.")
            raise ValidationError(_("No birthday email template selected. Please select a template in the SACCO Membership Configuration under Members > Configuration."))

        template = config.birthday_template_id
        if not template:
            _logger.error(f"No birthday template configured for member {self.username}.")
            self.needs_attention = True
            self.env.cr.commit()
            return

        if not self.email:
            _logger.warning(f"No email address found for member {self.username}.")
            self.needs_attention = True
            self.env.cr.commit()
            return

        # Check SMTP configuration
        smtp_server = self.env['ir.mail_server'].search([], limit=1)
        if not smtp_server:
            _logger.error(f"No SMTP server configured for member {self.username}.")
            self.needs_attention = True
            self.env.cr.commit()
            raise ValidationError(_("No SMTP server configured. Please configure an outgoing mail server in Settings > General Settings > Outgoing Email Servers."))

        try:
            # Ensure company_id is set, fallback to env.company
            if not self.company_id:
                self.write({'company_id': self.env.company.id})
                _logger.info(f"Set company_id to {self.env.company.id} for member {self.username} (Partner ID: {self.id})")

            # Prepare email values with attachments
            email_values = {
                'email_to': self.email,
                'attachment_ids': [(4, att.id) for att in config.birthday_attachments] if config.birthday_attachments else [],
            }
            _logger.info(f"Email values prepared for birthday email for member {self.username}: {email_values}")

            # Determine which body to use based on the toggle
            if config.use_default_birthday_template or not config.birthday_body.strip():
                _logger.info(f"Using default birthday template body for member {self.username}.")
                email_values.update(template._generate_template([self.id], ['body_html'])[self.id])
            else:
                _logger.info(f"Using custom birthday body for member {self.username}. Partner ID: {self.id}, Company ID: {self.company_id.id}, Company Name: {self.company_id.name}, Company Email: {self.company_id.email}")
                try:
                    rendered_body = self.env['mail.render.mixin']._render_template(
                        template_src=config.birthday_body,
                        model='res.partner',
                        res_ids=[self.id],
                        engine='qweb',
                        options={'post_process': True}
                    )[self.id]
                    email_values['body_html'] = rendered_body
                    _logger.info(f"Custom birthday body rendered successfully for member {self.username}: {rendered_body[:200]}...")
                except Exception as e:
                    _logger.error(f"Failed to render custom birthday body for member {self.username}: {str(e)}")
                    self.needs_attention = True
                    self.env.cr.commit()
                    return

            # Send the email and capture the mail message ID
            _logger.info(f"Attempting to send birthday email for member {self.username} using template {template.id}")
            mail_id = template.with_context(lang=self.lang or 'en_US').send_mail(
                self.id,
                force_send=True,
                email_values=email_values,
            )
            _logger.info(f"Birthday email queued successfully for member {self.username}, mail message ID: {mail_id}")

            # Verify the email is in the mail queue
            mail_message = self.env['mail.message'].browse(mail_id)
            if not mail_message:
                _logger.error(f"No mail message found for ID {mail_id} for member {self.username}.")
                self.needs_attention = True
                self.env.cr.commit()
                return

            # Check if the email was actually sent
            mail_mail = self.env['mail.mail'].search([('mail_message_id', '=', mail_id)], limit=1)
            if not mail_mail:
                _logger.error(f"No mail.mail record found for message ID {mail_id} for member {self.username}.")
                self.needs_attention = True
                self.env.cr.commit()
                return

            _logger.info(f"Birthday mail record created for member {self.username}: State={mail_mail.state}, Recipient={mail_mail.recipient_ids.mapped('email')}")
            if mail_mail.state == 'exception':
                _logger.error(f"Birthday email sending failed for member {self.username}: {mail_mail.failure_reason}")
                self.needs_attention = True
                self.env.cr.commit()
                return

            _logger.info(f"Birthday email sent successfully to member {self.username} at {self.email}.")
            self.needs_attention = False
            self.env.cr.commit()

        except Exception as e:
            _logger.error(f"Failed to send birthday email to member {self.username}: {str(e)}")
            self.needs_attention = True
            self.env.cr.commit()
            raise ValidationError(_("Failed to send birthday email: %s") % str(e))

    def action_mass_send_welcome_pack(self):
        """Send welcome packs to selected SACCO members."""
        if not all(partner.is_sacco_member for partner in self):
            return self._show_notification(
                'Error',
                'This action is only available for SACCO members.',
                'error'
            )

        failed_members = []
        for partner in self:
            try:
                partner._send_welcome_pack()
            except Exception as e:
                failed_members.append(partner.username or partner.name)
                partner.needs_attention = True
                self.env.cr.commit()

        if failed_members:
            return self._show_notification(
                'Warning',
                f"Failed to send welcome pack to: {', '.join(failed_members)}",
                'warning'
            )
        return self._show_notification(
            'Success',
            'Welcome packs sent successfully.',
            'success'
        )
            
    def _sync_mailing_list_subscription(self):
        """Sync mailing list subscription based on membership and activation status."""
        mailing_list = self.env['mailing.list'].search([('name', '=', 'SACCO Members')], limit=1)
        if not mailing_list:
            _logger.warning(f"No SACCO Members mailing list found for member {self.username}.")
            self.needs_attention = True
            return

        for partner in self:
            if partner.is_sacco_member and partner.membership_status == 'active' and partner.activation_status == 'activated':
                # Check if already subscribed
                subscription = self.env['mailing.contact'].search([
                    ('email_normalized', '=', partner.email_normalized),
                    ('list_ids', 'in', mailing_list.id),
                ], limit=1)
                if not subscription:
                    # Create a new subscription
                    contact_vals = {
                        'name': partner.name,
                        'email': partner.email,
                        'list_ids': [(4, mailing_list.id)],
                    }
                    self.env['mailing.contact'].create(contact_vals)
                    _logger.info(f"Member {partner.username} subscribed to SACCO Members mailing list.")
            else:
                # Unsubscribe if conditions are not met
                subscription = self.env['mailing.contact'].search([
                    ('email_normalized', '=', partner.email_normalized),
                    ('list_ids', 'in', mailing_list.id),
                ])
                if subscription:
                    subscription.write({'list_ids': [(3, mailing_list.id)]})
                    _logger.info(f"Member {partner.username} unsubscribed from SACCO Members mailing list.")

    def _sync_birthday_mailing_list_subscription(self):
        """Sync birthday mailing list subscription based on membership status and date of birth."""
        mailing_list = self.env['mailing.list'].search([('name', '=', 'SACCO Birthday List')], limit=1)
        if not mailing_list:
            _logger.warning(f"No SACCO Birthday List mailing list found for member {self.username}.")
            self.needs_attention = True
            return

        for partner in self:
            if (partner.is_sacco_member and 
                partner.membership_status == 'active' and 
                partner.activation_status == 'activated' and 
                partner.date_of_birth):
                # Check if already subscribed
                subscription = self.env['mailing.contact'].search([
                    ('email_normalized', '=', partner.email_normalized),
                    ('list_ids', 'in', mailing_list.id),
                ], limit=1)
                if not subscription:
                    # Create a new subscription
                    contact_vals = {
                        'name': partner.name,
                        'email': partner.email,
                        'list_ids': [(4, mailing_list.id)],
                    }
                    self.env['mailing.contact'].create(contact_vals)
                    _logger.info(f"Member {partner.username} subscribed to SACCO Birthday List.")
            else:
                # Unsubscribe if conditions are not met
                subscription = self.env['mailing.contact'].search([
                    ('email_normalized', '=', partner.email_normalized),
                    ('list_ids', 'in', mailing_list.id),
                ])
                if subscription:
                    subscription.write({'list_ids': [(3, mailing_list.id)]})
                    _logger.info(f"Member {partner.username} unsubscribed from SACCO Birthday List.")

    @api.model
    def _cron_send_birthday_emails(self):
        """Cron job to send birthday emails to members whose birthday is today."""
        config = self.env['sacco.membership.config'].search([], limit=1)
        if not config or not config.send_birthday_packs:
            _logger.info("Birthday email sending is disabled in configuration.")
            return

        today = fields.Date.today()
        members = self.search([
            ('is_sacco_member', '=', True),
            ('membership_status', '=', 'active'),
            ('activation_status', '=', 'activated'),
            ('date_of_birth', '!=', False),
            ('date_of_birth', 'like', f'%-{today.month:02d}-{today.day:02d}')
        ])

        failed_members = []
        for member in members:
            try:
                member._send_birthday_email()
            except Exception as e:
                failed_members.append(member.username or member.name)
                member.needs_attention = True
                self.env.cr.commit()

        if failed_members:
            _logger.warning(f"Failed to send birthday emails to: {', '.join(failed_members)}")

    def action_view_birthday_members(self):
        current_month = datetime.now().strftime('%m')
        domain = [
            ('is_sacco_member', '=', True),
            ('date_of_birth', '!=', False),
            ('date_of_birth', 'like', f'%-{current_month}-%')
        ]
        return {
            'name': 'Members with Birthdays This Month',
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'views': [
                (self.env.ref('member_management.view_partner_birthday_tree').id, 'tree'),
                (self.env.ref('member_management.view_res_partner_is_sacco_member_form').id, 'form'),
            ],
            'domain': domain,
            'context': {'search_default_is_sacco_member': 1},
            'help': """
                <p class="oe_view_nocontent_create">
                    No members with birthdays this month found.
                </p>
            """
        }