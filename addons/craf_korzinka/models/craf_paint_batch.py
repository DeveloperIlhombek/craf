from odoo import Command, api, fields, models
from odoo.exceptions import UserError


class CrafPaintBatch(models.Model):
    _inherit = "craf.paint.batch"

    load_ids = fields.Many2many(
        "craf.basket.load", "craf_paint_batch_load_rel", "batch_id", "load_id", string="Korzinkalar",
        domain="[('state', 'in', ('press', 'kimyo')), ('shift_state', '=', 'done')]")
    basket_count = fields.Integer("Korzinkalar", compute="_compute_basket_count", store=True, aggregator="sum")
    stock_picking_id = fields.Many2one("stock.picking", "Omborga topshirish", readonly=True, copy=False)
    stock_state = fields.Selection([("no", "Topshirilmagan"), ("done", "Omborga topshirildi")],
                                   compute="_compute_stock_state", string="Ombor")

    @api.depends("load_ids")
    def _compute_basket_count(self):
        for batch in self:
            batch.basket_count = len(batch.load_ids)

    def _compute_stock_state(self):
        for batch in self:
            batch.stock_state = "done" if batch.stock_picking_id.state == "done" else "no"

    def action_fill_from_baskets(self):
        for batch in self.filtered(lambda b: b.state == "draft"):
            if not batch.load_ids:
                raise UserError("Korzinkalarni tanlang (bo'yashdagi korzinkalar).")
            quantities = batch.load_ids._product_quantities()
            commands = [Command.unlink(l.id) for l in batch.line_ids if l.semi_product_id in quantities]
            commands += [Command.create({"semi_product_id": p.id, "pcs_in": q}) for p, q in quantities.items()]
            batch.write({"line_ids": commands})
        return True

    def action_add_ready_baskets(self):
        for batch in self.filtered(lambda b: b.state == "draft"):
            ready = self.env["craf.basket.load"].search([("state", "in", ("press", "kimyo")),
                                                         ("shift_state", "=", "done")])
            batch.load_ids = [Command.link(l.id) for l in ready]
        return True

    def action_fill_norms(self):
        res = super().action_fill_norms()
        # kimyo endi alohida bosqichda (Kimyoviy ishlov) yoziladi
        self.filtered(lambda b: b.state == "draft").chem_line_ids.unlink()
        return res

    def _craf_action_done(self):
        res = super()._craf_action_done()
        if self.load_ids:
            self.load_ids.write({"state": "boyash", "paint_batch_id": self.id})
        return res

    def action_send_to_stock(self):
        """Bo'yalgan mahsulotni (va pachkalarini) Tayyor mahsulot omboriga topshiradi."""
        self.ensure_one()
        if self.state != "done":
            raise UserError("Avval bo'yash smenasini tasdiqlang.")
        if self.stock_picking_id:
            raise UserError("Bu smena allaqachon omborga topshirilgan: %s" % self.stock_picking_id.name)
        dest = self._craf_loc("Tayyor mahsulot ombori")
        if not dest:
            raise UserError("'Tayyor mahsulot ombori' joylashuvi topilmadi.")
        src = self.location_dest_id
        quantities = {}
        for line in self.line_ids.filtered(lambda l: l.pcs_ok > 0):
            quantities[line.product_id] = quantities.get(line.product_id, 0) + line.pcs_ok
        self._craf_check_available(src, quantities)
        warehouse = src.warehouse_id or self.env["stock.warehouse"].search([("company_id", "=", self.company_id.id)],
                                                                           limit=1)
        picking = self.env["stock.picking"].create({
            "picking_type_id": warehouse.int_type_id.id,
            "location_id": src.id,
            "location_dest_id": dest.id,
            "origin": self.name,
            "move_ids": [Command.create({
                "product_id": p.id, "product_uom_qty": q, "product_uom": p.uom_id.id,
                "location_id": src.id, "location_dest_id": dest.id,
            }) for p, q in quantities.items()],
        })
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.with_context(skip_backorder=True, picking_ids_not_to_backorder=picking.ids).button_validate()
        if picking.state != "done":
            raise UserError("Omborga topshirish bajarilmadi (%s)." % picking.state)
        self.stock_picking_id = picking
        packs = self.env["craf.pack"].search([("origin", "=", self.name)])
        packs.write({"location_id": dest.id})
        self.message_post(body="Omborga topshirildi: %s → %s (%s)" % (src.name, dest.name, picking.name))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": "Omborga topshirildi",
                "message": "%s: %s dona → %s" % (self.name, sum(quantities.values()), dest.name),
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }
