from odoo import api, SUPERUSER_ID

def migrate(cr, version):
    """Post-migration script to remove old 'photo' field from hostel_student table."""
    if not version:
        return

    cr.execute("""
        ALTER TABLE hostel_student DROP COLUMN IF EXISTS photo;
    """)
