from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    craf_pack_count = fields.Integer("Pachkalar", compute="_compute_craf_pack_count")

    def _compute_craf_pack_count(self):
        data = self.env["craf.pack"]._read_group(
            [("product_tmpl_id", "in", self.ids)], ["product_tmpl_id"], ["__count"])
        counts = {tmpl.id: count for tmpl, count in data}
        for tmpl in self:
            tmpl.craf_pack_count = counts.get(tmpl.id, 0)

    def action_craf_pack_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Pachka yorlig'i",
            "res_model": "craf.pack.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_product_id": self.product_variant_id.id},
        }

    def action_craf_view_packs(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("craf_label.action_craf_pack")
        action["domain"] = [("product_tmpl_id", "=", self.id)]
        action["context"] = {"default_product_id": self.product_variant_id.id}
        return action
