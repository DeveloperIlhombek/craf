from odoo import models


class CrafProductionMixin(models.AbstractModel):
    _inherit = "craf.production.mixin"

    def _craf_mrp_picking_type(self, dest):
        norm = self.env["craf.mrp.norm"]._get_norm(self.company_id)
        if self._craf_stage == "foundry":
            return norm.foundry_type_id
        if self._craf_stage == "press":
            pack = self._craf_loc("Qadoqlash")
            return norm.press_pack_type_id if pack and dest == pack else norm.press_type_id
        if self._craf_stage == "paint":
            return norm.paint_type_id
        return self.env["stock.picking.type"]

    def _craf_produce(self, product, qty, src, dest, components, byproducts=None):
        picking_type = self._craf_mrp_picking_type(dest)
        rec = self.with_context(craf_picking_type_id=picking_type.id) if picking_type else self
        return super(CrafProductionMixin, rec)._craf_produce(product, qty, src, dest, components, byproducts)
