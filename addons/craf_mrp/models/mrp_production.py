import math

from odoo import Command, api, fields, models


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    craf_can_plan_stages = fields.Boolean(compute="_compute_craf_can_plan_stages")

    @api.model_create_multi
    def create(self, vals_list):
        # Plavka / Press / Bo'yash hujjatlaridan kelgan buyurtma o'z bosqich turiga tushadi
        picking_type_id = self.env.context.get("craf_picking_type_id")
        Bom = self.env["mrp.bom"]
        for vals in vals_list:
            if picking_type_id:
                vals.setdefault("picking_type_id", picking_type_id)
            elif not vals.get("picking_type_id") and not self.env.context.get("default_picking_type_id"):
                # BoM qaysi bosqichga tegishli bo'lsa, buyurtma o'sha bosqich turida ochiladi (raqami ham)
                bom = Bom.browse(vals["bom_id"]) if vals.get("bom_id") else Bom
                if not bom and vals.get("product_id"):
                    product = self.env["product.product"].browse(vals["product_id"])
                    bom = Bom._bom_find(product, bom_type="normal")[product]
                if bom.picking_type_id:
                    vals["picking_type_id"] = bom.picking_type_id.id
        return super().create(vals_list)

    def _craf_component_bom(self, product):
        return self.env["mrp.bom"]._bom_find(product, bom_type="normal")[product]

    @api.depends("state", "move_raw_ids.product_id")
    def _compute_craf_can_plan_stages(self):
        for mo in self:
            mo.craf_can_plan_stages = mo.state in ("draft", "confirmed", "progress") and any(
                mo._craf_component_bom(p) for p in mo.move_raw_ids.product_id)

    def _craf_plan_stages(self, depth=0):
        """Komponent yetishmasa, oldingi bosqich uchun buyurtma ochadi (bo'yash → press → Литейка)."""
        created = self.env["mrp.production"]
        if depth > 5:
            return created
        for mo in self:
            children = mo._get_children().filtered(lambda c: c.state not in ("done", "cancel"))
            for move in mo.move_raw_ids.filtered(lambda m: m.state not in ("done", "cancel")):
                product = move.product_id
                bom = mo._craf_component_bom(product)
                if not bom:
                    continue
                need = move.product_uom._compute_quantity(move.product_uom_qty, product.uom_id)
                reserved = move.product_uom._compute_quantity(move.quantity, product.uom_id)
                free = product.with_context(location=mo.location_src_id.id).free_qty
                planned = sum(children.filtered(lambda c: c.product_id == product).mapped("product_qty"))
                shortage = need - reserved - max(free, 0.0) - planned
                if shortage <= 0.005:
                    continue
                kg = self.env.ref("uom.product_uom_kgm", raise_if_not_found=False)
                qty = round(shortage, 2) if product.uom_id == kg else math.ceil(shortage - 1e-6)
                child = self.create({
                    "product_id": product.id,
                    "product_qty": qty,
                    "product_uom_id": product.uom_id.id,
                    "bom_id": bom.id,
                    "origin": mo.name,
                    "company_id": mo.company_id.id,
                })
                child.production_group_id.parent_ids = [Command.link(mo.production_group_id.id)]
                if mo.state != "draft":
                    child.action_confirm()
                created |= child
                created |= child._craf_plan_stages(depth + 1)
        return created

    def action_craf_plan_stages(self):
        created = self._craf_plan_stages()
        if not created:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "info",
                    "title": "Oldingi bosqichlar",
                    "message": "Komponentlar qoldig'i yetarli yoki allaqachon rejalangan — yangi buyurtma kerak emas.",
                },
            }
        for mo in self:
            mo.message_post(body="Oldingi bosqichlar uchun buyurtmalar ochildi: %s" % ", ".join(
                created.mapped(lambda c: "%s (%s %s)" % (c.name, c.product_qty, c.product_uom_id.name))))
        return {
            "type": "ir.actions.act_window",
            "name": "Bosqich buyurtmalari",
            "res_model": "mrp.production",
            "views": [(False, "list"), (False, "form")],
            "domain": [("id", "in", created.ids)],
            "context": {"create": False},
        }
