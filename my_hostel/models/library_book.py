from odoo import models, fields

class BaseArchive(models.AbstractModel):
    _name = 'base.archive'
    active = fields.Boolean(default=True)
    _description = 'Abstract Archive Model'
    
    def do_archive(self):
        """Archive the record by setting active to False."""
        for record in self:
            record.active = not record.active
