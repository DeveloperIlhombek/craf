from odoo import Command, api, fields, models
from odoo.exceptions import UserError


class CrafExtrusionShift(models.Model):
    _inherit = "craf.extrusion.shift"

    basket_load_ids = fields.One2many("craf.basket.load", "shift_id", string="Korzinkalar", copy=False)
    basket_count = fields.Integer("Korzinkalar soni", compute="_compute_basket_totals", store=True,
                                  aggregator="sum")
    basket_pcs = fields.Integer("Korzinkalarda, dona", compute="_compute_basket_totals", store=True,
                                aggregator="sum")
    basket_kg = fields.Float("Korzinkalarda, kg", compute="_compute_basket_totals", store=True,
                             digits=(16, 1), aggregator="sum")

    @api.depends("basket_load_ids.pcs_total", "basket_load_ids.kg_theory", "basket_load_ids.net_kg")
    def _compute_basket_totals(self):
        for shift in self:
            loads = shift.basket_load_ids
            shift.basket_count = len(loads)
            shift.basket_pcs = sum(loads.mapped("pcs_total"))
            shift.basket_kg = sum(l.net_kg or l.kg_theory for l in loads)

    def _craf_sync_lines_from_baskets(self):
        """Korzinkalardagi profillarni chiqish qatorlariga yig'adi (boshqa qatorlarga tegmaydi)."""
        for shift in self:
            quantities = shift.basket_load_ids._product_quantities()
            if not quantities:
                continue
            kimyo = shift._craf_loc("Kimyoviy ishlov")
            commands = [Command.unlink(l.id) for l in shift.line_ids if l.product_id in quantities]
            for product, qty in quantities.items():
                vals = {"product_id": product.id, "pcs": qty}
                if kimyo:
                    vals["location_dest_id"] = kimyo.id
                commands.append(Command.create(vals))
            shift.write({"line_ids": commands})

    def action_fill_from_baskets(self):
        drafts = self.filtered(lambda s: s.state == "draft")
        if not drafts.basket_load_ids:
            raise UserError("Avval korzinkalarni kiriting.")
        drafts._craf_sync_lines_from_baskets()
        return True

    def _craf_action_done(self):
        if self.basket_load_ids:
            self._craf_sync_lines_from_baskets()
        return super()._craf_action_done()

    def action_view_baskets(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("craf_korzinka.action_craf_basket_load")
        action["domain"] = [("shift_id", "=", self.id)]
        action["context"] = {"default_shift_id": self.id}
        return action


class CrafExtrusionShiftLine(models.Model):
    _inherit = "craf.extrusion.shift.line"

    @api.depends("product_id")
    def _compute_location_dest_id(self):
        super()._compute_location_dest_id()
        kimyo = self.env["craf.production.mixin"]._craf_loc("Kimyoviy ishlov")
        if kimyo:
            for line in self:
                # bo'yaladigan profil press dan keyin kimyoviy ishlovga boradi
                if line.product_id and not line.product_id.sale_ok:
                    line.location_dest_id = kimyo
