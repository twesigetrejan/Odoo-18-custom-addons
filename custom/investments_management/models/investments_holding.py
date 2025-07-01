from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

class InvestmentHolding(models.Model):
    _name = 'sacco.investments.holding'
    _description = 'Investment Holding'
    
    account_id = fields.Many2one('sacco.investments.account', string='Investment Account', required=True)
    asset_type = fields.Selection([
        ('stock', 'Stocks'),
        ('bond', 'Bonds'),
        ('mutual_fund', 'Mutual Funds'),
        ('other', 'Other')
    ], string='Asset Type', required=True)
    name = fields.Char('Investment Name', required=True)
    quantity = fields.Float('Quantity/Units')
    purchase_date = fields.Date('Purchase Date', required=True)
    cost_basis = fields.Float('Cost Basis', required=True, 
                            help="Original amount invested in this asset")
    current_value = fields.Float('Current Market Value',
                               help="Current value of the investment based on market price")
    unrealized_gain = fields.Float(compute='_compute_unrealized_gain', store=True,
                                 help="Current profit or loss on this investment")
    
    @api.depends('current_value', 'cost_basis')
    def _compute_unrealized_gain(self):
        for holding in self:
            holding.unrealized_gain = holding.current_value - holding.cost_basis