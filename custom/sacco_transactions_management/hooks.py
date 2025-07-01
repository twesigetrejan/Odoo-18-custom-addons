from odoo import api, SUPERUSER_ID

def post_init_hook(cr, registry):
    """Ensure the Member Journal exists after module installation."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['sacco.helper'].ensure_member_journal()