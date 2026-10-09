from odoo import api, fields, models


class CrafProfileSection(models.Model):
    _name = "craf.profile.section"
    _description = "Profil kesimi"
    _order = "sequence, name"

    name = fields.Char("Kesim", required=True, help="Tur + seriya, masalan: T Бал, Z Эко, Коса 80мм")
    sequence = fields.Integer(default=10)
    profile_type = fields.Char("Tur", help="T, Z, L, Коса, Штапик ...")
    series = fields.Char("Seriya", help="Бал, Эко, Эконом, Термо, ALUSAM, CRAF ...")
    kg_per_m = fields.Float("Og'irlik, kg/m", digits=(10, 4), aggregator=None)
    perimeter_m = fields.Float(
        "Bo'yaladigan perimetr, m", digits=(10, 4), aggregator=None,
        help="1 metr profilning bo'yaladigan yuzasi (m2/m). Kukun bo'yoq sarfi uchun.")
    die_code = fields.Char("Matritsa")
    drawing = fields.Image("Kesim chizmasi", max_width=1024, max_height=1024)
    note = fields.Text("Izoh")
    active = fields.Boolean(default=True)
    product_tmpl_ids = fields.One2many("product.template", "craf_section_id", string="Mahsulotlar")
    product_count = fields.Integer("Mahsulotlar soni", compute="_compute_product_count")

    _name_uniq = models.Constraint("UNIQUE(name)", "Kesim nomi takrorlanmasligi kerak.")

    @api.depends("product_tmpl_ids")
    def _compute_product_count(self):
        for rec in self:
            rec.product_count = len(rec.product_tmpl_ids)

    def action_open_products(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": "product.template",
            "view_mode": "list,form",
            "domain": [("craf_section_id", "=", self.id)],
            "context": {"default_craf_section_id": self.id},
        }
