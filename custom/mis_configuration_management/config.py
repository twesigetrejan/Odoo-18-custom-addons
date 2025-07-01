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

# TRANSACTIONS ENDPOINTS
GET_TRANSACTIONS_COLLECTION_ENDPOINT = "api/v1/data/transactions"
GET_FILTERED_TRANSACTIONS_COLLECTION_ENDPOINT = "api/v1/data/filter/transactions?search=true"

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