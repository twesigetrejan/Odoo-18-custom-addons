from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

# BASE_URL = "http://192.168.100.60:8090/gateway" # test
BASE_URL = "https://www.saccowave.com/gateway" # production
USERNAME = ""
PASSWORD = ""
LOGIN_ENDPOINT = "api/v1/user/login"


# SHARES ENDPOINTS
GET_SHARES_PRODUCTS_COLLECTION_ENDPOINT = "api/v1/data/shares_products"
GET_FILTERED_SHARES_PRODUCTS_COLLECTION_ENDPOINT = "api/v1/data/filter/shares_products?search=true"
GET_SHARES_DEPOSITS_COLLECTION_ENDPOINT = "api/v1/data/shares_deposits"
UPDATE_DEPOSIT_DETAILS_COLLECTION_ENDPOINT = "api/v1/data/update/deposit_details"
GET_APPROVED_SHARES_DEPOSITS_COLLECTION_ENDPOINT = "api/v1/data/filter/shares_deposits?search=true"

# SHARES STATEMENT UPLOAD ENDPOINTS
CREATE_SHARES_STATEMENT_COLLECTION_ENDPOINT = "api/v1/data/create/statements"
UPDATE_SHARES_STATEMENT_COLLECTION_ENDPOINT = "api/v1/data/update/statements"
GET_SHARES_STATEMENT_COLLECTION_ENDPOINT = "api/v1/data/statements"

# WITHDRAWAL REQUESTS
GET_WITHDRAWAL_REQUESTS_ENDPOINT = "api/v1/data/withdraw_request"
GET_APPROVED_WITHDRAWAL_REQUESTS_ENDPOINT = "api/v1/data/filter/withdraw_request?search=true"


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