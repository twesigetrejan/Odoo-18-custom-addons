from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import requests
import base64
from ..config import (GET_MEMBERS_COLLECTION_ENDPOINT, GET_FILTERED_MEMBERS_COLLECTION_ENDPOINT, CREATE_MEMBERS_COLLECTION_ENDPOINT, CREATE_UPDATE_MEMBERS_COLLECTION_ENDPOINT, DOWNLOAD_FILE_ENDPOINT, UPLOAD_FILE_ENDPOINT)
from ..config import get_config
from datetime import datetime, timedelta
import logging
from PIL import Image
import io

_logger = logging.getLogger(__name__)

class MemberSync(models.Model):
    _name = 'member.sync'
    _description = 'Sync Members from External System'
    _inherit = ['api.token.mixin']
    
    last_sync_date = fields.Datetime(string="Last Sync Date", readonly=True)
    sync_from_date = fields.Datetime(string="Sync From Date")
    sync_all = fields.Boolean(string="Sync All Members", default=False)
    
    @api.model
    def _cron_sync_members(self):
        """Background sync job that runs periodically to sync failed members and fetch updates."""
        _logger.info("================= Starting combined member synchronization =================")
        
        # Step 1: Sync members with in_sync = False
        self._sync_failed_members()

        # Step 2: Sync updates from external system
        sync_record = self.search([], limit=1)
        if not sync_record:
            sync_record = self.create({})
        
        # Get the latest last_sync_date from res.partner
        latest_sync_date = self._get_latest_local_sync_date()
        sync_record.sync_from_date = latest_sync_date or (datetime.now() - timedelta(hours=24))
        sync_record.sync_all = False
        sync_record.action_sync_members()
        sync_record.last_sync_date = datetime.now()

    def _sync_failed_members(self):
        """Sync members with in_sync = False to the external system."""
        _logger.info("================= Starting sync of failed members =================")
        partners = self.env['res.partner'].search([('in_sync', '=', False), ('is_sacco_member', '=', True)])
        
        if not partners:
            _logger.info("No members with in_sync = False to sync.")
            return
        
        success_count = 0
        for partner in partners:
            try:
                result = self.update_member(partner)
                if result['params']['type'] == 'success':
                    success_count += 1
                self.env.cr.commit()
            except Exception as e:
                _logger.error(f"Failed to sync member {partner.name}: {str(e)}")
                self.env.cr.rollback()
                continue

        _logger.info(f"Failed members sync complete: {success_count} of {len(partners)} members synced successfully.")

    def _get_latest_local_sync_date(self):
        """Get the latest last_sync_date from res.partner records."""
        Partner = self.env['res.partner']
        latest_record = Partner.search([
            ('is_sacco_member', '=', True),
            ('last_sync_date', '!=', False),
        ], order='last_sync_date desc', limit=1)
        
        return latest_record.last_sync_date if latest_record else None
    
    def action_sync_members(self):
        """Main sync method that handles both manual and automatic sync"""
        _logger.info("================= Starting member synchronization from external system =================")
        
        token = self._get_authentication_token()
        if not token:
            return self._show_notification('Error', 'Failed to login into external system', 'danger')

        # Determine sync strategy
        if self.sync_all:
            data = self._fetch_all_members(token)
        else:
            sync_date = self.sync_from_date or self._get_latest_local_sync_date()
            data = self._fetch_filtered_members(token, sync_date)

        if data is None:
            return self._show_notification('Error', 'Something went wrong', 'danger')
        
        if not data.get('rows'):
            return self._show_notification('Info', 'No new records to sync', 'info')
        
        create_count, update_count, error_count = self._process_members(data.get('rows', []))

        return self._show_notification(
            'Sync Complete',
            f'Added: {create_count}, Updated: {update_count}, Errors: {error_count}',
            'success' if error_count == 0 else 'warning'
        )
 
    def _fetch_filtered_members(self, token, last_updated_date=None):
        """Fetch members with proper date filtering"""
        config = get_config(self.env)
        api_url = f"{config['BASE_URL']}/{GET_FILTERED_MEMBERS_COLLECTION_ENDPOINT}"
        headers = self._get_request_headers()

        body = {}
        if last_updated_date:
            date_str = last_updated_date.strftime('%Y-%m-%dT%H:%M:%S')
            body = {"lastUpdated": f"$date_filter:gt {date_str}"}
            _logger.info(f"Fetching members since: {date_str}")

        all_members = []
        page = 1
        limit = 1000

        while True:
            params = {'page': page, 'limit': limit}
            try:
                response = requests.post(api_url, headers=headers, json=body, params=params)
                response.raise_for_status()
                data = response.json()
                current_members = data.get('rows', [])
                
                if not current_members:
                    break
                    
                all_members.extend(current_members)
                if len(current_members) < limit:
                    break
                    
                page += 1
            except requests.RequestException as e:
                _logger.error(f"API request failed: {str(e)}")
                return None

        return {'rows': all_members}

        
    def _fetch_all_members(self, token):
        """Fetch all members using pagination."""
        all_members = []
        page = 1
        limit = 100
        
        while True:
            data = self._fetch_data_from_api(token, page, limit)
            if not data or not data.get('rows'):
                break
                
            current_members = data.get('rows', [])
            all_members.extend(current_members)
            
            # Check if we've received fewer records than the limit
            if len(current_members) < limit:
                break
                
            _logger.info(f"Fetched {len(current_members)} members from page {page}")
            page += 1
            
        _logger.info(f"Total members fetched: {len(all_members)}")
        return {'rows': all_members}

    def _fetch_data_from_api(self, token, page=1, limit=100):
        """Fetch member data from the external API with pagination."""
        config = get_config(self.env)
        
        api_url = f"{config['BASE_URL']}/{GET_MEMBERS_COLLECTION_ENDPOINT}"
        headers = self._get_request_headers()
        
        # Add pagination parameters
        params = {
            'page': page,
            'limit': limit
        }

        try:
            _logger.info(f"Fetching data from API: {api_url} - Page: {page}, Limit: {limit}")
            response = requests.get(api_url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            _logger.error(f"Failed to fetch data from API: {str(e)}")
            return None

    def _download_profile_picture(self, profile_picture):
        """Download profile picture from the external system."""
        if not profile_picture or not isinstance(profile_picture, str):
            _logger.warning("Invalid or empty profilePicture field, skipping download")
            return None

        filename = profile_picture.split('/')[-1] if '/' in profile_picture else profile_picture
        config = get_config(self.env)
        api_url = f"{config['BASE_URL']}/{DOWNLOAD_FILE_ENDPOINT}/{filename}/download"
        headers = self._get_request_headers()

        if not headers:
            _logger.error("Authentication credentials missing for profile picture download.")
            return None

        _logger.info(f"Attempting to download profile picture: {filename} from {api_url}")

        try:
            response = requests.get(api_url, headers=headers, stream=True)
            _logger.info(f"Download response status: {response.status_code} for {filename}")
            response.raise_for_status()
            content = response.content
            if not content:
                _logger.error(f"Empty file received for {filename}")
                return None
            _logger.info(f"Downloaded {len(content)} bytes for {filename}")
            encoded_content = base64.b64encode(content).decode('utf-8')
            return encoded_content
        except requests.RequestException as e:
            _logger.error(f"Failed to download profile picture {filename}: {str(e)}")
            return None

    def _process_members(self, members_data):
        """Process each member in bulk with transaction management."""
        create_count, update_count, error_count = 0, 0, 0
        
        # Process in smaller batches to avoid large transactions
        batch_size = 50
        for i in range(0, len(members_data), batch_size):
            batch = members_data[i:i + batch_size]
            
            try:
                with self.env.cr.savepoint():  # Use savepoint instead of commit/rollback
                    for member in batch:
                        try:
                            # Validate member data before processing
                            self._validate_member_data(member)
                            
                            result = self.create_update_members(member)
                            if result == 'created':
                                create_count += 1
                            elif result == 'updated':
                                update_count += 1
                        except Exception as e:
                            _logger.exception(f"Error processing member {member.get('_id')}: {str(e)}")
                            error_count += 1
                            continue  # Continue with next member
                            
            except Exception as e:
                _logger.exception(f"Critical error during batch processing: {str(e)}")
                error_count += len(batch)

        _logger.info(f"Processing results: {create_count} created, {update_count} updated, {error_count} errors.")
        return create_count, update_count, error_count
    
    def _validate_member_data(self, member_data):
        """Validate member data before processing."""
        required_fields = ['_id', 'firstName', 'lastName', 'email']
        for field in required_fields:
            if not member_data.get(field):
                _logger.warning(f"Missing required field: {field}")

    def create_update_members(self, member_data):
        # Use context to bypass constraints, tracking, and member_id/username checks
        Partner = self.env['res.partner'].with_context(
            tracking_disable=True,  # Disable tracking
            bypass_constraints=True,  # Bypass constraints (e.g., required fields)
            external_sync=True  # Indicate external sync to skip member_id/username logic
        )
        
        _logger.info(f"Processing member data for ID: {member_data.get('username')}")

        try:
            # Check if member already exists
            existing_member = self.env['res.partner'].search([
                '|', '|', '|',
                ('member_id', '=', member_data.get('memberId')),
                ('member_id', '=', member_data.get('username')),
                ('username', '=', str(member_data.get('username')).upper() if member_data.get('username') else False),
                ('username', '=', str(member_data.get('username')).lower() if member_data.get('username') else False)
            ], limit=1)

            # Prepare member values, skipping missing fields
            member_vals = self._prepare_member_vals(member_data)
            
            # Remove any computed fields that might cause issues
            for field in ['ubl_cii_format', 'email_normalized', 'phone_sanitized']:
                member_vals.pop(field, None)
            
            if existing_member:
                # Skip updating email if it hasn't changed or if it would cause a duplicate
                current_email = existing_member.email
                new_email = member_vals.get('email')
                if new_email and current_email != new_email:
                    # Check for duplicate email excluding the current record
                    if self.env['res.partner'].search_count([
                        ('email', '=', new_email),
                        ('is_sacco_member', '=', True),
                        ('id', '!=', existing_member.id)
                    ]):
                        _logger.info(f"Skipping email update for member {member_data.get('username')} due to existing email: {new_email}")
                        member_vals.pop('email', None)  # Remove email from update to avoid constraint violation
                elif new_email == current_email:
                    member_vals.pop('email', None)  # No need to update if email is the same
                
                _logger.info(f"Updating existing member: {member_data.get('username')}")
                existing_member.with_context(external_sync=True).write(member_vals)
                return 'updated'
            else:
                _logger.info(f"Creating new member with values: {member_vals}")
                Partner.create(member_vals)
                return 'created'
        except Exception as e:
            _logger.exception(f"Error processing member: {str(e)}")
            raise UserError(f"Failed to process member ID {member_data.get('username')}. Error: {str(e)}")
        
    def _prepare_member_vals(self, member_data):
        """Prepare member values for creation or update, handling missing fields and profile picture."""
        def parse_date(date_string):
            try:
                return datetime.fromisoformat(date_string) if date_string else None
            except ValueError:
                _logger.warning(f"Invalid date format: {date_string}")
                return None

        def safe_get(data, key=None, default=None, to_lower=False):
            """Unified safe_get function to handle both dictionary and direct value access."""
            if key is not None:
                # Dictionary access mode
                value = data.get(key, default)
            else:
                # Direct value mode
                value = data
            if value is None:
                return default
            return str(value).lower() if isinstance(value, str) and to_lower else str(value) if isinstance(value, str) else value

        def get_id_type(doc_type):
            id_type_map = {
                'National ID': 'nationalId',
                'Driving License': 'drivingLicense',
                'Passport': 'passport',
            }
            return id_type_map.get(doc_type, 'nationalId')

        # Download profile picture if it exists
        profile_picture_data = None
        if member_data.get('profilePicture'):
            profile_picture_data = self._download_profile_picture(member_data.get('profilePicture'))

        # Default values for required fields
        default_values = {
            'name': 'Unknown Member',  # Default name if firstName and lastName are missing
            'email': 'no-email@example.com',  # Default email if missing
            'phone': '0000000000',  # Default phone if missing
            'is_sacco_member': True,
        }

        # Prepare member values, using defaults for missing fields
        member_vals = {
            'mongo_db_id': member_data.get('_id'),
            'ref_id': safe_get(member_data, 'refID'),
            'first_name': safe_get(member_data, 'firstName', 'Unknown'),  # Preserve case
            'middle_name': safe_get(member_data, 'middleName', ''),
            'last_name': safe_get(member_data, 'lastName', 'Member'),  # Preserve case
            'gender': safe_get(member_data, 'gender', 'male', to_lower=True),
            'member_id': safe_get(member_data, 'memberId', to_lower=True),
            'username': safe_get(member_data, 'username'),
            'name': f"{safe_get(member_data, 'firstName', 'Unknown')} {safe_get(member_data, 'lastName', 'Member')}".strip(),
            'member_type': safe_get(member_data, 'memberType', 'individual', to_lower=True),
            'email': safe_get(member_data, 'email', default_values['email'], to_lower=True),
            'role': 'member' if safe_get(member_data, 'role', to_lower=True) == 'sacco member' else 'admin',
            'date_of_birth': parse_date(safe_get(member_data, 'memberDateOfBirth')),
            'phone': safe_get(member_data, 'memberPhoneNumber', default_values['phone']),
            'employment_status': 'selfemployed' if safe_get(member_data, 'Self Employed', to_lower=True) == 'activated' else 'employed',
            'marital_status': safe_get(member_data, 'maritalStatus', 'single', to_lower=True),
            'id_type': get_id_type(safe_get(member_data, 'memberIdentificationDocument', to_lower=True)),
            'id_number': safe_get(member_data, 'memberIdNumber'),
            'registration_date': parse_date(safe_get(member_data, 'dateCreated')),
            'next_of_kin_name': safe_get(member_data, 'kinFullName'),  # Preserve case
            'next_of_kin_relationship': safe_get(member_data, 'relationship', to_lower=True),
            'next_of_kin_dob': parse_date(safe_get(member_data, 'kinDateOfBirth')),
            'next_of_kin_phone': safe_get(member_data, 'kinPhoneNumber'),
            'next_of_kin_address': safe_get(member_data, 'kinPhysicalAddress'),
            'next_of_kin_email': safe_get(member_data, 'kinEmail', to_lower=True),
            'next_of_kin_id_type': get_id_type(safe_get(member_data, 'kinIdDocumentType', to_lower=True)),
            'next_of_kin_id_number': safe_get(member_data, 'kinIdNumber'),
            'membership_status': 'active' if safe_get(member_data, 'activationStatus', to_lower=True) == 'activated' else 'deactivated',
            'is_sacco_member': default_values['is_sacco_member'],
            'joining_date': parse_date(safe_get(member_data, 'joiningDate')),
            'membership_status': safe_get(member_data, 'membershipStatus', 'details_processing', to_lower=True),
            'exit_date': parse_date(safe_get(member_data, 'exitDate')),
            'branch_code': safe_get(member_data, 'branchCode'),
            'last_sync_date': parse_date(safe_get(member_data, 'lastUpdated')),
            'in_sync': True,
        }

        # Add profile picture if downloaded successfully
        if profile_picture_data:
            member_vals['image_1920'] = profile_picture_data

        # Remove None values to avoid writing NULL to required fields
        member_vals = {k: v for k, v in member_vals.items() if v is not None}

        return member_vals
        
    def _show_notification(self, title, message, type='info'):
        _logger.info(f"Showing notification - Title: {title}, Message: {message}, Type: {type}")
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': message,
                'sticky': True,
                'type': type,
            }
        }
        
    def _upload_profile_picture(self, partner, token):
        """Upload profile picture to the external system and return the path."""
        if not partner.image_1920:
            _logger.info(f"No profile picture found for member {partner.member_id}")
            return None

        config = get_config(self.env)
        api_url = f"{config['BASE_URL']}/{UPLOAD_FILE_ENDPOINT}"
        headers = self._get_request_headers()

        if not headers:
            _logger.error("Authentication credentials missing for profile picture upload.")
            return None

        try:
            # Decode base64 image
            image_data = base64.b64decode(partner.image_1920)
            image = Image.open(io.BytesIO(image_data))
            image_format = image.format.lower() if image.format else 'png'
            if image_format not in ['jpeg', 'jpg', 'png']:
                image_format = 'png'
                image = image.convert('RGB')

            # Prepare filename as member_id.extension
            filename = f"{partner.member_id}.{image_format}"

            # Save image to a BytesIO object
            img_io = io.BytesIO()
            image.save(img_io, format=image_format.upper())
            img_io.seek(0)

            # Prepare form-data
            files = {
                'file': (filename, img_io, f'image/{image_format}')
            }

            _logger.info(f"Uploading profile picture for member {partner.member_id} to {api_url}")

            # Send POST request
            response = requests.post(api_url, headers=headers, files=files)
            response.raise_for_status()
            response_data = response.json()

            # Extract path from response
            file_path = response_data.get('path')
            if not file_path:
                _logger.error(f"No path returned in upload response for member {partner.member_id}")
                return None

            _logger.info(f"Successfully uploaded profile picture for member {partner.member_id}: {file_path}")
            return file_path

        except Exception as e:
            _logger.error(f"Failed to upload profile picture for member {partner.member_id}: {str(e)}")
            return None

    def upload_member(self, partner):
        """Upload a single member to the external system."""
        if partner.mongo_db_id or partner.ref_id:
            return partner._show_notification(
                'Error',
                'Member already exists in external system. Use "Update Member" instead.',
                'danger'
            )

        token, account_id = self._get_authentication_token()
        if not token:
            partner.write({'in_sync': False})
            return partner._show_notification(
                'Warning',
                'Member created successfully. The data will be synced with the external system shortly, depending on network availability.',
                'warning'
            )

        # Upload profile picture if it exists
        profile_picture_path = self._upload_profile_picture(partner, token)

        config = get_config(self.env)
        api_url = f"{config['BASE_URL']}/{CREATE_MEMBERS_COLLECTION_ENDPOINT}"
        headers = self._get_request_headers()
        data = partner._prepare_member_data()
        
        # Add profile picture path to data if available
        if profile_picture_path:
            data['profilePicture'] = profile_picture_path

        try:
            response = requests.post(api_url, headers=headers, json=data)
            response.raise_for_status()
            response_data = response.json()
            
            partner.write({
                'mongo_db_id': response_data.get('docId', ''),
                'ref_id': response_data.get('refID', ''),
                'last_sync_date': parse_date(response_data.get('lastUpdated')),
                'in_sync': True,
            })
            return partner._show_notification('Success', 'Member uploaded successfully', 'success')
        except requests.RequestException as e:
            _logger.error(f"Failed to upload member: {str(e)}")
            partner.write({'in_sync': False})
            return partner._show_notification(
                'Warning',
                'Member created successfully. The data will be synced with the external system shortly, depending on network availability.',
                'warning'
            )

    def update_member(self, partner):
        """Update a single member in the external system."""
        if not (partner.mongo_db_id or partner.ref_id):
            return partner._show_notification(
                'Error',
                'Member does not exist in external system. Use "Upload Member" instead.',
                'danger'
            )

        token, account_id = self._get_authentication_token()
        if not token:
            partner.write({'in_sync': False})
            return partner._show_notification(
                'Warning',
                'Member updated successfully. The data will be synced with the external system shortly, depending on network availability.',
                'warning'
            )

        # Upload profile picture if it exists
        profile_picture_path = self._upload_profile_picture(partner, token)

        mongo_id = partner.mongo_db_id or partner.ref_id
        config = get_config(self.env)
        api_url = f"{config['BASE_URL']}/{CREATE_UPDATE_MEMBERS_COLLECTION_ENDPOINT}/{mongo_id}"
        headers = self._get_request_headers()
        data = partner._prepare_member_data()
        data.pop('username', None) # Remove username if present, as it is not needed for update
        
        # Add profile picture path to data if available
        if profile_picture_path:
            data['profilePicture'] = profile_picture_path

        try:
            response = requests.post(api_url, headers=headers, json=data)
            response.raise_for_status()
            response_data = response.json()
            partner.write({
                'last_sync_date': parse_date(response_data.get('lastUpdated')),
                'in_sync': True,
            })
            return partner._show_notification('Success', 'Member updated successfully', 'success')
        except requests.RequestException as e:
            _logger.error(f"Failed to update member: {str(e)}")
            partner.write({'in_sync': False})
            return partner._show_notification(
                'Warning',
                'Member updated successfully. The data will be synced with the external system shortly, depending on network availability.',
                'warning'
            )

    def mass_upload_members(self, partners):
        """Mass upload new members."""
        if not partners:
            raise UserError(_("No members selected for upload."))

        existing = partners.filtered(lambda r: r.mongo_db_id or r.ref_id)
        if existing:
            raise UserError(
                _("Cannot upload members that already exist in the external system: %s. Use 'Mass Update Members' instead.")
                % ", ".join(existing.mapped('name'))
            )

        success_count = 0
        for partner in partners:
            try:
                if partner.is_sacco_member:
                    result = self.upload_member(partner)
                    if result['params']['type'] == 'success':
                        success_count += 1
                    self.env.cr.commit()
            except Exception as e:
                self.env.cr.rollback()
                _logger.error(f"Failed to upload member {partner.name}: {str(e)}")

        return self._show_notification(
            'Mass Upload Complete',
            f'Successfully uploaded {success_count} of {len(partners)} members',
            'success' if success_count == len(partners) else 'warning'
        )

    def mass_update_members(self, partners):
        """Mass update existing members."""
        if not partners:
            raise UserError(_("No members selected for update."))

        non_existing = partners.filtered(lambda r: not (r.mongo_db_id or r.ref_id))
        if non_existing:
            raise UserError(
                _("Cannot update members not yet in the external system: %s. Use 'Mass Upload Members' instead.")
                % ", ".join(non_existing.mapped('name'))
            )

        success_count = 0
        for partner in partners:
            try:
                if partner.is_sacco_member:
                    result = self.update_member(partner)
                    if result['params']['type'] == 'success':
                        success_count += 1
                    self.env.cr.commit()
            except Exception as e:
                self.env.cr.rollback()
                _logger.error(f"Failed to update member {partner.name}: {str(e)}")

        return self._show_notification(
            'Mass Update Complete',
            f'Successfully updated {success_count} of {len(partners)} members',
            'success' if success_count == len(partners) else 'warning'
        )

def parse_date(date_string):
    try:
        return datetime.fromisoformat(date_string) if date_string else None
    except ValueError:
        _logger.warning(f"Invalid date format: {date_string}")
        return None