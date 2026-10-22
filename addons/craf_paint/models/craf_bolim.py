from odoo import fields, models


class CrafBolim(models.Model):
    _inherit = "craf.bolim"

    defect_max_pct = fields.Float(
        "Brak chegarasi, %", default=1.5, digits=(16, 1),
        help="Bo'yash: smenada brak shundan ko'p bo'lsa, «normadan tashqari» deb belgilanadi va mas'ullarga "
             "eslatma boradi.")
    powder_tolerance = fields.Float(
        "Kukun ortiqcha sarfi chegarasi, %", default=10.0, digits=(16, 1),
        help="Bo'yash: kukun sarfi normadan shuncha foizdan ko'p bo'lsa, «normadan tashqari» deb belgilanadi.")
