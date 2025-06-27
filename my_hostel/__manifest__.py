
{
    'name': "Hostel Management",
    # 'post_init_hook': 'post_init_hook.create_default_categories',
    'summary': "Manage hostels easily within the school",
    'description': "Efficiently manage the entire residential facility in the school.",
    'author': "trejan_dev",
    'website': "http://www.example.com",
    'category': 'Education',
    'version': '17.0.1.0.1',
    'depends': ['base'],
    'data': [
        'security/hostel_security.xml',
        'security/ir.model.access.csv',
        'views/hostel.xml',
        'views/hostel_room.xml',
        'views/hostel_category.xml',
        'views/hostel_student.xml',
        'views/room_category.xml',
        'views/hostel_dashboard_menu.xml',
        'data/data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'my_hostel/static/src/css/hostel.css',
            # 'my_hostel/static/src/js/hostel_kanban.js',
        ],
    },
    'demo': [
        'demo/demo.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}