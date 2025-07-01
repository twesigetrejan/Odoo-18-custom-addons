{
    'name': "Member Management",
    'summary': """
        Comprehensive SACCO Member Management Module for Odoo
    """,
    'description': """
        The Member Management module provides a robust solution for managing SACCO (Savings and Credit Cooperative) members within Odoo.
        Key features include:
        - Member registration and profile management with detailed personal and contact information.
        - Next of Kin tracking.
        - Membership status tracking (e.g., active, inactive, pending, deceased) with activation workflows.
        - Integration with external systems for member data synchronization.
        - Customizable views for member details, including balances and membership history.
        - Security groups and access controls for different user roles within the SACCO.
        - Automated cron jobs for periodic data synchronization with external systems.
        - Support for mass upload and update operations for efficient member data management.
        - SACCO accronym configuration and automated username generation.
        - Welcome pack delivery via email with PDF attachment upon member activation.
        - Automatic subscription to SACCO mailing list after activation.
        - Configurable welcome pack email template and attachments via UI.
    """,
    'author': "Omni Software Ltd",
    'website': "https://www.omni.co.ug",
    'license': "LGPL-3",
    'category': "Finance/SACCO",
    'version': "17.0.1.0.1",
    'sequence': 2,

    'depends': [
        'base',
        'web',
        'account',
        'mail',
        'sms',
        'mass_mailing',  # Added for mailing list and email template features
    ],

    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/cron.xml',
        'data/mail_template_data.xml',  # New file for email template
        'data/mailing_list_data.xml',   
        'data/member_receipt_template.xml',   
        'views/sacco_member_menu.xml',
        'views/res_partner_view.xml',
        'views/membership_config_view.xml',
        'views/welcome_pack_config_view.xml',
        'views/birthday_pack_config_view.xml',
        'views/res_config_settings_view.xml',
        'views/res_company_view.xml',
    ],

    'assets': {
        'web.assets_backend': [
            'member_management/static/src/js/form_button.js',
        ],
        'web.assets_qweb': [
            'member_management/static/src/xml/form_button.xml',
        ],
    },

    'installable': True,
    'application': True,
    'auto_install': False,
    'images': [
        'static/description/icon.png',
        'static/description/banner.png',
    ],
    'support': 'support@omnitech.co.ug',
    'maintainer': 'Omni Software Ltd',
}