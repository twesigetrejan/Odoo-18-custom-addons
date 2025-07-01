# -*- coding: utf-8 -*-
{
    'name': "MIS Configuration Management",
    'author': "My Company",
    'website': "https://www.omnitech.co.ug",
    'version': '0.1',
    'depends': ['base', 'member_management', 'savings_management', 'investments_management', 'sacco_loan_management', 'sacco_transactions_management'],
    'data': [
        'security/ir.model.access.csv',
        'data/cron.xml',
        'views/mis_configure_views.xml',
        'views/res_config_settings_view.xml',
        'views/templates.xml',
    ]
}

