{
    'name': "Hostel Management",
    'summary': "Manage hostels easily within the school",
    'description': "Efficiently manage the entire residential facility in the school.",
    'author': "trejan_dev",
    'website': "http://www.example.com",
    'category': 'Education',
    'version': '17.0.1.0.1',
    'depends': ['base', 'web'],
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
            'my_hostel/static/src/js/lib/chart.js',  # Local Chart.js file
            'my_hostel/static/src/js/hostel_dashboard_main.js',
            'my_hostel/static/src/xml/hostel_dashboard_main.xml',
            'https://cdn.jsdelivr.net/npm/chart.js',
        ],
        'web.assets_qweb': [
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