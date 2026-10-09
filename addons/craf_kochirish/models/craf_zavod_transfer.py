import math

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

EPS = 1e-6


def _fmt(value, digits=0):
    text = f"{value:,.{digits}f}".replace(",", " ")
    return text


class CrafZavodTransfer(models.TransientModel):
    _name = "craf.zavod.transfer"
    _description = "Zavod xaritasidan ko'chirish"

    location_id = fields.Many2one(
        "stock.location", string="Qayerdan", required=True, domain=[("usage", "=", "internal")])
    location_dest_id = fields.Many2one(
        "stock.location", string="Qayerga", required=True,
        domain="[('usage', '=', 'internal'), ('id', '!=', location_id)]")
    available_product_ids = fields.Many2many(
        "product.product", compute="_compute_available_product_ids")
    product_id = fields.Many2one(
        "product.product", string="Mahsulot", required=True,
        domain="[('id', 'in', available_product_ids)]")
    uom_id = fields.Many2one(related="product_id.uom_id", string="Birlik")
    pcs_per_pack = fields.Integer(related="product_id.craf_pcs_per_pack", string="Dona / pachka")
    available_qty = fields.Float("Mavjud", compute="_compute_available", digits="Product Unit")
    available_text = fields.Char("Mavjud", compute="_compute_available")
    qty_packs = fields.Integer("Pachka")
    qty_extra = fields.Integer("+ dona")
    quantity = fields.Float(
        "Miqdor", compute="_compute_quantity", store=True, readonly=False, digits="Product Unit")
    summary = fields.Char("Bu", compute="_compute_summary")

    @api.depends("location_id")
    def _compute_available_product_ids(self):
        Quant = self.env["stock.quant"]
        for wiz in self:
            if not wiz.location_id:
                wiz.available_product_ids = False
                continue
            quants = Quant.search([("location_id", "child_of", wiz.location_id.id), ("quantity", ">", 0)])
            wiz.available_product_ids = quants.product_id

    def _text_for(self, product, qty):
        tmpl = product.product_tmpl_id
        per_pack = tmpl.craf_pcs_per_pack
        kg_uom = self.env.ref("uom.product_uom_kgm", raise_if_not_found=False)
        if kg_uom and product.uom_id == kg_uom:
            return "%s kg" % _fmt(qty, 2 if qty % 1 else 0)
        pcs = int(math.floor(qty + EPS))
        text = "%s шт" % _fmt(pcs)
        if per_pack:
            packs, rest = divmod(pcs, per_pack)
            text += " = %s pachka" % _fmt(packs) + (" + %s dona" % rest if rest else "")
        if tmpl.craf_kg_per_pc:
            text += " · %s kg" % _fmt(pcs * tmpl.craf_kg_per_pc)
        return text

    @api.depends("location_id", "product_id")
    def _compute_available(self):
        Quant = self.env["stock.quant"]
        for wiz in self:
            if wiz.location_id and wiz.product_id:
                qty = Quant._get_available_quantity(wiz.product_id, wiz.location_id)
                wiz.available_qty = qty
                wiz.available_text = self._text_for(wiz.product_id, qty)
            else:
                wiz.available_qty = 0.0
                wiz.available_text = False

    @api.depends("qty_packs", "qty_extra", "product_id")
    def _compute_quantity(self):
        for wiz in self:
            per_pack = wiz.product_id.product_tmpl_id.craf_pcs_per_pack
            if per_pack and (wiz.qty_packs or wiz.qty_extra):
                wiz.quantity = wiz.qty_packs * per_pack + wiz.qty_extra
            elif not wiz.quantity:
                wiz.quantity = 0.0

    @api.depends("quantity", "product_id")
    def _compute_summary(self):
        for wiz in self:
            wiz.summary = self._text_for(wiz.product_id, wiz.quantity) if wiz.product_id and wiz.quantity else False

    def action_confirm(self):
        self.ensure_one()
        if self.location_id == self.location_dest_id:
            raise UserError("Qayerdan va qayerga bir xil bo'lishi mumkin emas.")
        if self.quantity <= 0:
            raise UserError("Miqdor 0 dan katta bo'lishi kerak.")
        if self.quantity > self.available_qty + EPS:
            raise UserError("%s da faqat %s bor." % (self.location_id.name, self.available_text))
        warehouse = self.location_id.warehouse_id or self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1)
        picking_type = warehouse.int_type_id
        if not picking_type:
            raise UserError("Omborda ichki ko'chirish turi topilmadi.")
        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "location_id": self.location_id.id,
            "location_dest_id": self.location_dest_id.id,
            "origin": "Zavod xaritasi",
            "move_ids": [Command.create({
                "product_id": self.product_id.id,
                "product_uom_qty": self.quantity,
                "product_uom": self.product_id.uom_id.id,
                "location_id": self.location_id.id,
                "location_dest_id": self.location_dest_id.id,
            })],
        })
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.with_context(skip_backorder=True, picking_ids_not_to_backorder=picking.ids).button_validate()
        if picking.state != "done":
            raise UserError("Ko'chirish bajarilmadi (%s). Hujjat: %s" % (picking.state, picking.name))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": "Ko'chirildi",
                "message": "%s: %s → %s (%s)" % (
                    self.product_id.display_name, self.location_id.name, self.location_dest_id.name,
                    self._text_for(self.product_id, self.quantity)),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
