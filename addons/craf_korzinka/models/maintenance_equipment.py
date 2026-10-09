from odoo import fields, models


class MaintenanceEquipment(models.Model):
    _inherit = "maintenance.equipment"

    craf_stage = fields.Selection(selection_add=[("chem", "Kimyoviy ishlov")], ondelete={"chem": "set null"})
