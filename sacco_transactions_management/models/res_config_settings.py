from odoo import fields, models
import logging

_logger = logging.getLogger(__name__)

_logger.info("Loading ResConfigSettings class in res_config_settings.py")

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cron_ids = fields.Many2many(
        comodel_name='ir.cron',
        string='Scheduled Jobs',
        compute='_compute_cron_ids',
        store=False,
    )

    def _compute_cron_ids(self):
        _logger.info("Entering _compute_cron_ids method")
        # List of models from the specified modules
        model_names = [
            'general.member.statement.wizard',
            'member.sync',
            'sacco.savings.deposit.sync',
            'sacco.savings.product.sync',
            'sacco.withdrawal.request',
            'sacco.savings.account',
            'sacco.interest.posting',
            'sacco.shares.account',
            'sacco.transaction.sync',
            'sacco.investments.deposit.sync',
            'sacco.investments.product.sync',
            'sacco.investments.account',
            'sacco.loan.installment',
            'loan.payment.sync',
            'sacco.loan.product.sync',
            'sacco.loan.application',
            'sacco.loan.loan',
        ]

        for record in self:
            try:
                # Step 1: Find server actions used by cron jobs
                cron_server_actions = self.env['ir.actions.server'].search([
                    ('usage', '=', 'ir_cron'),
                    ('model_name', 'in', model_names)
                ])
                
                _logger.info("Found %d server actions with usage='ir_cron' and model_name in %s", len(cron_server_actions), model_names)

                if not cron_server_actions:
                    _logger.warning("No server actions found with usage='ir_cron' and model_name in %s", model_names)
                    record.cron_ids = False
                    continue

                _logger.info("Server actions found: %s", cron_server_actions.mapped('name'))

                # Step 2: Get the IDs of these server actions
                server_action_ids = cron_server_actions.mapped('id')

                # Step 3: Find cron jobs linked to these server actions
                cron_jobs = self.env['ir.cron'].search([
                    ('ir_actions_server_id', 'in', server_action_ids)
                ])

                if not cron_jobs:
                    _logger.warning("No cron jobs found linked to server actions with IDs: %s", server_action_ids)
                    record.cron_ids = False
                    continue

                _logger.info("Cron jobs found: %s", cron_jobs.mapped('name'))
                record.cron_ids = cron_jobs

            except Exception as e:
                _logger.error("Error fetching cron jobs: %s", str(e))
                record.cron_ids = False