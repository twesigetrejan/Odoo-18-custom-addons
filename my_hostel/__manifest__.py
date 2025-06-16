
# {
#     'name': 'Hostel Management',
#     'installable': True,
#     'application': True,
#     'category': 'Tools',
#     'version': '1.0',
#     'summary': 'A dummy module to test custom addons',
# }

{
    'name': "Hostel Management",
    'summary': "Manage hostels easily within the school",
    'description': "Efficiently manage the entire residential facility in the school.",
    'author': "trejan_dev",
    'website': "http://www.example.com",
    'category': 'Education',
    'version': '17.0.1.0.0',
    'depends': ['base'],
    'data': [
        'security/hostel_security.xml',
        'security/ir.model.access.csv',
        'views/hostel.xml',
        'views/hostel_room.xml',
        'views/hostel_category.xml',
    ],
    'assets': {
        'web.assets_backend': [
        
            'my_hostel/static/src/xml/**/*',
        ],
    },
    'demo': [
        'demo/demo.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
