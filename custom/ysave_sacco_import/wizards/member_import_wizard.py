# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import pandas as pd
import base64
import logging
from datetime import datetime
import re
import os

# Configure custom error logger
log_file_path = os.path.join(os.path.dirname(__file__), 'OdooLogs', 'member_import_errors.log')  # Adjust path as needed
os.makedirs(os.path.dirname(log_file_path), exist_ok=True)  # Ensure directory exists
error_logger = logging.getLogger('member_import_errors')
error_logger.setLevel(logging.ERROR)
if not error_logger.handlers:  # Prevent duplicate handlers
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    error_logger.addHandler(file_handler)

_logger = logging.getLogger(__name__)

class MemberImportWizard(models.TransientModel):
    _name = 'member.import.wizard'
    _description = 'Wizard to Import SACCO Members from Excel'

    file = fields.Binary(string='Excel File', required=True)
    file_name = fields.Char(string='File Name')

    def action_import_external(self):
        """Import members from the uploaded Excel file (external format)."""
        if not self.file:
            raise UserError(_("Please upload an Excel file."))

        try:
            file_data = base64.b64decode(self.file)
            df = pd.read_excel(file_data, engine='openpyxl', dtype={'username': str})
            create_count, update_count, error_count = self._process_external_members(df)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('External Import Complete'),
                    'message': _(f'Added: {create_count}, Updated: {update_count}, Errors: {error_count}'),
                    'sticky': True,
                    'type': 'success' if error_count == 0 else 'warning',
                }
            }
        except Exception as e:
            error_logger.error(f"Failed to import external members: {str(e)}")
            raise UserError(_(f"Failed to import external members: {str(e)}"))

    def action_import_internal(self):
        """Import members from the uploaded Excel file (internal format)."""
        if not self.file:
            raise UserError(_("Please upload an Excel file."))

        try:
            file_data = base64.b64decode(self.file)
            df = pd.read_excel(file_data, engine='openpyxl', dtype={'ClientCode': str})
            create_count, skip_count, error_count = self._process_internal_members(df)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Internal Import Complete'),
                    'message': _(f'Added: {create_count}, Skipped: {skip_count}, Errors: {error_count}'),
                    'sticky': True,
                    'type': 'success' if error_count == 0 else 'warning',
                }
            }
        except Exception as e:
            error_logger.error(f"Failed to import internal members: {str(e)}")
            raise UserError(_(f"Failed to import internal members: {str(e)}"))

    def _process_external_members(self, df):
        """Process members from external Excel format."""
        Partner = self.env['res.partner'].with_context(
            tracking_disable=True,
            bypass_constraints=True,
        )
        create_count = 0
        update_count = 0
        error_count = 0
        email_counter = 0  # Counter for unique default emails

        def safe_get(value, default=None, to_lower=False, to_string=False):
            if pd.isna(value):
                return default
            # Convert to string explicitly if to_string is True
            result = str(value) if to_string or isinstance(value, str) else value
            return result.lower() if isinstance(result, str) and to_lower else result

        for index, row in df.iterrows():
            try:
                with self.env.cr.savepoint():
                    member_vals = self._prepare_external_member_vals(row, email_counter)
                    username = safe_get(row.get('username'), to_lower=True, to_string=True)
                    existing_member = Partner.search([('member_id', '=', username)], limit=1)
                    if existing_member:
                        existing_member.write(member_vals)
                        update_count += 1
                        _logger.info(f"Updated external member: {username} at index {index}")
                    else:
                        Partner.create(member_vals)
                        create_count += 1
                        _logger.info(f"Created external member: {username} at index {index}")
                    if member_vals.get('email', '').startswith('no-email'):
                        email_counter += 1  # Increment counter if default email was used
            except Exception as e:
                error_count += 1
                error_logger.error(f"Processing external member {row.get('username', 'Unknown')} at index {index}: {str(e)}")
                continue

        return create_count, update_count, error_count

    def _process_internal_members(self, df):
        """Process members from internal Excel format."""
        Partner = self.env['res.partner'].with_context(
            tracking_disable=True,
            bypass_constraints=True,
        )
        create_count = 0
        skip_count = 0
        error_count = 0
        email_counter = 378  # Counter for unique default emails
        
        def safe_get(value, default=None, to_lower=False, to_string=False):
            if pd.isna(value):
                return default
            # Convert to string explicitly if to_string is True
            result = str(value) if to_string or isinstance(value, str) else value
            return result.lower() if isinstance(result, str) and to_lower else result

        def format_client_code(code):
            code_str = str(code).zfill(4)
            return code_str if len(code_str) == 4 else code_str

        for index, row in df.iterrows():
            try:
                with self.env.cr.savepoint():
                    client_code = format_client_code(safe_get(row.get('ClientCode'), to_lower=True, to_string=True))
                    existing_member = Partner.search([('member_id', '=', client_code)], limit=1)
                    if existing_member:
                        _logger.info(f"Skipped internal member with ClientCode: {client_code} at index {index} (already exists)")
                        skip_count += 1
                        continue
                    member_vals = self._prepare_internal_member_vals(row, email_counter)
                    Partner.create(member_vals)
                    create_count += 1
                    _logger.info(f"Created internal member: {client_code} at index {index}")
                    if member_vals.get('email', '').startswith('no-email'):
                        email_counter += 1  # Increment counter if default email was used
            except Exception as e:
                error_count += 1
                error_logger.error(f"Processing internal member {row.get('ClientCode', 'Unknown')} at index {index}: {str(e)}")
                continue

        return create_count, skip_count, error_count

    def _prepare_external_member_vals(self, row, email_counter):
        """Prepare member values for external Excel format."""
        def parse_date(value):
            try:
                if pd.isna(value):
                    return None
                if isinstance(value, (int, float)):
                    return datetime.fromtimestamp(value / 1000.0).date()
                if isinstance(value, str):
                    try:
                        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S.%f').date()
                    except ValueError:
                        return datetime.strptime(value, '%Y-%m-%d %H:%M:%S').date()
                if isinstance(value, (pd.Timestamp, datetime)):
                    return value.date()
                error_logger.warning(f"Unsupported date format: {value}")
                return None
            except (ValueError, TypeError) as e:
                error_logger.warning(f"Invalid date format: {value}, error: {str(e)}")
                return None

        def safe_get(value, default=None, to_lower=False, to_string=False):
            if pd.isna(value):
                return default
            # Convert to string explicitly if to_string is True
            result = str(value) if to_string or isinstance(value, str) else value
            return result.lower() if isinstance(result, str) and to_lower else result

        # Generate unique default email
        default_email = f'no-email{email_counter + 1}@example.com' if safe_get(row.get('email')) is None else safe_get(row.get('email'), to_lower=True)

        member_vals = {
            'is_sacco_member': True,
            'mongo_db_id': None,
            'ref_id': None,
            'member_id': safe_get(row.get('username'), to_lower=True, to_string=True),
            'first_name': safe_get(row.get('first_name'), 'Unknown'),
            'last_name': safe_get(row.get('last_name'), 'Member'),
            'name': f"{safe_get(row.get('first_name'), 'Unknown')} {safe_get(row.get('last_name'), 'Member')}".strip(),
            'member_type': safe_get(row.get('member_type'), 'individual', to_lower=True),
            'email': default_email,
            'primary_phone': safe_get(row.get('telephone_contact')),
            'secondary_phone': safe_get(row.get('cell_number')),
            'res_address_line1': safe_get(row.get('residential_address')),
            'date_of_birth': parse_date(row.get('date_of_birth')),
            'id_number': safe_get(row.get('nin')) or safe_get(row.get('passport_number')),
            'id_type': safe_get(row.get('nin'), to_lower=True) and 'nationalId' or safe_get(row.get('passport_number'), to_lower=True) and 'passport' or None,
            'registration_date': parse_date(row.get('date_created')),
            'activation_status': 'deactivated',
            'membership_status': 'inactive',
            # 'activation_status': safe_get(row.get('enabled'), to_lower=True) == 1 and 'activated' or 'deactivated',
            # 'membership_status': safe_get(row.get('enabled'), to_lower=True) == 1 and 'active' or 'inactive',
        }

        # Generate unique default email for next of kin
        default_nok_email = f'no-email{email_counter + 1}@example.com' if safe_get(row.get('emailj')) is None else safe_get(row.get('emailj'), to_lower=True)

        next_of_kin_fields = {
            'next_of_kin_name': safe_get(row.get('first_namej')),
            'next_of_kin_email': default_nok_email,
            'next_of_kin_phone': safe_get(row.get('telephone_contactj')),
            'next_of_kin_address': safe_get(row.get('residential_addressj')),
            'next_of_kin_id_number': safe_get(row.get('ninj')) or safe_get(row.get('passport_numberj')),
            'next_of_kin_id_type': safe_get(row.get('ninj'), to_lower=True) and 'nationalId' or safe_get(row.get('passport_numberj'), to_lower=True) and 'passport' or None,
            'next_of_kin_dob': parse_date(row.get('date_of_birthj')),
        }

        if any(v for v in next_of_kin_fields.values()):
            member_vals.update(next_of_kin_fields)

        return {k: v for k, v in member_vals.items() if v is not None}

    def _prepare_internal_member_vals(self, row, email_counter):
        """Prepare member values for internal Excel format."""
        def parse_date(value):
            try:
                if pd.isna(value):
                    return None
                if isinstance(value, str):
                    return datetime.strptime(value, '%Y-%m-%d').date()
                if isinstance(value, (pd.Timestamp, datetime)):
                    return value.date()
                error_logger.warning(f"Unsupported date format: {value}")
                return None
            except (ValueError, TypeError) as e:
                error_logger.warning(f"Invalid date format: {value}, error: {str(e)}")
                return None

        def safe_get(value, default=None, to_lower=False, to_string=False):
            if pd.isna(value):
                return default
            # Convert to string explicitly if to_string is True
            result = str(value) if to_string or isinstance(value, str) else value
            return result.lower() if isinstance(result, str) and to_lower else result

        names = safe_get(row.get('Names'), 'Unknown Member').strip()
        if '&' in names:
            name_parts = names.split('&', 1)
            first_name = name_parts[0].strip()
            last_name = name_parts[1].strip() if len(name_parts) > 1 else 'Member'
        else:
            name_parts = names.split(' ', 1)
            first_name = name_parts[0].strip()
            last_name = name_parts[1].strip() if len(name_parts) > 1 else 'Member'

        mobile = safe_get(row.get('Mobile'))
        if mobile and '/' in mobile:
            mobile = mobile.split('/')[0].strip()

        # Generate unique default email
        default_email = f'no-email{email_counter + 1}@example.com' if not re.match(r"[^@]+@[^@]+\.[^@]+", safe_get(row.get('Email'), '')) else safe_get(row.get('Email'), to_lower=True)

        member_vals = {
            'is_sacco_member': True,
            'mongo_db_id': None,
            'ref_id': None,
            'member_id': safe_get(row.get('ClientCode'), to_lower=True, to_string=True),
            'first_name': first_name,
            'last_name': last_name,
            'name': f"{first_name} {last_name}".strip(),
            'member_type': 'joint' if '&' in names else 'individual',
            'email': default_email,
            'primary_phone': safe_get(row.get('HomePhone')),
            'secondary_phone': mobile,
            'res_address_line1': safe_get(row.get('Address')),
            'date_of_birth': parse_date(row.get('BirthDate')),
            'registration_date': parse_date(row.get('JoinDate')),
            'marital_status': safe_get(row.get('MaritalStatus'), 'single', to_lower=True),
            'next_of_kin_name': safe_get(row.get('NextOfKin')),
            'next_of_kin_phone': safe_get(row.get('NOKContact')),
            'activation_status': 'deactivated',
            'membership_status': 'inactive',
        }

        return {k: v for k, v in member_vals.items() if v is not None}
    

    def action_close_all_memberships(self):
        """Set membership status to 'closed' for all SACCO members."""
        Partner = self.env['res.partner'].with_context(tracking_disable=True)
        closed_count = Partner.search_count([('is_sacco_member', '=', True)])
        if closed_count > 0:
            Partner.search([('is_sacco_member', '=', True)]).write({'membership_status': 'closed', 'member_onboarded': True})
            _logger.info(f"Set {closed_count} SACCO member accounts to 'closed' status.")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Membership Status Updated'),
                    'message': _(f'Successfully set {closed_count} member accounts to "closed" status.'),
                    'sticky': True,
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Members Found'),
                    'message': _('No SACCO member accounts found to close.'),
                    'sticky': True,
                    'type': 'warning',
                }
            }
            
    def action_import_cleaned_members(self):
        """Import and update members from the uploaded Excel file with cleaned data."""
        if not self.file:
            raise UserError(_("Please upload an Excel file."))

        try:
            file_data = base64.b64decode(self.file)
            df = pd.read_excel(file_data, engine='openpyxl', dtype={'MemberId': str, 'User Name*': str})
            create_count, update_count, error_count = self._process_cleaned_members(df)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Cleaned Members Import Complete'),
                    'message': _(f'Added: {create_count}, Updated: {update_count}, Errors: {error_count}'),
                    'sticky': True,
                    'type': 'success' if error_count == 0 else 'warning',
                }
            }
        except Exception as e:
            error_logger.error(f"Failed to import cleaned members: {str(e)}")
            raise UserError(_(f"Failed to import cleaned members: {str(e)}"))

    def _process_cleaned_members(self, df):
        """Process cleaned members from Excel with update-or-create logic."""
        Partner = self.env['res.partner'].with_context(tracking_disable=True, bypass_constraints=True)
        create_count = 0
        update_count = 0
        error_count = 0
        email_counter = 1573  # Counter for unique default emails

        def safe_get(value, default=None, to_lower=False, to_string=False):
            if pd.isna(value):
                return default
            result = str(value) if to_string or isinstance(value, str) else value
            return result.lower() if isinstance(result, str) and to_lower else result

        def format_client_code(code):
            code_str = str(code).zfill(4)
            return code_str if len(code_str) == 4 else code_str

        def parse_date(date_str):
            if pd.isna(date_str):
                return None, None
            if isinstance(date_str, (int, float)):
                date_str = str(date_str)
            if isinstance(date_str, str):
                date_parts = date_str.split('&') if '&' in date_str else [date_str]
                if len(date_parts) > 1:
                    first_date = date_parts[0].strip()
                    second_date = date_parts[1].strip()
                else:
                    first_date = date_str.strip()
                    second_date = None

                date_formats = [
                    '%d/%m/%Y', '%b %d', '%d-%b', '%Y-%m-%d', '%d/%m/%y'
                ]
                first_date_obj = None
                second_date_obj = None
                for fmt in date_formats:
                    try:
                        first_date_obj = datetime.strptime(first_date, fmt).date()
                        if second_date:
                            second_date_obj = datetime.strptime(second_date, fmt).date()
                        break
                    except ValueError:
                        continue
                if not first_date_obj:
                    error_logger.warning(f"Unsupported date format: {date_str}")
                return first_date_obj, second_date_obj
            return None, None

        for index, row in df.iterrows():
            try:
                with self.env.cr.savepoint():
                    member_id = format_client_code(safe_get(row.get('MemberId'), to_string=True))
                    existing_member = Partner.search([('member_id', '=', member_id)], limit=1)
                    member_vals = self._prepare_cleaned_member_vals(row, email_counter)

                    if existing_member:
                        # Update existing member, skipping email if it already exists
                        try:
                            primary_email = member_vals.get('email')
                            if primary_email and Partner.search([('email', '=', primary_email), ('is_sacco_member', '=', True), ('id', '!=', existing_member.id)], limit=1):
                                _logger.info(f"Skipped email update for member {member_id} at index {index} due to existing email: {primary_email}")
                                member_vals.pop('email', None)  # Remove email from update if it exists
                                if 'secondary_email' in member_vals and Partner.search([('email', '=', member_vals.get('secondary_email')), ('is_sacco_member', '=', True), ('id', '!=', existing_member.id)], limit=1):
                                    member_vals.pop('secondary_email', None)  # Remove secondary email if it exists
                            existing_member.write(member_vals)
                            update_count += 1
                            _logger.info(f"Updated cleaned member: {member_id} at index {index}")
                        except Exception as e:
                            error_logger.error(f"Error updating member {member_id} at index {index}: {str(e)}")
                            error_count += 1
                    else:
                        # Check if email exists before creating
                        primary_email = member_vals.get('email')
                        if primary_email and Partner.search([('email', '=', primary_email), ('is_sacco_member', '=', True)], limit=1):
                            _logger.info(f"Skipped creation of cleaned member with MemberId: {member_id} at index {index} due to existing email: {primary_email}")
                            error_count += 1  # Increment error_count for skipped creations
                            continue
                        # Create new member if no email conflict
                        try:
                            Partner.create(member_vals)
                            create_count += 1
                            _logger.info(f"Created cleaned member: {member_id} at index {index}")
                        except Exception as e:
                            error_logger.error(f"Error creating member {member_id} at index {index}: {str(e)}")
                            error_count += 1

                    if member_vals.get('email', '').startswith('no-email'):
                        email_counter += 1  # Increment counter if default email was used
            except Exception as e:
                error_count += 1
                error_logger.error(f"Processing cleaned member {row.get('MemberId', 'Unknown')} at index {index}: {str(e)}")
                continue

        return create_count, update_count, error_count
            
    def _prepare_cleaned_member_vals(self, row, email_counter):
        """Prepare member values for cleaned Excel format."""
        def safe_get(value, default=None, to_lower=False, to_string=False):
            if pd.isna(value):
                return default
            result = str(value) if to_string or isinstance(value, str) else value
            return result.lower() if isinstance(result, str) and to_lower else result

        def parse_date(date_str):
            if pd.isna(date_str):
                return None, None
            if isinstance(date_str, (int, float)):
                date_str = str(date_str)
            if isinstance(date_str, str):
                date_parts = date_str.split('&') if '&' in date_str else [date_str]
                if len(date_parts) > 1:
                    first_date = date_parts[0].strip()
                    second_date = date_parts[1].strip()
                else:
                    first_date = date_str.strip()
                    second_date = None

                date_formats = [
                    '%d/%m/%Y', '%b %d', '%d-%b', '%Y-%m-%d', '%d/%m/%y'
                ]
                first_date_obj = None
                second_date_obj = None
                for fmt in date_formats:
                    try:
                        first_date_obj = datetime.strptime(first_date, fmt).date()
                        if second_date:
                            second_date_obj = datetime.strptime(second_date, fmt).date()
                        break
                    except ValueError:
                        continue
                if not first_date_obj:
                    error_logger.warning(f"Unsupported date format: {date_str}")
                return first_date_obj, second_date_obj
            return None, None

        # Handle multiple emails
        email_str = safe_get(row.get('Email*'))
        emails = email_str.split('&') if isinstance(email_str, str) and '&' in email_str else [email_str] if email_str else []
        primary_email = emails[0].strip() if emails else None
        secondary_email = emails[1].strip() if len(emails) > 1 else None

        # Handle multiple dates
        dob_first, dob_second = parse_date(row.get('Date of birth'))

        # Phone number logic
        phone_number = safe_get(row.get('Phone Number'))
        home_number = safe_get(row.get('Home Number'))
        work_number = safe_get(row.get('Work Number'))
        primary_phone = phone_number if phone_number else (home_number.split('/')[0].strip() if isinstance(home_number, str) and home_number else None)
        secondary_phone = work_number if work_number else (home_number.split('/')[1].strip() if isinstance(home_number, str) and '/' in home_number else None)

        # ID type and number
        id_number = safe_get(row.get('National ID'))
        id_type = 'nationalId' if id_number else None

        # Membership status logic
        membership_status = 'active'  # Default to active on successful update
        if primary_email in ['watoto', 'watoto & bbira']:
            membership_status = 'inactive'

        member_vals = {
            'is_sacco_member': True,
            'member_id': safe_get(row.get('MemberId'), to_string=True),
            'username': safe_get(row.get('User Name*'), to_string=True),
            'first_name': safe_get(row.get('Other Name')),
            'last_name': safe_get(row.get('Last Name')),
            'member_type': safe_get(row.get('Member Type'), to_lower=True),
            'email': primary_email if primary_email and re.match(r"[^@]+@[^@]+\.[^@]+", primary_email) else f'no-email{email_counter + 1}@example.com',
            'secondary_email': secondary_email if secondary_email and re.match(r"[^@]+@[^@]+\.[^@]+", secondary_email) else None,
            'primary_phone': primary_phone,
            'secondary_phone': secondary_phone,
            'closure_id': safe_get(row.get('Close number')),
            'celebration_point': safe_get(row.get('celebration Point')),
            'employment_status': safe_get(row.get('Employment status'), to_lower=True),
            'marital_status': safe_get(row.get('Marital status'), to_lower=True),
            'vat': safe_get(row.get('TIN'), to_string=True),
            'res_address_line1': safe_get(row.get('Residential Address')),
            'postal_address': safe_get(row.get('Postal Code')),
            'date_of_birth': dob_first,
            'secondary_date_of_birth': dob_second,
            'id_number': id_number,
            'id_type': id_type,
            'membership_status': membership_status,
            'activation_status': 'activated' if membership_status == 'active' else 'deactivated',
        }

        # Only increment email_counter if a default email is used
        if member_vals.get('email', '').startswith('no-email'):
            email_counter += 1

        return {k: v for k, v in member_vals.items() if v is not None}