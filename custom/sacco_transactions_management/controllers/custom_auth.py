from werkzeug.exceptions import BadRequest
from odoo import models
from odoo.http import request

class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _auth_method_custom_auth(cls):
        # Skip authentication for OPTIONS requests
        if request.httprequest.method == 'OPTIONS':
            return

        # Proceed with authentication for other methods (e.g., GET, POST)
        access_token = request.httprequest.headers.get('Authorization')
        if not access_token:
            raise BadRequest("Access token missing")
        if access_token.startswith('Bearer '):
            access_token = access_token[7:]
        user_id = request.env['res.users.apikeys']._check_credentials(
            scope='odoo.restapi', key=access_token)
        if not user_id:
            raise BadRequest("Access token invalid")
        request.update_env(user=user_id)