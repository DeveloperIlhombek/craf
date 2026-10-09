from odoo import api, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

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
