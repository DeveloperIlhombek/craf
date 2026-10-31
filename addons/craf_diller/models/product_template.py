from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    craf_price_date = fields.Datetime("Narx o'zgargan vaqt", copy=False, readonly=True)

    def write(self, vals):
        if "list_price" in vals:
            changed = self.filtered(lambda t: abs(t.list_price - float(vals["list_price"] or 0.0)) > 0.5)
            if changed:
                super(ProductTemplate, changed).write({"craf_price_date": fields.Datetime.now()})
        return super().write(vals)
