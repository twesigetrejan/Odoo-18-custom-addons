# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
import requests
import logging

_logger = logging.getLogger(__name__)

class MISConfigure(models.Model):
    _name = 'omni.mis.configure'
    _description = 'MIS Configuration'
    _inherit = ['api.token.mixin']

    name = fields.Char(string='Name', required=True, help='Add the name', default='MIS Configuration')
    mis_base_url = fields.Char(string='MIS Base URL')
    admin_username = fields.Char(string='Sacco Admin Username')
    account_password = fields.Char(string='MIS Super User Password')
    sacco_account = fields.Char(string='Sacco Account')
    mis_user = fields.Char(string='MIS Super User Username')
    login_endpoint = fields.Char(string='Login Endpoint')
    is_test_instance = fields.Boolean(string='Is Test Instance?')
    
    # Members Collection endpoints
    create_members_collection = fields.Char(string='Create Members Collection Endpoint')
    get_members_collection = fields.Char(string='Get Members Collection Endpoint')
    update_members_collection = fields.Char(string='Create Members Collection Endpoint')

    def action_test_connection(self):
            """Test connection to MIS system with fresh login attempt"""
            self._clear_token_info()  # Clear any existing tokens
            
            if not self.mis_base_url or not self.admin_username or not self.account_password:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Please fill in all required credentials',
                        'type': 'danger',
                        'sticky': False,
                    }
                }

            login_url = f"{self.mis_base_url.rstrip('/')}/api/v1/user/login"
            login_data = {
                "username": self.admin_username,
                "password": self.account_password
            }

            try:
                response = requests.post(login_url, json=login_data)
                response.raise_for_status()
                data = response.json()

                if not data.get('access_token') or not data.get('account_id'):
                    raise UserError('Invalid response from server')

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Success',
                        'message': 'Successfully connected to MIS system',
                        'type': 'success',
                        'sticky': False,
                    }
                }

            except requests.RequestException as e:
                _logger.error(f"Connection test failed: {str(e)}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'Connection failed: Incorrect URL or credentials.',
                        'type': 'danger',
                        'sticky': False,
                    }
                }