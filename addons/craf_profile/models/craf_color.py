from odoo import fields, models


class CrafColor(models.Model):
    _name = "craf.color"
    _description = "Profil rangi"
    _order = "sequence, name"

    name = fields.Char("Rang", required=True)
    code = fields.Char("Kod", help="RAL yoki ishlab chiqaruvchi kodi: 9016, J306, 7016 ...")
    sequence = fields.Integer(default=10)
    is_painted = fields.Boolean("Bo'yalgan", default=True)
    paint_tmpl_id = fields.Many2one(
        "product.template", string="Kukun bo'yoq",
        help="Shu rang uchun ishlatiladigan bo'yoq (xom-ashyo).")
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint("UNIQUE(name)", "Rang nomi takrorlanmasligi kerak.")
