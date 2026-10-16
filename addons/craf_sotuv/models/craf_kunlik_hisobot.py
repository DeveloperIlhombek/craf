from collections import OrderedDict, defaultdict

from odoo import api, fields, models


class CrafKunlikHisobot(models.AbstractModel):
    _inherit = "craf.kunlik.hisobot"

    # ------------------------------------------------------------------ sotuv bo'limi
    def _sale_moves(self, start, end, products=None):
        domain = [
            ("state", "=", "done"), ("date", ">=", start), ("date", "<", end),
            ("location_id.usage", "=", "internal"), ("location_dest_id.usage", "=", "customer"),
        ]
        if products is not None:
            domain.append(("product_id", "in", products.ids))
        return self.env["stock.move"].search(domain)

    def _sale_orders(self, start, end):
        moves = self._sale_moves(start, end)
        return moves.sale_line_id.order_id

    def _sales(self, start, end):
        moves = self._sale_moves(start, end)
        bucket = OrderedDict()
        for m in moves:
            self._add(bucket, m.product_id, m.product_uom._compute_quantity(m.quantity, m.product_id.uom_id))
        orders = moves.sale_line_id.order_id.sorted(lambda o: (o.craf_given_date or o.date_order, o.id))
        other = moves.filtered(lambda m: not m.sale_line_id).picking_id
        docs = [{
            "model": "sale.order", "id": o.id,
            "name": " · ".join(filter(None, [o.name, o.partner_id.name, o.craf_truck])),
            "state": "done", "state_label": "Berildi", "c1": o.c1_state,
            "who": o.craf_location_id._craf_sale_label() if o.craf_location_id else "", "shift": "",
        } for o in orders]
        docs += [{"model": "stock.picking", "id": p.id, "name": p.name, "state": "done", "state_label": "Bajarildi",
                  "c1": "", "who": p.partner_id.name or "", "shift": ""} for p in other]
        extra = []
        if orders:
            extra.append("Mijozlar: %s" % len(orders.partner_id))
            per_loc = defaultdict(float)
            for m in moves:
                per_loc[m.location_id._craf_sale_label()] += m.quantity * (m.product_id.craf_kg_per_pc or 0.0)
            if len(per_loc) > 1 or "Zavod" not in per_loc:
                extra.append(", ".join("%s: %s kg" % (k, f"{v:,.0f}".replace(",", " ")) for k, v in per_loc.items()))
        rows = self._rows(bucket)
        kg = sum(r["kg"] for r in rows)
        if kg:
            extra.append("Jami: %s kg" % f"{kg:,.0f}".replace(",", " "))
        return {
            "key": "sotuv", "title": "6. Sotuv — mijozlarga berildi", "model": "sale.order", "action": False,
            "docs": docs, "used": [], "made": rows, "waste": [], "extra": extra,
            "done_count": len(orders) + len(other), "draft_count": 0,
        }

    # ------------------------------------------------------------------ tayyor mahsulot: "Sotildi" ustuni
    def _movement(self, products, start, end):
        res = super()._movement(products, start, end)
        if not res:
            return res
        sold, returned = defaultdict(float), defaultdict(float)
        for m in self._sale_moves(start, end, products):
            sold[m.product_id.id] += m.product_uom._compute_quantity(m.quantity, m.product_id.uom_id)
        back = self.env["stock.move"].search([
            ("state", "=", "done"), ("date", ">=", start), ("date", "<", end), ("product_id", "in", products.ids),
            ("location_id.usage", "=", "customer"), ("location_dest_id.usage", "=", "internal"),
        ])
        for m in back:
            returned[m.product_id.id] += m.product_uom._compute_quantity(m.quantity, m.product_id.uom_id)
        for product, d in res.items():
            out, ret = sold.get(product.id, 0.0), returned.get(product.id, 0.0)
            d["out_other"] -= out
            d["in_supply"] -= ret
            d["out_sale"] = out - ret
        return res

    def _movement_rows(self, data, only_active=False):
        rows = super()._movement_rows(data, only_active=False)
        for row in rows:
            row.setdefault("out_sale", 0.0)
        if only_active:
            keys = ("in_supply", "in_prod", "out_prod", "out_other", "out_sale")
            rows = [r for r in rows if any(abs(r.get(k) or 0.0) > 1e-6 for k in keys)]
        return rows

    # ------------------------------------------------------------------ asosiy
    @api.model
    def get_data(self, day=None):
        data = super().get_data(day)
        day = self._parse_day(data["date"])
        start, end = self._day_bounds(day)
        sales = self._sales(start, end)
        data["departments"].append(sales)
        data["c1_new"] += sum(1 for d in sales["docs"] if d["model"] == "sale.order" and d["c1"] == "new")
        data["sold_kg"] = sum(r["kg"] for r in sales["made"])
        return data

    @api.model
    def action_mark_c1(self, day=None):
        count = super().action_mark_c1(day)
        day = self._parse_day(day)
        start, end = self._day_bounds(day)
        orders = self._sale_orders(start, end).filtered(lambda o: o.c1_state == "new")
        orders.action_c1_done()
        return count + len(orders)

    @api.model
    def get_sales_rows(self, day=None):
        """Excel "Sotuv" varag'i uchun: har bir chiqim (joy bo'yicha)."""
        day = self._parse_day(day)
        start, end = self._day_bounds(day)
        rows = []
        moves = self._sale_moves(start, end).sorted(lambda m: (m.date, m.id))
        for m in moves:
            o = m.sale_line_id.order_id
            p = m.product_id
            pcs = m.product_uom._compute_quantity(m.quantity, p.uom_id)
            per = p.craf_pcs_per_pack
            packs, extra = divmod(int(round(pcs)), per) if per else (0, int(round(pcs)))
            when = fields.Datetime.context_timestamp(self, m.date)
            rows.append({
                "time": when.strftime("%d.%m.%Y %H:%M"), "order": o.name or m.reference or "",
                "partner": (o.partner_id or m.partner_id).name or "", "truck": o.craf_truck or "",
                "location": m.location_id._craf_sale_label(),
                "code": p.default_code or "", "name": p.name,
                "packs": packs, "extra": extra, "pcs": pcs, "kg": pcs * (p.craf_kg_per_pc or 0.0),
                "c1": "ha" if o.c1_state == "done" else "",
            })
        return rows
