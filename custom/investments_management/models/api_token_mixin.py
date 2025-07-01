from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta
import logging
from ..config import get_config
import requests

_logger = logging.getLogger(__name__)

class APITokenMixin(models.AbstractModel):
    _name = 'api.token.mixin'
    _description = 'API Token Management Mixin'

    def _get_token_key(self):
        """Generate a unique key for storing the token."""
        return f'api_auth_token_{self.env.company.id}'

    def _get_token_expiry_key(self):
        """Generate a unique key for storing the token expiry."""
        return f'api_auth_token_expiry_{self.env.company.id}'

    def _get_account_id_key(self):
        """Generate a unique key for storing the account ID."""
        return f'api_account_id_{self.env.company.id}'

    def _get_stored_token_info(self):
        """Retrieve token and account_id information from system parameters."""
        ICP = self.env['ir.config_parameter'].sudo()
        token = ICP.get_param(self._get_token_key())
        expiry_str = ICP.get_param(self._get_token_expiry_key())
        account_id = ICP.get_param(self._get_account_id_key())

        if not token or not expiry_str or not account_id:
            return None, None, None
            
        try:
            expiry = datetime.fromisoformat(expiry_str)
            return token, expiry, account_id
        except (ValueError, TypeError):
            return None, None, None

    def _store_token_info(self, token, expiry, account_id):
        """Store token and account_id information in system parameters."""
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param(self._get_token_key(), token)
        ICP.set_param(self._get_token_expiry_key(), expiry.isoformat())
        ICP.set_param(self._get_account_id_key(), account_id)

    def _clear_token_info(self):
        """Clear stored token and account_id information."""
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param(self._get_token_key(), False)
        ICP.set_param(self._get_token_expiry_key(), False)
        ICP.set_param(self._get_account_id_key(), False)

    def _get_authentication_token(self):
        """Get a valid authentication token or generate a new one if needed."""
        _logger.info("==== Checking or generating authentication token ====")
        token, expiry, account_id = self._get_stored_token_info()
        
        _logger.info(f"Stored token: {token}, expiry: {expiry}, account_id: {account_id}")

        # Check if token exists and is still valid (with some margin)
        if token and expiry and expiry > datetime.now() + timedelta(minutes=5):
            return token, account_id

        # Clear any existing token
        self._clear_token_info()
        
        # Get configuration values
        config = get_config(self.env)

        # Generate new token
        _logger.info("==== Logging into external system ====")
        login_url = f"{config['BASE_URL']}/{config['LOGIN_ENDPOINT']}"
        login_data = {
            "username": config['USERNAME'],
            "password": config['PASSWORD']
        }
        
        _logger.info(f"Login data {login_data}")

        try:
            response = requests.post(login_url, json=login_data)
            response.raise_for_status()
            data = response.json()
            _logger.info(f"Login data {data}")
            new_token = data.get('access_token')
            account_id = data.get('account_id')
            
            if not account_id:
                _logger.error("Login failed: account_id missing.")
                raise UserError(_("Unauthorized: account_id missing"))
            
            # Store new token and account_id with 24-hour expiry
            expiry = datetime.now() + timedelta(hours=24)
            self._store_token_info(new_token, expiry, account_id)

            return new_token, account_id
        except requests.RequestException as e:
            _logger.error(f"Failed to obtain auth token: {str(e)}")
            raise UserError(_("Failed to authenticate with external system"))

    def _get_request_headers(self):
        """Get request headers including Authorization and X-Account-ID."""
        token, account_id = self._get_authentication_token()
        if not token or not account_id:
            raise UserError(_("Missing authentication credentials. Please log in again."))
        
        return {
            'Authorization': f'Bearer {token}',
            'X-AccountId': account_id,
        }

    def make_api_request(self, endpoint, method='GET', payload=None):
        """Make an API request with the stored token and account_id."""
        config = get_config(self.env)
        url = f"{config['BASE_URL']}/{endpoint}"
        headers = self._get_request_headers()

        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=headers, params=payload)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=headers, json=payload)
            elif method.upper() == 'PUT':
                response = requests.put(url, headers=headers, json=payload)
            elif method.upper() == 'DELETE':
                response = requests.delete(url, headers=headers)
            else:
                raise UserError(_("Invalid HTTP method"))
            
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            _logger.error(f"API request to {endpoint} failed: {str(e)}")
            raise UserError(_("Failed to communicate with the external system"))
