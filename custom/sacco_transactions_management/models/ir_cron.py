from odoo import models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class IrCron(models.Model):
    _inherit = 'ir.cron'

    def run_manually(self):
        """Manually execute the cron job."""
        self.ensure_one()  # Ensure we're working with a single record
        try:
            if not self.active:
                raise UserError(_("Cannot run an inactive cron job. Please activate it first."))
            
            # Call the cron job's method
            self.method_direct_trigger()
            _logger.info("Cron job '%s' (ID: %d) executed manually.", self.name, self.id)
        except Exception as e:
            _logger.error("Error executing cron job '%s' (ID: %d) manually: %s", self.name, self.id, str(e))
            raise UserError(_("Failed to execute cron job manually: %s") % str(e))