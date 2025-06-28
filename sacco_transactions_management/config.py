from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

BASE_URL = "https://www.saccowave.com/gateway"
USERNAME = ""
PASSWORD = ""
LOGIN_ENDPOINT = "api/v1/user/login"


# GENERAL STATEMENT UPLOAD ENDPOINTS
CREATE_GENERAL_STATEMENT_COLLECTION_ENDPOINT = "api/v1/data/create/statements"
UPDATE_GENERAL_STATEMENT_COLLECTION_ENDPOINT = "api/v1/data/update/statements"
GET_GENERAL_STATEMENT_COLLECTION_ENDPOINT = "api/v1/data/statements"
CREATE_UPDATE_GENERAL_STATEMENT_COLLECTION_ENDPOINT="api/v1/data/createOrUpdate/statements"


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
    
    # Validate configuration
    missing_fields = [k for k, v in config_values.items() if not v]
    if missing_fields:
        raise UserError(f"Missing configuration fields: {', '.join(missing_fields)}")
    
    return config_values