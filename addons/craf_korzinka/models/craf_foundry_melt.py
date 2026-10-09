from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt


class CrafFoundryMelt(models.Model):
    _inherit = "craf.foundry.melt"

    billet_qty = fields.Float(string="Stalba chiqdi, kg")
    cut_waste_qty = fields.Float("Kesilgan chiqindi (stalba), kg", digits=(16, 1), aggregator="sum",
                                 help="Stalbani kesishda chiqqan keraksiz qism (Сталба отход)")
    cut_waste_product_id = fields.Many2one(
        "product.product", string="Stalba chiqindisi (mahsulot)", default=lambda self: self._craf_product("PF-12"))

    @api.depends("line_ids.qty", "line_ids.is_metal", "billet_qty", "slag_qty", "cut_waste_qty")
    def _compute_kpi(self):
        super()._compute_kpi()
        for melt in self:
            if melt.billet_qty and melt.cut_waste_qty:
                metal = melt.charge_metal
                loss = metal - melt.billet_qty - melt.slag_qty - melt.cut_waste_qty
                melt.burn_loss_qty = loss
                melt.burn_loss_pct = loss / metal * 100.0 if metal else 0.0

    @api.depends("charge_metal", "billet_qty", "slag_qty", "burn_loss_qty", "cut_waste_qty")
    def _compute_balance_text(self):
        super()._compute_balance_text()
        for melt in self.filtered(lambda m: m.charge_metal and m.cut_waste_qty):
            melt.balance_text = "%s kg metall = %s stalba + %s kesilgan chiqindi + %s шлак + %s угар" % (
                fmt(melt.charge_metal), fmt(melt.billet_qty), fmt(melt.cut_waste_qty), fmt(melt.slag_qty),
                fmt(melt.burn_loss_qty, 1))

    def _craf_action_done(self):
        self.ensure_one()
        total = self.billet_qty + self.slag_qty + self.cut_waste_qty
        if self.cut_waste_qty > EPS and total > self.charge_metal + EPS:
            raise UserError("Stalba + kesilgan chiqindi + шлак (%s kg) metall shixtadan (%s kg) ko'p bo'lishi "
                            "mumkin emas." % (fmt(total, 1), fmt(self.charge_metal, 1)))
        if self.cut_waste_qty > EPS and not self.cut_waste_product_id:
            raise UserError("Stalba chiqindisi mahsulotini tanlang.")
        return super(CrafFoundryMelt, self.with_context(craf_melt_cut_waste=True))._craf_action_done()

    def _craf_produce(self, product, qty, src, dest, components, byproducts=None):
        if self.env.context.get("craf_melt_cut_waste") and self.cut_waste_qty > EPS:
            byproducts = list(byproducts or []) + [
                (self.cut_waste_product_id, self.cut_waste_qty, self.waste_location_id)]
        return super()._craf_produce(product, qty, src, dest, components, byproducts)
