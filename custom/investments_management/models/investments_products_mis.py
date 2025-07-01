from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import requests
import logging
import time
import random
import binascii
from ..config import (get_config, CREATE_UPDATE_SACCO_PRODUCTS_COLLECTION_ENDPOINT)

_logger = logging.getLogger(__name__)

class InvestmentsProductMIS(models.Model):
    _name = 'sacco.investments.product.mis'
    _description = 'SACCO Investments Product MIS Integration'
    _inherit = ['api.token.mixin']

    product_id = fields.Many2one(
        'sacco.investments.product',
        string='Investments Product',
        required=True,
        ondelete='cascade'
    )
    last_sync_date = fields.Date(
        string='Last Sync Date',
        readonly=True,
        help='Tracks the last time this product was synced with the external system'
    )
    mongo_db_id = fields.Char(
        string='Mongo DB ID',
        readonly=True,
        copy=False
    )

    def _generate_mongo_like_id(self):
        """Generate a 24-character hexadecimal string similar to MongoDB ObjectId"""
        timestamp = int(time.time()).to_bytes(4, byteorder='big')
        random_bytes = random.randbytes(5)
        counter = random.randint(0, 0xFFFFFF).to_bytes(3, byteorder='big')
        object_id = binascii.hexlify(timestamp + random_bytes + counter).decode('utf-8')
        return object_id

    def _prepare_product_data(self, product):
        """Prepare product data for API submission"""
        return {
            "productType": "Investment",
            "productName": product.name,
            "productDescription": product.description or "",
            "productCode": product.product_code or "",
            "minimumBalance": product.minimum_balance or 0.0,
        }

    def _post_or_update_product(self, product, token):
        """Post or update a single product to the external system"""
        headers = self._get_request_headers()
        config = get_config(self.env)
        
        # Check if MIS record exists for this product
        mis_record = self.search([('product_id', '=', product.id)], limit=1)
        if not mis_record:
            mis_record = self.create({
                'product_id': product.id,
                'mongo_db_id': self._generate_mongo_like_id()
            })
            _logger.info(f"Created new MIS record for investment product {product.name}: {mis_record.mongo_db_id}")
        
        mongo_id = mis_record.mongo_db_id
        api_url = f"{config['BASE_URL']}/{CREATE_UPDATE_SACCO_PRODUCTS_COLLECTION_ENDPOINT}/{mongo_id}".rstrip('/')
        product_data = self._prepare_product_data(product)
        
        try:
            _logger.info(f"Posting/Updating investment product to {api_url}: {product_data}")
            response = requests.post(api_url, headers=headers, json=product_data)
            response.raise_for_status()
            
            response_data = response.json()
            if response_data and 'docId' in response_data:
                new_mongo_id = response_data['docId']
                if new_mongo_id != mongo_id:
                    mis_record.write({'mongo_db_id': new_mongo_id})
                    _logger.info(f"Updated mongo_db_id for investment product {product.name} to {new_mongo_id}")
                    
            mis_record.write({'last_sync_date': fields.Date.today()})
            return True
        except requests.RequestException as e:
            _logger.error(f"Failed to post/update investment product {product.name}: {str(e)}")
            return False

    def action_mass_sync_products(self, product_records):
        """Mass action to sync selected investment products"""
        if not product_records:
            raise ValidationError(_("No products selected for synchronization."))
        
        _logger.info(f"Starting mass product sync for {len(product_records)} investment products")
        
        token = self._get_authentication_token()
        if not token:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sync Error'),
                    'message': _('Failed to connect to external system'),
                    'type': 'danger',
                    'sticky': True,
                }
            }

        success_count = 0
        for product in product_records:
            try:
                if self._post_or_update_product(product, token):
                    success_count += 1
                    self.env.cr.commit()
                    _logger.info(f"Successfully synced investment product {product.name}")
                else:
                    _logger.warning(f"Failed to sync investment product {product.name}")
            except Exception as e:
                self.env.cr.rollback()
                _logger.error(f"Error syncing investment product {product.name}: {str(e)}")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Product Sync'),
                'message': _('%d products processed successfully out of %d') % (success_count, len(product_records)),
                'type': 'success' if success_count > 0 else 'warning',
                'sticky': False,
            }
        }

    @api.model
    def sync_all_products(self):
        """Sync all investment products in batches"""
        _logger.info("Starting sync of all investment products")
        
        product_model = self.env['sacco.investments.product']
        BATCH_SIZE = 500
        offset = 0
        total_products = product_model.search_count([])
        
        while offset < total_products:
            products = product_model.search([], offset=offset, limit=BATCH_SIZE)
            self.action_mass_sync_products(products)
            offset += len(products)
        
        _logger.info("Completed sync of all investment products")