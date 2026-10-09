from odoo import fields, models

CRAF_STAGES = [("foundry", "Литейка"), ("press", "Press"), ("paint", "Bo'yash")]


class MaintenanceEquipment(models.Model):
    _inherit = "maintenance.equipment"

    craf_stage = fields.Selection(CRAF_STAGES, string="Craf bosqichi", index=True)
