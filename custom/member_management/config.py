from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

# Default configuration values
BASE_URL = "https://www.saccowave.com/gateway"  # production
USERNAME = ""
PASSWORD = ""
LOGIN_ENDPOINT = "api/v1/user/login"

# FILE ENDPOINTS
UPLOAD_FILE_ENDPOINT = "api/v1/data/upload-file"
DOWNLOAD_FILE_ENDPOINT = "api/v1/data/files"

CREATE_MEMBERS_COLLECTION_ENDPOINT = "api/v1/data/create/sacco_members"
CREATE_UPDATE_MEMBERS_COLLECTION_ENDPOINT = "api/v1/data/createOrUpdate/sacco_members"
GET_MEMBERS_COLLECTION_ENDPOINT = "api/v1/data/sacco_members"
GET_FILTERED_MEMBERS_COLLECTION_ENDPOINT = "api/v1/data/filter/sacco_members?search=true"
GET_FILTERED_MEMBERS_APPLICATION_ENDPOINT = "api/v1/data/filter/member_application?search=true"
UPDATE_MEMBERS_COLLECTION_ENDPOINT = "api/v1/data/update/sacco_members"

def get_config(env):
    """
    Get configuration values with database overrides if available.
    Falls back to default values if not configured in database.
    
    Args:
        env: Odoo environment object
    
    Returns:
        dict: Configuration values
    """
    config_values = {
        'BASE_URL': BASE_URL,
        'USERNAME': USERNAME,
        'PASSWORD': PASSWORD,
        'LOGIN_ENDPOINT': LOGIN_ENDPOINT,
    }
    
    try:
        db_config = env['omni.mis.configure'].search([], limit=1)
        if db_config:
            config_values['BASE_URL'] = (
                str(db_config.mis_base_url).rstrip('/') if isinstance(db_config.mis_base_url, str) else BASE_URL
            )
            config_values['USERNAME'] = (
                str(db_config.admin_username) if isinstance(db_config.admin_username, str) else USERNAME
            )
            config_values['PASSWORD'] = (
                str(db_config.account_password) if isinstance(db_config.account_password, str) else PASSWORD
            )
    except Exception as e:
        _logger.error(f"Error fetching configuration: {str(e)}")
    
    return config_values