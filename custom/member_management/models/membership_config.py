from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)

class SaccoMembershipConfig(models.Model):
    _name = 'sacco.membership.config'
    _description = 'SACCO Membership Configuration'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Name', default='Membership Configuration', readonly=True)
    membership_fee = fields.Float(string='Membership Fee Amount', required=True, default=0.0, tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
        default=lambda self: self.env.company.currency_id, tracking=True)
    membership_fee_account_id = fields.Many2one('account.account', string='Membership Fee Account',
        domain="[('account_type', '=like', 'asset_cash%')]",
        required=True, tracking=True,
        help="Account to credit the membership fee payments.")
    membership_fee_journal_id = fields.Many2one('account.journal', string='Membership Fee Journal',
        default=lambda self: self.env['sacco.helper'].get_member_journal_id(),
        required=True, tracking=True,
        help="Journal to use for membership fee transactions.")

    # Welcome Pack Configuration
    use_default_template = fields.Boolean(string='Use Default Template', default=True,
        help="Toggle to use the default template or customize your own.")
    welcome_pack_template_id = fields.Many2one(
        'mail.template', string='Welcome Pack Email Template',
        domain="[('model', '=', 'res.partner')]",
        help="Email template used for sending the welcome pack to new members.",
        default=lambda self: self.env['ir.model.data']._xmlid_to_res_id('member_management.mail_template_welcome_pack')
    )
    welcome_pack_attachments = fields.Many2many(
        'ir.attachment',
        relation='sacco_membership_welcome_attach_rel',  # Unique relation table name
        column1='config_id',  # Column for sacco.membership.config
        column2='attachment_id',  # Column for ir.attachment
        string='Welcome Pack Attachments',
        help="Attachments to include in the welcome pack email (e.g., PDF documents)."
    )
    welcome_pack_body = fields.Html(
        string='Welcome Pack Email Body',
        render_engine='qweb',
        render_options={'post_process': True},
        prefetch=True,
        translate=True,
        sanitize=False,
        help="Custom body for the welcome pack email. Use <t t-out='object.field'/> for dynamic content. If empty or using default template, the default template body will be used.",
        default=lambda self: self._get_default_welcome_pack_body()
    )

    # Birthday Pack Configuration
    send_birthday_packs = fields.Boolean(
        string='Send Birthday Packs',
        default=False,
        help="Enable or disable automatic sending of birthday emails via cron job."
    )
    use_default_birthday_template = fields.Boolean(
        string='Use Default Birthday Template',
        default=True,
        help="Toggle to use the default birthday template or customize your own."
    )
    birthday_template_id = fields.Many2one(
        'mail.template',
        string='Birthday Email Template',
        domain="[('model', '=', 'res.partner')]",
        help="Email template used for sending birthday greetings to members.",
        default=lambda self: self.env['ir.model.data']._xmlid_to_res_id('member_management.mail_template_birthday')
    )
    birthday_attachments = fields.Many2many(
        'ir.attachment',
        relation='sacco_membership_birthday_attach_rel',  # Unique relation table name
        column1='config_id',  # Column for sacco.membership.config
        column2='attachment_id',  # Column for ir.attachment
        string='Birthday Attachments',
        help="Attachments to include in the birthday email (e.g., PDF documents)."
    )
    birthday_body = fields.Html(
        string='Birthday Email Body',
        render_engine='qweb',
        render_options={'post_process': True},
        prefetch=True,
        translate=True,
        sanitize=False,
        help="Custom body for the birthday email. Use <t t-out='object.field'/> for dynamic content.",
        default=lambda self: self._get_default_birthday_body()
    )

    @api.model
    def _get_default_welcome_pack_body(self):
        """Set the default welcome pack email body with QWeb placeholders and fallback values for preview."""
        return """
<table border="0" cellpadding="0" cellspacing="0" style="padding-top: 16px; background-color: #FFFFFF; font-family: Verdana, Arial, sans-serif; color: #454748; width: 100%; border-collapse: separate;">
    <tr>
        <td align="center">
            <table border="0" cellpadding="0" cellspacing="0" width="590" style="padding: 16px; background-color: #FFFFFF; color: #454748; border-collapse: separate;">
                <tbody>
                    <!-- HEADER -->
                    <tr>
                        <td align="center" style="min-width: 590px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="590" style="min-width: 590px; background-color: white; padding: 0px 8px; border-collapse: separate;">
                                <tr>
                                    <td valign="middle">
                                        <span style="font-size: 10px;">Welcome to <t t-out="(object.company_id.name if object.company_id else env.company.name) or 'Your SACCO'">Your SACCO</t></span><br/>
                                        <span style="font-size: 20px; font-weight: bold;">
                                            <t t-out="object.name or ''">Mark Smith</t>
                                        </span>
                                    </td>
                                    <t t-if="not (object.company_id.uses_default_logo if object.company_id else env.company.uses_default_logo)">
                                        <td valign="middle" align="right">
                                            <img t-attf-src="/logo.png?company={{ (object.company_id.id if object.company_id else env.company.id) }}" style="padding: 0px; margin: 0px; height: auto; width: 80px;" t-att-alt="(object.company_id.name if object.company_id else env.company.name) or 'Your SACCO'"/>
                                        </td>
                                    </t>
                                </tr>
                                <tr>
                                    <td colspan="2" style="text-align: center;">
                                        <hr style="background-color: #ccc; border: none; height: 1px; margin: 16px 0;"/>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <!-- CONTENT -->
                    <tr>
                        <td align="center" style="min-width: 590px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="590" style="min-width: 590px; background-color: white; padding: 0px 8px; border-collapse: separate;">
                                <tr>
                                    <td valign="top" style="font-size: 13px;">
                                        <div>
                                            <h2 style="color: #333;">Welcome, <t t-out="object.name or ''">Mark Smith</t>!</h2>
                                            <p>We are delighted to welcome you as a new member of <t t-out="(object.company_id.name if object.company_id else env.company.name) or 'Your SACCO'">Your SACCO</t> SACCO.</p>
                                            <p>Your Username is: <strong><t t-out="object.username or ''">MEM000033</t></strong></p>
                                            <p>Please find your welcome pack attached to this email. It contains all the information you need to get started.</p>
                                            <p>If you have any questions, feel free to reach out to us at <t t-out="(object.company_id.email if object.company_id else env.company.email) or 'support@yoursacco.com'">support@yoursacco.com</t>.</p>
                                            <p>Best regards,<br/>The <t t-out="(object.company_id.name if object.company_id else env.company.name) or 'Your SACCO'">Your SACCO</t> SACCO Team</p>
                                        </div>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="text-align: center;">
                                        <hr style="background-color: #ccc; border: none; height: 1px; margin: 16px 0;"/>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <!-- FOOTER -->
                    <tr>
                        <td align="center" style="min-width: 590px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="590" style="min-width: 590px; background-color: white; font-size: 11px; padding: 0px 8px; border-collapse: separate;">
                                <tr>
                                    <td valign="middle" align="left">
                                        <t t-out="(object.company_id.name if object.company_id else env.company.name) or 'Your SACCO'">Your SACCO</t>
                                    </td>
                                </tr>
                                <tr>
                                    <td valign="middle" align="left" style="opacity: 0.7;">
                                        <t t-out="(object.company_id.phone if object.company_id else env.company.phone) or ''">+1 650-123-4567</t>
                                        <t t-if="(object.company_id.email if object.company_id else env.company.email)">
                                            | <a t-att-href="'mailto:%s' % (object.company_id.email if object.company_id else env.company.email)" style="text-decoration: none; color: #454748;" t-out="(object.company_id.email if object.company_id else env.company.email) or 'support@yoursacco.com'">support@yoursacco.com</a>
                                        </t>
                                        <t t-if="(object.company_id.website if object.company_id else env.company.website)">
                                            | <a t-att-href="'%s' % (object.company_id.website if object.company_id else env.company.website)" style="text-decoration: none; color: #454748;" t-out="(object.company_id.website if object.company_id else env.company.website) or ''">http://www.yoursacco.com</a>
                                        </t>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <!-- POWERED BY -->
                    <tr>
                        <td align="center" style="min-width: 590px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="590" style="min-width: 590px; background-color: #F1F1F1; color: #454748; padding: 8px; border-collapse: separate;">
                                <tr>
                                    <td style="text-align: center; font-size: 13px;">
                                        Powered by <a target="_blank" href="https://www.odoo.com?utm_source=db&utm_medium=auth" style="color: #875A7B;">Odoo</a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </tbody>
            </table>
        </td>
    </tr>
</table>
        """

    @api.model
    def _get_default_birthday_body(self):
        """Set the default birthday email body with QWeb placeholders."""
        return """
<table border="0" cellpadding="0" cellspacing="0" style="padding-top: 16px; background-color: #FFFFFF; font-family: Verdana, Arial, sans-serif; color: #454748; width: 100%; border-collapse: separate;">
    <tr>
        <td align="center">
            <table border="0" cellpadding="0" cellspacing="0" width="590" style="padding: 16px; background-color: #FFFFFF; color: #454748; border-collapse: separate;">
                <tbody>
                    <!-- HEADER -->
                    <tr>
                        <td align="center" style="min-width: 590px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="590" style="min-width: 590px; background-color: white; padding: 0px 8px; border-collapse: separate;">
                                <tr>
                                    <td valign="middle">
                                        <span style="font-size: 10px;">Happy Birthday from <t t-out="(object.company_id.name if object.company_id else env.company.name) or 'Your SACCO'">Your SACCO</t></span><br/>
                                        <span style="font-size: 20px; font-weight: bold;">
                                            <t t-out="object.name or ''">Mark Smith</t>
                                        </span>
                                    </td>
                                    <t t-if="not (object.company_id.uses_default_logo if object.company_id else env.company.uses_default_logo)">
                                        <td valign="middle" align="right">
                                            <img t-attf-src="/logo.png?company={{ (object.company_id.id if object.company_id else env.company.id) }}" style="padding: 0px; margin: 0px; height: auto; width: 80px;" t-att-alt="(object.company_id.name if object.company_id else env.company.name) or 'Your SACCO'"/>
                                        </td>
                                    </t>
                                </tr>
                                <tr>
                                    <td colspan="2" style="text-align: center;">
                                        <hr style="background-color: #ccc; border: none; height: 1px; margin: 16px 0;"/>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <!-- CONTENT -->
                    <tr>
                        <td align="center" style="min-width: 590px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="590" style="min-width: 590px; background-color: white; padding: 0px 8px; border-collapse: separate;">
                                <tr>
                                    <td valign="top" style="font-size: 13px;">
                                        <div>
                                            <h2 style="color: #333;">Happy Birthday, <t t-out="object.name or ''">Mark Smith</t>!</h2>
                                            <p>We at <t t-out="(object.company_id.name if object.company_id else env.company.name) or 'Your SACCO'">Your SACCO</t> wish you a fantastic birthday filled with joy and celebration!</p>
                                            <div class="text-center">
                                                <img src="/member_management/static/src/img/happy_birthday.gif" class="img" style="width: 23%;"/>
                                            </div>
                                            <p>Thank you for being a valued member of our SACCO community. We hope this year brings you prosperity and happiness.</p>
                                            <p>Best wishes,<br/>The <t t-out="(object.company_id.name if object.company_id else env.company.name) or 'Your SACCO'">Your SACCO</t> SACCO Team</p>
                                        </div>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="text-align: center;">
                                        <hr style="background-color: #ccc; border: none; height: 1px; margin: 16px 0;"/>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <!-- FOOTER -->
                    <tr>
                        <td align="center" style="min-width: 590px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="590" style="min-width: 590px; background-color: white; font-size: 11px; padding: 0px 8px; border-collapse: separate;">
                                <tr>
                                    <td valign="middle" align="left">
                                        <t t-out="(object.company_id.name if object.company_id else env.company.name) or 'Your SACCO'">Your SACCO</t>
                                    </td>
                                </tr>
                                <tr>
                                    <td valign="middle" align="left" style="opacity: 0.7;">
                                        <t t-out="(object.company_id.phone if object.company_id else env.company.phone) or ''">+1 650-123-4567</t>
                                        <t t-if="(object.company_id.email if object.company_id else env.company.email)">
                                            | <a t-att-href="'mailto:%s' % (object.company_id.email if object.company_id else env.company.email)" style="text-decoration: none; color: #454748;" t-out="(object.company_id.email if object.company_id else env.company.email) or 'support@yoursacco.com'">support@yoursacco.com</a>
                                        </t>
                                        <t t-if="(object.company_id.website if object.company_id else env.company.website)">
                                            | <a t-att-href="'%s' % (object.company_id.website if object.company_id else env.company.website)" style="text-decoration: none; color: #454748;" t-out="(object.company_id.website if object.company_id else env.company.website) or ''">http://www.yoursacco.com</a>
                                        </t>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                    <!-- POWERED BY -->
                    <tr>
                        <td align="center" style="min-width: 590px;">
                            <table border="0" cellpadding="0" cellspacing="0" width="590" style="min-width: 590px; background-color: #F1F1F1; color: #454748; padding: 8px; border-collapse: separate;">
                                <tr>
                                    <td style="text-align: center; font-size: 13px;">
                                        Powered by <a target="_blank" href="https://www.odoo.com?utm_source=db&utm_medium=auth" style="color: #875A7B;">Odoo</a>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>
                </tbody>
            </table>
        </td>
    </tr>
</table>
        """

    @api.model
    def create(self, vals):
        # Ensure only one configuration record exists
        if self.search_count([]) > 0:
            raise ValidationError(_("Only one SACCO Membership Configuration record is allowed."))
        if not vals.get('name'):
            vals['name'] = 'SACCO Membership Configuration'
        return super(SaccoMembershipConfig, self).create(vals)

    def write(self, vals):
        # Prevent changing the name
        if 'name' in vals and vals['name'] != 'SACCO Membership Configuration':
            raise ValidationError(_("The name of the SACCO Membership Configuration cannot be changed."))
        return super(SaccoMembershipConfig, self).write(vals)

    def action_reset_custom_template(self):
        """Reset the custom template body to the default format."""
        default_body = self._get_default_welcome_pack_body()
        for record in self:
            record.welcome_pack_body = default_body
        return True

    def action_reset_birthday_template(self):
        """Reset the custom birthday template body to the default format."""
        default_body = self._get_default_birthday_body()
        for record in self:
            record.birthday_body = default_body
        return True