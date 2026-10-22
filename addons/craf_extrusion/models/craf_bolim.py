from odoo import fields, models


class CrafBolim(models.Model):
    _inherit = "craf.bolim"

    norm_tolerance = fields.Float(
        "Normadan chetlanish, %", default=2.0, digits=(16, 1),
        help="Press: chiqish % normadan shuncha foiz punkt, unumdorlik normadan shuncha foiz past bo'lsa, "
             "smena «normadan past» deb belgilanadi va mas'ullarga eslatma boradi.")
