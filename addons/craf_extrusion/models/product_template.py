from odoo import api, fields, models

from odoo.addons.craf_production.models.craf_production_mixin import FORECAST_STATUS


class ProductTemplate(models.Model):
    _inherit = "product.template"

    craf_press_waste = fields.Boolean(
        "Press chiqindisi", help="Питак, brak profil, briket — press bo'limida chiqadi, sotib olinmaydi "
                                 "(Литейка kirimida ko'rinmaydi).")
    craf_butt_product_id = fields.Many2one(
        "product.product", string="Питак (shu quymadan)",
        help="Quyma (stalba) uchun: press kesgan qoldiq qaysi mahsulotga yoziladi. "
             "Masalan, o'z stalbamiz → Питак (вторичка), RusAl → Питак (русал).")

    # Quyma prognozi (Press → Quyma qoldig'i va prognoz). craf_min_qty asli craf_hisobot da — bu modul undan
    # oldin o'rnatiladi, shuning uchun shu yerda ham (bir xil) e'lon qilingan.
    craf_min_qty = fields.Float("Minimal qoldiq", digits=(16, 1),
                                help="Qoldiq shundan kamaysa, kunlik hisobotda va panelda ogohlantiriladi.")
    craf_press_qty = fields.Float("Zavodda, kg", compute="_compute_craf_press_forecast", digits=(16, 1))
    craf_press_in_press = fields.Float("Press sexida, kg", compute="_compute_craf_press_forecast", digits=(16, 1))
    craf_press_used = fields.Float("Press sarfi (davr), kg", compute="_compute_craf_press_forecast", digits=(16, 1))
    craf_press_period = fields.Integer("Davr, kun", compute="_compute_craf_press_forecast")
    craf_press_avg = fields.Float("O'rtacha kunlik sarf, kg", compute="_compute_craf_press_forecast",
                                  digits=(16, 1))
    craf_press_days_left = fields.Float("Necha kunga yetadi", compute="_compute_craf_press_forecast",
                                        digits=(16, 1))
    craf_press_days_text = fields.Char("Yetadi", compute="_compute_craf_press_forecast")
    craf_press_end_date = fields.Date("Tugash sanasi", compute="_compute_craf_press_forecast")
    craf_press_status = fields.Selection(FORECAST_STATUS, string="Holat", compute="_compute_craf_press_forecast")

    def _compute_craf_press_forecast(self):
        Shift = self.env["craf.extrusion.shift"]
        rows = Shift._craf_billet_forecast(self.product_variant_ids)
        for tmpl in self:
            r = rows.get(tmpl.product_variant_id.id)
            days = r["days_left"] if r else None
            tmpl.craf_press_qty = r["qty"] if r else 0.0
            tmpl.craf_press_in_press = r["in_press"] if r else 0.0
            tmpl.craf_press_used = r["used"] if r else 0.0
            tmpl.craf_press_period = r["period"] if r else 0
            tmpl.craf_press_avg = r["avg"] if r else 0.0
            tmpl.craf_press_days_left = days or 0.0
            tmpl.craf_press_days_text = Shift._craf_days_text(days)
            tmpl.craf_press_end_date = r["end_date"] if days is not None and days <= 365 else False
            tmpl.craf_press_status = r["status"] if r else False

    @api.model
    def _craf_raw_color(self):
        color = self.env.ref("craf_nomenklatura.color_raw", raise_if_not_found=False)
        return color or self.env["craf.color"].search([("is_painted", "=", False)], limit=1)

    def _craf_semi_product(self, create=True):
        """Bo'yalgan profil uchun bo'yalmagan yarim tayyor mahsulot (shu kesim, shu uzunlik)."""
        self.ensure_one()
        raw = self._craf_raw_color()
        if not self.craf_section_id or not raw:
            return self.env["product.product"]
        semi = self.search([
            ("craf_section_id", "=", self.craf_section_id.id),
            ("craf_length_m", "=", self.craf_length_m),
            ("craf_color_id", "=", raw.id),
        ], limit=1)
        if semi or not create:
            return semi.product_variant_id
        categ = self.env.ref("craf_extrusion.categ_semi_profile", raise_if_not_found=False)
        code = False
        if self.default_code and self.default_code.count("-") >= 2:
            code = "%s-XOM-%s" % (self.default_code.rsplit("-", 2)[0], "%g" % self.craf_length_m)
        name = "%s ( не крашенные )" % self.craf_section_id.name
        if self.craf_length_m and abs(self.craf_length_m - 6.0) > 1e-6:
            name += " %gмт" % self.craf_length_m
        semi = self.create({
            "name": name,
            "default_code": code,
            "type": "consu",
            "is_storable": True,
            "categ_id": categ.id if categ else self.categ_id.id,
            "uom_id": self.uom_id.id,
            "sale_ok": False,
            "purchase_ok": False,
            "craf_section_id": self.craf_section_id.id,
            "craf_color_id": raw.id,
            "craf_length_m": self.craf_length_m,
            "craf_pcs_per_pack": self.craf_pcs_per_pack,
        })
        return semi.product_variant_id

    @api.model
    def _craf_ensure_semi_products(self):
        painted = self.search([("craf_section_id", "!=", False), ("craf_color_id.is_painted", "=", True)])
        for tmpl in painted:
            tmpl._craf_semi_product()
        return True
