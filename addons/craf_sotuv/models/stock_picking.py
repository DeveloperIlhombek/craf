from collections import OrderedDict

from odoo import fields, models

from .sale_order_line import packs_text


def num(value, digits=0):
    """12345.6 -> '12 345,6' (o'zbekcha ko'rinish)."""
    return ("{:,.%sf}" % digits).format(value or 0).replace(",", " ").replace(".", ",")


class StockPicking(models.Model):
    _inherit = "stock.picking"

    craf_sale_partner_id = fields.Many2one(related="sale_id.partner_id", string="Mijoz")
    craf_truck = fields.Char(related="sale_id.craf_truck", string="Mashina")
    craf_sale_name = fields.Char(related="sale_id.name", string="Buyurtma")  # yuklovchi sale.order ni o'qimaydi

    def _action_done(self):
        res = super()._action_done()
        # Ombordan qo'lda bajarilgan yetkazib berish ham yuklash holatini yangilaydi
        orders = self.filtered(lambda p: p.picking_type_code == "outgoing").sale_id
        for order in orders.filtered(lambda o: o.craf_load_state in ("draft", "queue", "loading")):
            if not order._craf_open_pickings():
                vals = {"craf_load_state": "done"}
                if not order.craf_given_date:
                    vals["craf_given_date"] = fields.Datetime.now()
                if not order.craf_loader_id:
                    vals["craf_loader_id"] = self.env.user.id
                order.write(vals)
        return res

    # ------------------------------------------------------------------ yuk xati
    def _craf_waybill(self):
        """Yuk xati uchun ma'lumot: bajarilgan bo'lsa — berilgan miqdor, aks holda — buyurtma qilingan."""
        self.ensure_one()
        done = self.state == "done"
        moves = self.move_ids.filtered(lambda m: m.state == "done" if done else m.state != "cancel")
        rows = OrderedDict()
        for move in moves.sorted(lambda m: (m.product_id.default_code or "", m.id)):
            qty = move.product_uom._compute_quantity(
                move.quantity if done else move.product_uom_qty, move.product_id.uom_id)
            row = rows.setdefault(move.product_id, {"product": move.product_id, "pcs": 0.0})
            row["pcs"] += qty
        lines, total_pcs, total_packs, total_kg = [], 0, 0, 0.0
        for product, row in rows.items():
            tmpl = product.product_tmpl_id
            per = tmpl.craf_pcs_per_pack or 0
            pcs = int(round(row["pcs"]))
            packs, rest = divmod(pcs, per) if per else (0, pcs)
            kg = pcs * (tmpl.craf_kg_per_pc or 0.0)
            lines.append({
                "product": product, "code": product.default_code or "", "name": product.name,
                "length": tmpl.craf_length_m, "per_pack": per, "packs": packs, "rest": rest, "pcs": pcs,
                "packs_text": packs_text(pcs, per), "kg": kg,
                "packs_s": num(packs), "pcs_s": num(pcs), "kg_s": num(kg, 1),
            })
            total_pcs += pcs
            total_packs += packs
            total_kg += kg
        order = self.sudo().sale_id
        when = self.date_done or self.scheduled_date
        return {
            "lines": lines, "total_pcs": total_pcs, "total_packs": total_packs, "total_kg": total_kg,
            "total_pcs_s": num(total_pcs), "total_packs_s": num(total_packs), "total_kg_s": num(total_kg, 1),
            "order": order, "partner": order.partner_id or self.partner_id, "done": done,
            "date": fields.Datetime.context_timestamp(self, when) if when else False,
            "location": self.location_id._craf_sale_label() if self.location_id else "",
            "loader": order.craf_loader_id or (self.env.user if not done else self.env["res.users"]),
            "seller": order.user_id,
        }

    def action_craf_print_waybill(self):
        return self.env.ref("craf_sotuv.action_report_craf_waybill").report_action(self)
