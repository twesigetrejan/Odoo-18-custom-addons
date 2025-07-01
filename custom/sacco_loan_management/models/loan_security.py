from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime, date

class SaccoLoanSecurity(models.Model):
    _name = "sacco.loan.security"
    _description = "SACCO Loan Security"
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='Security ID',
        default=lambda self: self.env['ir.sequence'].next_by_code('sacco.loan.security'),
        readonly=True,
        required=True,
        copy=False,
        help="A unique code for each security (e.g., SEC/2025/00001)"
    )
    loan_id = fields.Many2one('sacco.loan.loan', string='Loan', required=True, ondelete='cascade')
    security_type = fields.Selection(
        [('vehicle', 'Vehicle'), ('land', 'Land'), ('other', 'Other')],
        string='Security Type',
        required=True,
        help="Type of asset securing the loan (e.g., Vehicle)"
    )
    description = fields.Char(
        string='Description',
        required=True,
        help="Details about the security (e.g., Toyota Premio, Reg UBB 123A, 2015)"
    )
    owner_name = fields.Char(
        string='Owner Name',
        required=True,
        help="Name of the person or entity owning the security (e.g., John Doe)"
    )
    ownership_proof_ref = fields.Many2many(
        'ir.attachment',
        string='Ownership Proof',
        help="Reference to proof of ownership (e.g., logbook scan or title deed attachment)"
    )
    registered_asset_no = fields.Char(
        string='Registered Asset No',
        required=True,
        help="Unique asset registration number (e.g., KCA 456)"
    )
    location = fields.Char(
        string='Location',
        required=True,
        help="Where the asset is located (e.g., Nairobi, Kenya)"
    )
    market_value = fields.Float(
        string='Market Value',
        required=True,
        help="Current market worth of the asset (e.g., 5000)"
    )
    valuation_date = fields.Date(
        string='Valuation Date',
        required=True,
        help="Date of the last valuation (e.g., 2025-06-01)"
    )
    forced_sale_value = fields.Float(
        string='Forced Sale Value',
        help="Value if sold quickly (e.g., 4000)"
    )
    encumbrance_flag = fields.Boolean(
        string='Encumbrance Flag',
        default=False,
        help="Indicates if the asset is pledged elsewhere (e.g., TRUE)"
    )
    encumbrance_details = fields.Char(
        string='Encumbrance Details',
        help="Info on any existing pledge (e.g., ABC Bank / CRB123)"
    )
    security_status = fields.Selection(
        [('pending_verification', 'Pending Verification'), ('verified', 'Verified'), ('released', 'Released')],
        string='Security Status',
        default='pending_verification',
        help="Current state of the security (e.g., Verified)"
    )
    release_date = fields.Date(
        string='Release Date',
        help="Date the security is released (e.g., 2025-06-10)"
    )

    @api.depends('loan_document_ids')
    def _compute_attachment_number(self):
        for security in self:
            security.attachment_number = self.env['ir.attachment'].search_count([
                ('res_model', '=', 'sacco.loan.security'),
                ('res_id', '=', security.id)
            ])

    loan_document_ids = fields.One2many('ir.attachment', 'res_id', string='Attachments', domain=[('res_model', '=', 'sacco.loan.security')])
    attachment_number = fields.Integer(compute='_compute_attachment_number', string='Number of Attachments')
    notes = fields.Text(string='Notes')

    @api.constrains('registered_asset_no')
    def _check_encumbrance(self):
        """Check for encumbrance by verifying registered_asset_no across active securities."""
        for record in self:
            if record.registered_asset_no:
                existing_securities = self.env['sacco.loan.security'].search([
                    ('registered_asset_no', '=', record.registered_asset_no),
                    ('id', '!=', record.id),
                    '|',
                    ('security_status', '!=', 'released'),
                    ('release_date', '>', fields.Date.today())
                ])
                if existing_securities:
                    record.encumbrance_flag = True
                    record.encumbrance_details = f"Already pledged in {', '.join(str(s.loan_id.name) for s in existing_securities)}"
                    raise ValidationError(
                        _("The asset with registration number %s is already pledged to another loan application.") %
                        record.registered_asset_no
                    )

    @api.constrains('security_status', 'release_date')
    def _check_status_and_release(self):
        """Ensure release_date is set when status is 'released'."""
        for record in self:
            if record.security_status == 'released' and not record.release_date:
                record.release_date = fields.Date.today()
            elif record.security_status != 'released' and record.release_date:
                record.release_date = False

    @api.constrains('registered_asset_no')
    def _check_unique_asset_no(self):
        """Prevent duplicate active securities for the same asset."""
        for record in self:
            if record.registered_asset_no and record.security_status != 'released':
                duplicates = self.env['sacco.loan.security'].search([
                    ('registered_asset_no', '=', record.registered_asset_no),
                    ('security_status', '!=', 'released'),
                    ('id', '!=', record.id),
                    '|',
                    ('release_date', '=', False),
                    ('release_date', '>', fields.Date.today()),
                ])
                if duplicates:
                    raise ValidationError(
                        _("Asset %s is already pledged for loan(s): %s") % (
                            record.registered_asset_no,
                            ', '.join(dup.loan_id.name for dup in duplicates)
                        )
                    )

    def action_verify(self):
        """Move security to 'verified' status."""
        self.ensure_one()
        if self.security_status == 'pending_verification':
            self.security_status = 'verified'
        else:
            raise ValidationError(_("Only pending securities can be verified."))

    def action_release(self):
        """Move security to 'released' status and set release_date."""
        self.ensure_one()
        if self.security_status != 'released':
            self.security_status = 'released'
            self.release_date = fields.Date.today()

    def action_get_attachment_view(self):
        self.ensure_one()
        res = self.env['ir.actions.act_window']._for_xml_id('base.action_attachment')
        res['domain'] = [('res_model', '=', 'sacco.loan.security'), ('res_id', 'in', self.ids)]
        res['context'] = {'default_res_model': 'sacco.loan.security', 'default_res_id': self.id}
        return res