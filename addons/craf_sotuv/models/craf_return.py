"""Sotuvdan qaytarish: sotuvchi berilgan buyurtmadan mahsulotni qaytarib oladi.

Mijozdan (Partners/Customers) tanlangan sotuv joyiga (Zavod, Parnik, Rohat) kirim hujjati yoziladi.
Harakatlar buyurtma qatoriga bog'lanadi (to_refund) — Odoo «yetkazildi» miqdorini o'zi kamaytiradi,
Pul moduli esa hisob-faktura bo'lsa qaytarish hisob-fakturasini yozadi (_craf_after_return).
"""
from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from .sale_order_line import packs_text

EPS = 1e-6


class StockPicking(models.Model):
    _inherit = "stock.picking"

    craf_return_order_id = fields.Many2one("sale.order", "Qaytarilgan sotuv", index="btree_not_null", copy=False,
                                           readonly=True)
    craf_return_note = fields.Char("Qaytarish sababi", copy=False)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    craf_return_ids = fields.One2many("stock.picking", "craf_return_order_id", string="Qaytarishlar", readonly=True)
    craf_return_count = fields.Integer("Qaytarishlar", compute="_compute_craf_return_count")

    def _compute_craf_return_count(self):
        for order in self:
            order.craf_return_count = len(order.craf_return_ids.filtered(lambda p: p.state == "done"))

    def _craf_returned_by_line(self):
        """{sale.order.line: qaytarilgan dona} — bajarilgan qaytarishlar bo'yicha."""
        res = {}
        for move in self.craf_return_ids.filtered(lambda p: p.state == "done").move_ids:
            if move.state == "done" and move.sale_line_id:
                res[move.sale_line_id] = res.get(move.sale_line_id, 0.0) + move.quantity
        return res

    def _craf_return(self, location, quantities, note=False):
        """quantities: {sale.order.line: dona}. Mijozdan location ga kirim yozadi va darhol bajaradi."""
        self.ensure_one()
        if self.state != "sale":
            raise UserError("Faqat tasdiqlangan sotuvdan qaytarish mumkin.")
        if not location or location.usage != "internal":
            raise UserError("Qaytarilgan mahsulot tushadigan joyni tanlang.")
        quantities = {line: qty for line, qty in quantities.items() if qty > EPS}
        if not quantities:
            raise UserError("Qaytariladigan miqdorni yozing.")
        for line, qty in quantities.items():
            if line.order_id != self:
                raise UserError("Qator boshqa buyurtmaga tegishli.")
            if qty - line.qty_delivered > EPS:
                raise UserError("%s: qaytarish (%s) berilgan miqdordan (%s) ko'p bo'lishi mumkin emas." % (
                    line.product_id.display_name, packs_text(qty, line.product_id.craf_pcs_per_pack),
                    packs_text(line.qty_delivered, line.product_id.craf_pcs_per_pack)))
        customer = self.env.ref("stock.stock_location_customers")
        warehouse = location.warehouse_id or self.warehouse_id
        picking_type = warehouse.return_type_id or warehouse.in_type_id
        moves = []
        for line, qty in quantities.items():
            origin = line.move_ids.filtered(
                lambda m: m.state == "done" and m.location_dest_id.usage == "customer")[-1:]
            moves.append(Command.create({
                "product_id": line.product_id.id,
                "product_uom_qty": qty,
                "product_uom": line.product_id.uom_id.id,
                "location_id": customer.id,
                "location_dest_id": location.id,
                "sale_line_id": line.id,
                "to_refund": True,
                "origin_returned_move_id": origin.id or False,
                "partner_id": self.partner_shipping_id.id,
            }))
        picking = self.env["stock.picking"].sudo().create({
            "picking_type_id": picking_type.id,
            "location_id": customer.id,
            "location_dest_id": location.id,
            "partner_id": self.partner_shipping_id.id,
            "origin": "Qaytarish %s" % self.name,
            "craf_return_order_id": self.id,
            "craf_return_note": note or False,
            "move_ids": moves,
        })
        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.with_context(skip_backorder=True, picking_ids_not_to_backorder=picking.ids).button_validate()
        if picking.state != "done":
            raise UserError("Qaytarish bajarilmadi (%s)." % picking.state)
        rows = Markup("").join(Markup("<li>%s — %s</li>") % (
            line.product_id.display_name, packs_text(qty, line.product_id.craf_pcs_per_pack))
            for line, qty in quantities.items())
        self.message_post(body=Markup("<b>Qaytarildi</b> → %s (%s)%s<ul>%s</ul>") % (
            location._craf_sale_label(), picking.name, Markup(" · %s") % note if note else "", rows))
        self._craf_after_return(picking)
        return picking

    def _craf_after_return(self, picking):
        """Pul moduli qaytarish hisob-fakturasini yozadi."""
        return True


class CrafSotuv(models.AbstractModel):
    _inherit = "craf.sotuv"

    @api.model
    def return_info(self, order_id):
        self._check_seller()
        so = self.env["sale.order"].browse(int(order_id)).exists()
        if not so:
            raise UserError("Buyurtma topilmadi.")
        returned = so._craf_returned_by_line()
        lines = []
        for line in so.order_line.filtered(lambda l: not l.display_type and l.product_id.is_storable):
            if line.qty_delivered <= EPS and not returned.get(line):
                continue
            per_pack = line.product_id.craf_pcs_per_pack
            lines.append({
                "line_id": line.id, "product": line.product_id.name, "code": line.product_id.default_code or "",
                "per_pack": per_pack or 0, "delivered": line.qty_delivered,
                "delivered_text": packs_text(line.qty_delivered, per_pack),
                "returned": returned.get(line, 0.0),
                "returned_text": packs_text(returned.get(line, 0.0), per_pack) if returned.get(line) else "",
            })
        return {
            "id": so.id, "name": so.name, "partner": so.partner_id.name,
            "location_id": so.craf_location_id.id or False,
            "locations": [{"id": l.id, "name": l._craf_sale_label()} for l in self._locations()],
            "lines": lines,
            "history": [{"name": p.name, "date": self._utc_to_local_str(p.date_done, "%d.%m.%Y %H:%M"),
                         "location": p.location_dest_id._craf_sale_label(), "note": p.craf_return_note or ""}
                        for p in so.craf_return_ids.filtered(lambda p: p.state == "done").sorted("id")],
        }

    @api.model
    def return_save(self, order_id, location_id, rows, note=""):
        self._check_seller()
        so = self.env["sale.order"].browse(int(order_id)).exists()
        if not so:
            raise UserError("Buyurtma topilmadi.")
        location = self.env["stock.location"].browse(int(location_id or 0)).exists()
        quantities = {}
        for row in rows or []:
            line = self.env["sale.order.line"].browse(int(row.get("line_id") or 0)).exists()
            if not line:
                continue
            per_pack = line.product_id.craf_pcs_per_pack or 0
            packs = self._return_int(row.get("packs"))
            pcs = self._return_int(row.get("pcs"))
            qty = packs * per_pack + pcs
            if qty:
                quantities[line] = quantities.get(line, 0) + qty
        picking = so._craf_return(location, quantities, (note or "").strip() or False)
        so._craf_notify("return", "Qaytarildi", "%s · %s — qaytarildi (%s)" % (
            so.name, so.partner_id.name, location._craf_sale_label()), to_loaders=True)
        return {"picking": picking.name, "card": self._order_card(so)}

    def _return_int(self, value):
        try:
            number = int(str(value or 0).strip() or 0)
        except ValueError:
            raise UserError("Miqdor butun son bo'lishi kerak: %s" % value) from None
        if number < 0:
            raise UserError("Miqdor manfiy bo'lishi mumkin emas.")
        return number

    def _order_card(self, so):
        card = super()._order_card(so)
        returned = so._craf_returned_by_line()
        if returned:
            by_product = {}
            for line, qty in returned.items():
                by_product[line.product_id.default_code or line.product_id.name] = (line, qty)
            for row in card["lines"]:
                hit = by_product.get(row["code"] or row["product"])
                if hit:
                    row["returned"] = hit[1]
                    row["returned_text"] = packs_text(hit[1], hit[0].product_id.craf_pcs_per_pack)
        card["return_count"] = so.craf_return_count
        card["can_return"] = so.state == "sale" and any(
            l.qty_delivered > EPS for l in so.order_line if l.product_id.is_storable)
        return card
