from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

BASE_URL = "https://www.saccowave.com/gateway"
USERNAME = ""
PASSWORD = ""
LOGIN_ENDPOINT = "api/v1/user/login"

# FILE ENDPOINTS
UPLOAD_FILE_ENDPOINT = "api/v1/data/upload-file"
DOWNLOAD_FILE_ENDPOINT = "api/v1/data/files"

# SAVINGS PRODUCT ENDPOINTS
GET_SACCO_PRODUCTS_COLLECTION_ENDPOINT = "api/v1/data/sacco_products"
GET_FILTERED_SAVINGS_PRODUCTS_COLLECTION_ENDPOINT = "api/v1/data/filter/sacco_products?search=true"
CREATE_UPDATE_SACCO_PRODUCTS_COLLECTION_ENDPOINT = "api/v1/data/createOrUpdate/sacco_products"

# SAVINGS ENDPOINTS
GET_SAVINGS_DEPOSITS_COLLECTION_ENDPOINT = "api/v1/data/savings_deposits"
UPDATE_DEPOSIT_DETAILS_COLLECTION_ENDPOINT = "api/v1/data/update/deposit_details"
GET_APPROVED_SAVINGS_DEPOSITS_COLLECTION_ENDPOINT = "api/v1/data/filter/savings_deposits?search=true"

# SAVINGS STATEMENT UPLOAD ENDPOINTS
CREATE_SAVINGS_STATEMENT_COLLECTION_ENDPOINT = "api/v1/data/create/statements"
UPDATE_SAVINGS_STATEMENT_COLLECTION_ENDPOINT = "api/v1/data/update/statements"
GET_SAVINGS_STATEMENT_COLLECTION_ENDPOINT = "api/v1/data/statements"
CREATE_UPDATE_SAVINGS_STATEMENT_COLLECTION_ENDPOINT="api/v1/data/createOrUpdate/statements"

# WITHDRAWAL REQUESTS
GET_WITHDRAWAL_REQUESTS_ENDPOINT = "api/v1/data/withdraw_request"
GET_PENDING_WITHDRAWAL_REQUESTS_ENDPOINT = "api/v1/data/filter/withdraw_request?search=true"
UPDATE_WITHDRAWAL_REQUESTS_ENDPOINT = "api/v1/data/update/withdraw_request"


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