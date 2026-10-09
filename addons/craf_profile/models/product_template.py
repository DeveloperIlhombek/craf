import math

from odoo import api, fields, models

EPS = 1e-9


class ProductTemplate(models.Model):
    _inherit = "product.template"

    craf_section_id = fields.Many2one("craf.profile.section", string="Kesim", index=True)
    craf_color_id = fields.Many2one("craf.color", string="Rang", index=True)
    craf_length_m = fields.Float("Uzunlik, m", digits=(10, 3), aggregator=None)
    craf_pcs_per_pack = fields.Integer("Dona / pachka", aggregator=None)
    craf_name_1c = fields.Char("1C dagi nomi")
    craf_kg_per_m = fields.Float(related="craf_section_id.kg_per_m", string="Og'irlik, kg/m", readonly=True, aggregator=None)
    craf_kg_per_pc = fields.Float(
        "1 dona, kg", digits=(10, 3), compute="_compute_craf_weights", store=True, aggregator=None)
    craf_kg_per_pack = fields.Float(
        "1 pachka, kg", digits=(10, 3), compute="_compute_craf_weights", store=True, aggregator=None)
    craf_stock_text = fields.Char("Qoldiq (pachka)", compute="_compute_craf_stock")
    craf_free_text = fields.Char("Erkin (pachka)", compute="_compute_craf_stock")
    craf_stock_kg = fields.Float("Qoldiq, kg", digits=(16, 1), compute="_compute_craf_stock")

    @api.depends("craf_section_id.kg_per_m", "craf_length_m", "craf_pcs_per_pack")
    def _compute_craf_weights(self):
        for tmpl in self:
            per_pc = (tmpl.craf_section_id.kg_per_m or 0.0) * (tmpl.craf_length_m or 0.0)
            tmpl.craf_kg_per_pc = per_pc
            tmpl.craf_kg_per_pack = per_pc * (tmpl.craf_pcs_per_pack or 0)

    @api.model
    def _craf_packs_text(self, pcs, per_pack):
        pcs = int(math.floor((pcs or 0.0) + EPS))
        if not per_pack:
            return "%s dona" % pcs
        packs, rest = divmod(pcs, per_pack)
        return "%s pachka + %s dona" % (packs, rest) if rest else "%s pachka" % packs

    @api.depends("craf_pcs_per_pack", "craf_kg_per_pc")
    @api.depends_context("company", "warehouse_id", "location")
    def _compute_craf_stock(self):
        for tmpl in self:
            on_hand = tmpl.qty_available
            free = sum(tmpl.product_variant_ids.mapped("free_qty"))
            tmpl.craf_stock_text = self._craf_packs_text(on_hand, tmpl.craf_pcs_per_pack)
            tmpl.craf_free_text = self._craf_packs_text(free, tmpl.craf_pcs_per_pack)
            tmpl.craf_stock_kg = on_hand * (tmpl.craf_kg_per_pc or 0.0)

    def action_craf_calculator(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("craf_profile.action_craf_calculator")
        action["context"] = {"default_product_id": self.product_variant_id.id}
        return action
