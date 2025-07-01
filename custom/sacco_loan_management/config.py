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

# ODOO INSTANCE REGISTRATION
ODOO_REGISTRATION_ENDPOINT = "api/v1/odoo/register/odoo-instances"


# LOAN APPLICATION ENDPOINTS
LOAN_APPLICATION_COLLECTION_ENDPOINT = "api/v1/data/loan_application"
GET_APPROVED_LOAN_APPLICATIONS_ENDPOINT = "api/v1/data/filter/loan_application?search=true&withChildren=true"
UPDATE_LOAN_APPLICATION_COLLECTION_ENDPOINT = "api/v1/data/update/loan_application"

# LOAN PRODUCT ENDPOINTS
SACCO_LOANS_COLLECTION_ENDPOINT = "api/v1/data/create/sacco_loans"
GET_LOAN_PRODUCTS_COLLECTION_ENDPOINT = "api/v1/data/loan_products"
CREATE_UPDATE_SACCO_PRODUCTS_COLLECTION_ENDPOINT = "api/v1/data/createOrUpdate/sacco_products"

# LOAN PAYMENTS COLLECTION ENDPOINTS
SACCO_LOANS_PAYMENTS_COLLECTION_ENDPOINT = "api/v1/data/loan_payments"
SACCO_LOANS_PAYMENTS_SYNC_ENDPOINT = "api/v1/odoo/send/payments/to-odoo"
UPDATE_LOANS_PAYMENTS_COLLECTION_ENDPOINT = "api/v1/data/update/loan_payments"

# LOAN STATEMENT UPLOAD ENDPOINTS
CREATE_LOAN_STATEMENT_COLLECTION_ENDPOINT = "api/v1/data/create/loan_statements"
UPDATE_LOAN_STATEMENT_COLLECTION_ENDPOINT = "api/v1/data/update/loan_statements"
GET_LOAN_STATEMENT_COLLECTION_ENDPOINT = "api/v1/data/loan_statements"
CREATE_UPDATE_LOANS_STATEMENT_COLLECTION_ENDPOINT = "api/v1/data/createOrUpdate/statements"

# LOAN ATTACHMENTS
CREATE_UPDATE_LOAN_ATTACHMENTS_COLLECTION_ENDPOINT = "api/v1/data/createOrUpdate/loan_attachments"

# NOTIFICATIONS COLLECTION
CREATE_NOTIFICATIONS_COLLECTION_ENDPOINT = "api/v1/data/create/notifications"

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