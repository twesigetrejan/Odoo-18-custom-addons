# from odoo import api, SUPERUSER_ID

# def create_default_categories(cr, registry):
#     """
#     Create default room categories when module is installed
#     This will run automatically after module installation
#     """
#     env = api.Environment(cr, SUPERUSER_ID, {})
    
#     # Get the room category model
#     Category = env['hostel.room.category']
    
#     # Default categories to create
#     default_categories = [
#         {
#             'name': 'Single Room',
#             'description': 'A room for one person',
#             'max_allow_days': 30
#         },
#         {
#             'name': 'Double Room',
#             'description': 'A room for two persons',
#             'max_allow_days': 30
#         },
#         {
#             'name': 'Deluxe Room',
#             'description': 'A room with additional amenities',
#             'max_allow_days': 60
#         },
#         {
#             'name': 'Dormitory',
#             'description': 'Shared room for multiple students',
#             'max_allow_days': 90
#         }
#     ]
    
#     # Create categories if they don't exist
#     for category_vals in default_categories:
#         if not Category.search([('name', '=', category_vals['name'])]):
#             Category.create(category_vals)
    
#     # Create parent-child relationships if needed
#     parent_category = Category.search([('name', '=', 'Standard Rooms')])
#     if not parent_category:
#         parent_category = Category.create({
#             'name': 'Standard Rooms',
#             'description': 'Standard accommodation options'
#         })
        
#         # Set single and double as children
#         for cat_name in ['Single Room', 'Double Room']:
#             child = Category.search([('name', '=', cat_name)])
#             if child:
#                 child.write({'parent_id': parent_category.id})