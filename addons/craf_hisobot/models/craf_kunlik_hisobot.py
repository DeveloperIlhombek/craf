from collections import OrderedDict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models

DEPARTMENTS = [
    # (kalit, sarlavha, model, harakat)
    ("pech", "1. Pech (eritish va quyish)", "craf.foundry.melt", "craf_foundry.action_craf_foundry_melt"),
    ("press", "2. Press", "craf.extrusion.shift", "craf_extrusion.action_craf_extrusion_shift"),
    ("kimyo", "3. Kimyoviy ishlov", "craf.chem.treatment", "craf_korzinka.action_craf_chem_treatment"),
    ("boyash", "4. Bo'yash va qadoqlash", "craf.paint.batch", "craf_paint.action_craf_paint_batch"),
]
STATE_LABELS = {"draft": "Qoralama", "done": "Bajarildi", "cancel": "Bekor"}


class CrafKunlikHisobot(models.AbstractModel):
    _name = "craf.kunlik.hisobot"
    _description = "Craf kunlik hisobot (1C uchun)"

    # ------------------------------------------------------------------ vaqt
    @api.model
    def _day_bounds(self, day):
        tz = pytz.timezone(self.env.user.tz or self.env.context.get("tz") or "Asia/Tashkent")
        start = tz.localize(datetime.combine(day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        return start, start + timedelta(days=1)

    @api.model
    def _parse_day(self, day):
        return fields.Date.to_date(day) if day else fields.Date.context_today(self)

    # ------------------------------------------------------------------ yig'ish
    @staticmethod
    def _add(bucket, product, qty, kg=0.0):
        if not product or not qty:
            return
        row = bucket.setdefault(product, [0.0, 0.0])
        row[0] += qty
        row[1] += kg

    def _uom(self, product):
        unit = self.env.ref("uom.product_uom_unit", raise_if_not_found=False)
        return "dona" if unit and product.uom_id == unit else (product.uom_id.name or "")

    def _rows(self, bucket):
        rows = []
        for product, (qty, kg) in sorted(bucket.items(), key=lambda kv: kv[0].display_name):
            uom = self._uom(product)
            rows.append({
                "product_id": product.id,
                "code": product.default_code or "",
                "name": product.name,
                "qty": round(qty, 3),
                "uom": uom,
                "kg": round(kg or (qty if self._is_kg(product) else qty * (product.craf_kg_per_pc or 0.0)), 2),
            })
        return rows

    def _is_kg(self, product):
        kg = self.env.ref("uom.product_uom_kgm", raise_if_not_found=False)
        return bool(kg) and product.uom_id == kg

    def _doc_info(self, rec):
        return {
            "model": rec._name, "id": rec.id, "name": rec.name, "state": rec.state,
            "state_label": STATE_LABELS.get(rec.state, rec.state), "c1": rec.c1_state,
            "who": rec.employee_id.name or "", "shift": dict(rec._fields["shift"].selection).get(rec.shift, ""),
        }

    def _department(self, key, docs):
        done = docs.filtered(lambda d: d.state == "done")
        used, made, waste = OrderedDict(), OrderedDict(), OrderedDict()
        extra = []
        if key == "pech":
            for d in done:
                for line in d.line_ids:
                    self._add(used, line.product_id, line.qty)
                self._add(made, d.billet_product_id, d.billet_qty)
                self._add(waste, d.slag_product_id, d.slag_qty)
                if "cut_waste_qty" in d._fields:
                    self._add(waste, d.cut_waste_product_id, d.cut_waste_qty)
            metal = sum(done.mapped("charge_metal"))
            loss = sum(done.mapped("burn_loss_qty"))
            if metal:
                extra.append("Угар: %.2f%%" % (loss / metal * 100))
        elif key == "press":
            for d in done:
                self._add(used, d.billet_product_id, d.billet_qty)
                for line in d.line_ids:
                    self._add(made, line.product_id, line.pcs, line.kg)
                self._add(waste, d.rest_product_id, d.rest_qty)
                self._add(waste, d.scrap_product_id, d.scrap_qty)
            if "basket_count" in docs._fields:
                extra.append("Korzinkalar: %s ta" % sum(done.mapped("basket_count")))
            billet = sum(done.mapped("billet_qty"))
            if billet:
                extra.append("Chiqish: %.1f%%" % (sum(done.mapped("output_kg")) / billet * 100))
        elif key == "kimyo":
            for d in done:
                for line in d.chem_line_ids:
                    self._add(used, line.product_id, line.qty)
                for product, qty in d.load_ids._product_quantities().items():
                    self._add(made, product, qty)
            extra.append("Korzinkalar: %s ta" % sum(done.mapped("basket_count")))
        elif key == "boyash":
            for d in done:
                for line in d.line_ids:
                    self._add(used, line.semi_product_id, line.pcs_in)
                    self._add(made, line.product_id, line.pcs_ok, line.kg_ok)
                    if line.pcs_defect and d.scrap_product_id:
                        self._add(waste, d.scrap_product_id, line.pcs_defect * (line.kg_per_pc or 0.0))
                self._add(used, d.powder_product_id, d.powder_qty)
                for line in d.chem_line_ids:
                    self._add(used, line.product_id, line.qty)
            pcs_in = sum(done.mapped("pcs_in"))
            if pcs_in:
                extra.append("Brak: %.2f%%" % (sum(done.mapped("pcs_defect")) / pcs_in * 100))
            packs = self.env["craf.pack"].search_count([("origin", "in", done.mapped("name"))]) if done else 0
            extra.append("Pachkalar: %s ta" % packs)
        return {
            "docs": [self._doc_info(d) for d in docs],
            "used": self._rows(used),
            "made": self._rows(made),
            "waste": self._rows(waste),
            "extra": extra,
            "done_count": len(done),
            "draft_count": len(docs.filtered(lambda d: d.state == "draft")),
        }

    def _to_stock(self, start, end):
        dest = self.env["craf.production.mixin"]._craf_loc("Tayyor mahsulot ombori")
        moves = self.env["stock.move"].search([
            ("state", "=", "done"), ("date", ">=", start), ("date", "<", end),
            ("location_dest_id", "=", dest.id), ("location_id.usage", "=", "internal"),
            ("location_id", "!=", dest.id),
        ]) if dest else self.env["stock.move"]
        bucket = OrderedDict()
        for m in moves:
            self._add(bucket, m.product_id, m.product_uom._compute_quantity(m.quantity, m.product_id.uom_id))
        pickings = moves.picking_id
        return {"made": self._rows(bucket), "docs": [
            {"model": "stock.picking", "id": p.id, "name": p.name, "state": p.state, "state_label": "Bajarildi",
             "c1": "", "who": p.origin or "", "shift": ""} for p in pickings]}

    # ------------------------------------------------------------------ ombor harakati
    def _movement(self, products, start, end):
        """{product: dict(opening, in_supply, in_prod, out_prod, out_other, closing)} — barcha ichki joylar."""
        if not products:
            return {}
        Move = self.env["stock.move"]
        internal = [("location_dest_id.usage", "=", "internal"), ("location_id.usage", "!=", "internal")]
        external = [("location_id.usage", "=", "internal"), ("location_dest_id.usage", "!=", "internal")]
        base = [("state", "=", "done"), ("product_id", "in", products.ids)]

        def total(domain):
            result = {}
            for m in Move.search(base + domain):
                qty = m.product_uom._compute_quantity(m.quantity, m.product_id.uom_id)
                key = (m.product_id.id, m.location_id.usage, m.location_dest_id.usage)
                result[key] = result.get(key, 0.0) + qty
            return result

        day = [("date", ">=", start), ("date", "<", end)]
        after = [("date", ">=", end)]
        in_day, out_day = total(internal + day), total(external + day)
        in_after, out_after = total(internal + after), total(external + after)
        on_hand = {}
        for q in self.env["stock.quant"].search([("product_id", "in", products.ids), ("location_id.usage", "=", "internal")]):
            on_hand[q.product_id.id] = on_hand.get(q.product_id.id, 0.0) + q.quantity

        def pick(data, pid, src=None, dest=None):
            return sum(v for (p, s, d), v in data.items() if p == pid and (src is None or s in src)
                       and (dest is None or d in dest))

        result = {}
        for product in products:
            pid = product.id
            closing = on_hand.get(pid, 0.0) - pick(in_after, pid) + pick(out_after, pid)
            in_prod = pick(in_day, pid, src=("production",))
            in_supply = pick(in_day, pid) - in_prod
            out_prod = pick(out_day, pid, dest=("production",))
            out_other = pick(out_day, pid) - out_prod
            opening = closing - in_supply - in_prod + out_prod + out_other
            result[product] = {
                "opening": opening, "in_supply": in_supply, "in_prod": in_prod,
                "out_prod": out_prod, "out_other": out_other, "closing": closing,
            }
        return result

    def _movement_rows(self, data, only_active=False):
        rows = []
        for product, d in sorted(data.items(), key=lambda kv: (kv[0].default_code or "", kv[0].name)):
            active = any(abs(d[k]) > 1e-6 for k in ("in_supply", "in_prod", "out_prod", "out_other"))
            if only_active and not active:
                continue
            min_qty = product.craf_min_qty
            rows.append({
                "product_id": product.id,
                "code": product.default_code or "",
                "name": product.name,
                "uom": self._uom(product),
                **{k: round(v, 2) for k, v in d.items()},
                "min_qty": min_qty,
                "low": bool(min_qty) and d["closing"] < min_qty,
                "kg_per_pc": product.craf_kg_per_pc,
            })
        return rows

    # ------------------------------------------------------------------ asosiy
    @api.model
    def get_data(self, day=None):
        day = self._parse_day(day)
        start, end = self._day_bounds(day)
        departments = []
        new_count = 0
        for key, title, model, action in DEPARTMENTS:
            if model not in self.env:
                continue
            docs = self.env[model].search([("date", "=", day), ("state", "!=", "cancel")], order="id")
            dep = self._department(key, docs)
            dep.update({"key": key, "title": title, "model": model, "action": action})
            new_count += len(docs.filtered(lambda d: d.state == "done" and d.c1_state == "new"))
            departments.append(dep)
        stock = self._to_stock(start, end)
        stock.update({"key": "ombor", "title": "5. Omborga topshirildi (tayyor mahsulot)", "model": "stock.picking",
                      "used": [], "waste": [], "extra": [], "done_count": len(stock["docs"]), "draft_count": 0,
                      "action": False})
        departments.append(stock)

        raw_root = self.env.ref("craf_nomenklatura.categ_raw_root", raise_if_not_found=False)
        fin_root = self.env.ref("craf_nomenklatura.categ_finished", raise_if_not_found=False)
        Product = self.env["product.product"]
        raw = Product.search([("categ_id", "child_of", raw_root.id), ("is_storable", "=", True)]) if raw_root else Product
        fin = Product.search([("categ_id", "child_of", fin_root.id), ("is_storable", "=", True)]) if fin_root else Product
        raw_rows = self._movement_rows(self._movement(raw, start, end))
        fin_rows = self._movement_rows(self._movement(fin, start, end), only_active=True)
        return {
            "date": fields.Date.to_string(day),
            "date_label": day.strftime("%d.%m.%Y"),
            "prev": fields.Date.to_string(day - timedelta(days=1)),
            "next": fields.Date.to_string(day + timedelta(days=1)),
            "is_today": day == fields.Date.context_today(self),
            "departments": departments,
            "raw": raw_rows,
            "low_count": sum(1 for r in raw_rows if r["low"]),
            "finished": fin_rows,
            "c1_new": new_count,
        }

    @api.model
    def action_mark_c1(self, day=None):
        day = self._parse_day(day)
        count = 0
        for _key, _title, model, _action in DEPARTMENTS:
            if model not in self.env:
                continue
            docs = self.env[model].search([("date", "=", day), ("state", "=", "done"), ("c1_state", "=", "new")])
            docs.action_c1_done()
            count += len(docs)
        return count
