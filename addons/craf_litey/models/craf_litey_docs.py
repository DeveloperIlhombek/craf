"""Литейка hujjatlari: kirim, ko'chirish, sanash va barcha hujjatlar jurnali (telefon sahifasi uchun).

Hujjat turlari va Inventarizatsiya (stock) dagi o'rni:
- Plavka (craf.foundry.melt)        → Ishlab chiqarish buyurtmasi (LIT), sarf va chiqish harakatlari
- Kirim (stock.picking, incoming)   → Kvitansiyalar (WH/IN)
- Ko'chirish (stock.picking, internal) → Ichki o'tkazmalar (WH/INT)
- Chiqim (stock.picking, outgoing)  → Yetkazib berish (WH/OUT), masalan шлак sotuvi
- Sanash (craf.litey.count)          → Fizik inventarizatsiya harakatlari (nomi: SN-…)
- Tuzatish (stock.move, is_inventory) → hujjatsiz inventarizatsiya: Excel qoldig'i, Odoo da qo'lda
"""
from collections import defaultdict
from datetime import time, timedelta

import pytz

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_litey.models.craf_foundry_melt import parse_sum
from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt

DOC_KINDS = {
    "plavka": "Plavka",
    "kirim": "Kirim",
    "kochirish": "Ko'chirish",
    "chiqim": "Chiqim",
    "sanash": "Sanash",
    "tuzatish": "Tuzatish",
}
PICKING_STATES = {"draft": "Qoralama", "waiting": "Kutilmoqda", "confirmed": "Kutilmoqda", "assigned": "Tayyor",
                  "done": "Bajarildi", "cancel": "Bekor"}
MELT_STATES = {"draft": "Qoralama", "done": "Bajarildi", "cancel": "Bekor"}
COUNT_STATES = {"draft": "Qoralama", "done": "Tasdiqlangan", "cancel": "Bekor"}


def _q(value):
    """1234.5 → '1 234,5'; katta sonlar butun, kasr faqat kerak bo'lsa."""
    if abs(value) >= 100 or abs(value) % 1 < 1e-9:
        return fmt(value, 0)
    return fmt(value, 2).rstrip("0").rstrip(",")


class CrafLiteyHisobot(models.AbstractModel):
    _inherit = "craf.litey.hisobot"

    # ------------------------------------------------------------------ umumiy
    def _all_litey_products(self):
        return self._products() | self._products(hidden=True)

    def _int_locations(self):
        return self.env["stock.location"].search(
            [("usage", "=", "internal"), ("company_id", "in", [self.env.company.id, False])], order="name")

    def _num(self, text, label):
        """'993+600+351' → 1944; xatoda material nomi bilan tushunarli xabar."""
        try:
            value = parse_sum(text)
        except UserError as err:
            raise UserError("%s: %s" % (label, err)) from err
        return value

    def _sum_label(self, items):
        """[(qty, uom)] → '3 254 kg + 12 dona'."""
        by_uom = defaultdict(float)
        for qty, uom in items:
            by_uom[uom] += qty
        return " + ".join("%s %s" % (_q(q), u) for u, q in by_uom.items() if abs(q) > EPS) or "—"

    def _items_label(self, items, limit=3):
        """[(name, qty, uom)] → 'А8 3 254 kg, Сим 1 200 kg va yana 2 ta'."""
        parts = ["%s %s %s" % (n, _q(q), u) for n, q, u in items[:limit]]
        if len(items) > limit:
            parts.append("va yana %s ta" % (len(items) - limit))
        return ", ".join(parts)

    def _short(self, product):
        return product.product_tmpl_id.craf_litey_name or product.name

    # ------------------------------------------------------------------ forma uchun ma'lumot
    @api.model
    def form_options(self):
        """Kirim / ko'chirish / sanash varaqlari uchun: materiallar (joylar bo'yicha qoldiq bilan), joylar,
        yetkazib beruvchilar."""
        products = self._products()
        stock = defaultdict(dict)
        for product, location, qty in self.env["stock.quant"]._read_group(
                [("product_id", "in", products.ids), ("location_id.usage", "=", "internal"),
                 ("company_id", "in", [self.env.company.id, False])],
                ["product_id", "location_id"], ["quantity:sum"]):
            stock[product.id][location.id] = round(qty, 3)
        materials = [{
            "id": p.id, "name": p.name, "short": self._short(p), "code": p.default_code or "",
            "uom": self._uom(p), "kind": "aux" if p.craf_not_metal else "metal",
            "press_waste": p.craf_press_waste,
            "stock": stock.get(p.id, {}), "last_price": self._last_price(p),
        } for p in products]
        used = self.env["stock.picking"].search([
            ("picking_type_code", "=", "incoming"), ("partner_id", "!=", False),
            ("move_ids.product_id", "in", products.ids)], order="id desc", limit=200).partner_id
        partners = used | self.env["res.partner"].search([("supplier_rank", ">", 0)], limit=60)
        return {
            "today": fields.Date.to_string(fields.Date.context_today(self)),
            "materials": materials,
            "locations": [{"id": l.id, "name": l.name} for l in self._int_locations()],
            "litey_location_id": self._litey_location().id or False,
            "transfer_src_id": (self.env["craf.production.mixin"]._craf_loc("Xom-ashyo ombori")
                                or self.env["craf.production.mixin"]._craf_loc("Chiqindi")).id or False,
            "partners": sorted({p.name for p in partners if p.name}),
            "is_manager": self._is_editor(),
        }

    # ------------------------------------------------------------------ kirim
    @api.model
    def create_receipt(self, vals):
        """vals: date, vehicle, partner_name, location_id, note, lines: [{product_id, text, price}]"""
        self._check_editor()
        lines = []
        Product = self.env["product.product"]
        for row in vals.get("lines") or []:
            if not row.get("product_id"):
                continue
            product = Product.browse(int(row["product_id"]))
            if product.craf_press_waste:
                raise UserError("%s — press chiqindisi, kirim qilinmaydi (press smenasi yoki briketlashdan keladi)."
                                % product.name)
            qty = self._num(row.get("text"), product.name) or 0.0
            if qty <= EPS:
                continue
            lines.append(Command.create({
                "product_id": product.id, "qty_text": (row.get("text") or "").strip(), "qty": qty,
                "price_unit": max(float(row.get("price") or 0.0), 0.0),
            }))
        if not lines:
            raise UserError("Kamida bitta material va miqdor kiriting.")
        partner = self.env["res.partner"]
        name = (vals.get("partner_name") or "").strip()
        if name:
            partner = partner.search([("name", "=ilike", name)], limit=1) or partner.create(
                {"name": name, "supplier_rank": 1, "is_company": True})
        location = self.env["stock.location"].browse(int(vals.get("location_id") or 0)).exists() \
            or self._litey_location()
        wizard = self.env["craf.litey.kirim"].create({
            "date": vals.get("date") or fields.Date.context_today(self),
            "vehicle": (vals.get("vehicle") or "").strip().upper() or False,
            "partner_id": partner.id or False,
            "location_id": location.id,
            "note": (vals.get("note") or "").strip() or False,
            "line_ids": lines,
        })
        picking = wizard._craf_create_picking()
        return {"id": picking.id, "name": picking.name,
                "summary": self._sum_label([(m.quantity, self._uom(m.product_id)) for m in picking.move_ids])}

    # ------------------------------------------------------------------ ko'chirish
    @api.model
    def create_transfer(self, vals):
        """vals: date, location_id (qayerdan), location_dest_id (qayerga), note, lines: [{product_id, text}]"""
        self._check_editor()
        Location = self.env["stock.location"]
        src = Location.browse(int(vals.get("location_id") or 0)).exists()
        dst = Location.browse(int(vals.get("location_dest_id") or 0)).exists()
        if not src or not dst or src.usage != "internal" or dst.usage != "internal":
            raise UserError("Qayerdan va qayerga — ikkala joyni tanlang.")
        if src == dst:
            raise UserError("Qayerdan va qayerga bir xil joy bo'lishi mumkin emas.")
        needs = defaultdict(float)
        Product = self.env["product.product"]
        for row in vals.get("lines") or []:
            if not row.get("product_id"):
                continue
            product = Product.browse(int(row["product_id"]))
            qty = self._num(row.get("text"), product.name) or 0.0
            if qty > EPS:
                needs[product] += qty
        if not needs:
            raise UserError("Kamida bitta material va miqdor kiriting.")
        products = Product.concat(*needs.keys())
        moment = self._moment(vals.get("date"))
        self._check_lock(products, moment, "Ko'chirish")
        missing = []
        for product, qty in needs.items():
            have = product.with_context(location=src.id).qty_available
            if qty - have > EPS:
                missing.append("• %s: kerak %s, %s da bor %s %s" % (
                    product.name, _q(qty), src.name, _q(have), self._uom(product)))
        if missing:
            raise UserError("Qoldiq yetarli emas:\n%s" % "\n".join(missing))
        warehouse = src.warehouse_id or dst.warehouse_id or self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1)
        origin = "Литейка: ko'chirish"
        picking = self.env["stock.picking"].create({
            "picking_type_id": warehouse.int_type_id.id,
            "location_id": src.id,
            "location_dest_id": dst.id,
            "origin": origin,
            "move_ids": [Command.create({
                "product_id": product.id, "product_uom_qty": qty, "product_uom": product.uom_id.id,
                "location_id": src.id, "location_dest_id": dst.id, "origin": origin,
            }) for product, qty in needs.items()],
        })
        note = (vals.get("note") or "").strip()
        if note:
            picking.message_post(body=note)
        self._validate_picking(picking)
        if moment:
            picking.write({"date_done": moment, "scheduled_date": moment})
            picking.move_ids.write({"date": moment})
            picking.move_ids.move_line_ids.write({"date": moment})
        return {"id": picking.id, "name": picking.name,
                "summary": self._sum_label([(q, self._uom(p)) for p, q in needs.items()])}

    def _validate_picking(self, picking):
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.with_context(skip_backorder=True, picking_ids_not_to_backorder=picking.ids).button_validate()
        if picking.state != "done":
            raise UserError("%s bajarilmadi (holati: %s)." % (picking.name, picking.state))

    # ------------------------------------------------------------------ sanash
    def _count_moment(self, day):
        day = fields.Date.to_date(day) if day else fields.Date.context_today(self)
        if day > fields.Date.context_today(self):
            raise UserError("Kelajak sanasi bilan sanab bo'lmaydi.")
        return self._moment(day, time(23, 59))

    @api.model
    def count_load(self, count_id=False, location_id=False, date=False):
        """Sanash varag'i: joydagi har bir material uchun tizim qoldig'i va (qoralama bo'lsa) yozilgan miqdor."""
        Count = self.env["craf.litey.count"]
        count = Count.browse(int(count_id)).exists() if count_id else Count
        if count_id and not count:
            raise UserError("Sanash hujjati topilmadi.")
        location = count.location_id or self.env["stock.location"].browse(int(location_id or 0)).exists() \
            or self._litey_location()
        day = count.date or (fields.Date.to_date(date) if date else fields.Date.context_today(self))
        moment = self._count_moment(day) if count.state != "done" else count.done_date
        existing = {line.product_id.id: line for line in count.line_ids}
        products = self._products() | count.line_ids.product_id
        rows = []
        for p in products:
            line = existing.get(p.id)
            ctx = {"location": location.id}
            if moment:
                ctx["to_date"] = moment
            system = line.system_qty if (line and count.state == "done") else p.with_context(**ctx).qty_available
            here = abs(system) > EPS or p.product_tmpl_id.craf_litey_location_id == location
            rows.append({
                "product_id": p.id, "name": p.name, "short": self._short(p), "code": p.default_code or "",
                "uom": self._uom(p), "kind": "aux" if p.craf_not_metal else "metal",
                "system": round(system, 3), "here": bool(here or line),
                "text": (line.counted_text or (_q(line.counted_qty) if line.counted else "")) if line else "",
                "counted": bool(line and line.counted),
                "qty": line.counted_qty if line else 0.0,
                "diff": line.diff_qty if (line and count.state == "done") else 0.0,
            })
        rows.sort(key=lambda r: (not r["here"],))
        return {
            "id": count.id or False, "name": count.name or "", "state": count.state or "draft",
            "date": fields.Date.to_string(day), "location_id": location.id, "location": location.name,
            "note": count.note or "", "rows": rows,
            "moment_label": self._local(moment) if moment else "hozirgi holat",
            "locations": [{"id": l.id, "name": l.name} for l in self._int_locations()],
            "is_manager": self._is_editor(),
        }

    @api.model
    def count_save(self, vals, confirm=False):
        """vals: id?, date, location_id, note, lines: [{product_id, text}] (bo'sh text — sanalmagan)."""
        self._check_editor()
        Count = self.env["craf.litey.count"]
        count = Count.browse(int(vals["id"])).exists() if vals.get("id") else Count
        if vals.get("id") and not count:
            raise UserError("Sanash hujjati topilmadi.")
        if count and count.state != "draft":
            raise UserError("%s qoralama emas — o'zgartirib bo'lmaydi." % count.name)
        day = fields.Date.to_date(vals.get("date")) if vals.get("date") else fields.Date.context_today(self)
        self._count_moment(day)
        location = self.env["stock.location"].browse(int(vals.get("location_id") or 0)).exists() \
            or self._litey_location()
        Product = self.env["product.product"]
        wanted = {}
        for row in vals.get("lines") or []:
            text = (row.get("text") or "").strip()
            if not row.get("product_id") or not text:
                continue
            product = Product.browse(int(row["product_id"]))
            qty = self._num(text, product.name)
            if qty is None:
                continue
            if qty < 0:
                raise UserError("%s: sanalgan miqdor manfiy bo'lishi mumkin emas." % product.name)
            wanted[product.id] = (text, qty)
        header = {"date": day, "location_id": location.id, "note": (vals.get("note") or "").strip() or False}
        if not count:
            count = Count.create(header)
        else:
            count.write(header)
        commands = []
        for line in count.line_ids:
            if line.product_id.id in wanted:
                text, qty = wanted.pop(line.product_id.id)
                commands.append(Command.update(line.id, {"counted_text": text, "counted_qty": qty, "counted": True}))
            else:
                commands.append(Command.delete(line.id))
        seq = {p.id: i for i, p in enumerate(self._products(), 1)}
        for pid, (text, qty) in wanted.items():
            commands.append(Command.create({"product_id": pid, "counted_text": text, "counted_qty": qty,
                                            "counted": True, "sequence": seq.get(pid, 999)}))
        if commands:
            count.write({"line_ids": commands})
        message = ""
        if confirm:
            if self._is_editor():
                count.action_done()
            else:
                message = "Qoralama saqlandi. Qoldiqni tuzatishni rahbar tasdiqlaydi."
        return {"id": count.id, "name": count.name, "state": count.state, "message": message,
                "counted": count.counted_count, "diff": count.diff_count}

    # ------------------------------------------------------------------ jurnal
    def _doc(self, kind, model, rec_id, name, when_local, state, state_label, title, sub, **extra):
        return {
            "key": "%s-%s" % (model, rec_id), "kind": kind, "kind_label": DOC_KINDS[kind], "model": model,
            "id": rec_id, "name": name, "sort": when_local.strftime("%Y-%m-%d %H:%M:%S"),
            "date": when_local.strftime("%Y-%m-%d"), "date_label": when_local.strftime("%d.%m.%Y"),
            "time_label": when_local.strftime("%H:%M"), "state": state, "state_label": state_label,
            "title": title, "sub": sub, **extra,
        }

    def _to_local(self, dt):
        return pytz.utc.localize(dt).astimezone(self._tz()).replace(tzinfo=None)

    def _picking_kind(self, picking, litey_locs):
        if picking.return_id:
            # qaytarish asl hujjat turida ko'rinadi (kirim qaytarilsa — WH/OUT, lekin bu kirim tuzatilishi)
            return self._picking_kind(picking.return_id, litey_locs)
        code = picking.picking_type_code
        if code == "incoming":
            return "kirim"
        if code == "outgoing":
            return "chiqim"
        if code == "internal" and (picking.location_id.id in litey_locs or picking.location_dest_id.id in litey_locs
                                   or any(m.location_id.id in litey_locs or m.location_dest_id.id in litey_locs
                                          for m in picking.move_ids)):
            return "kochirish"
        return None

    def _picking_doc(self, picking, kind, pids):
        moves = picking.move_ids.filtered(lambda m: m.product_id.id in pids) or picking.move_ids
        when = picking.date_done if picking.state == "done" else picking.scheduled_date
        items, amount = [], 0.0
        for mv in moves:
            qty = mv.quantity if picking.state == "done" else mv.product_uom_qty
            items.append((self._short(mv.product_id), qty, self._uom(mv.product_id)))
            amount += (mv.craf_price or 0.0) * qty
        if picking.return_id:
            title = "Qaytarish: %s" % picking.return_id.name
        elif kind == "kirim":
            title = " · ".join(x for x in [picking.craf_vehicle, picking.partner_id.name] if x) or "Kirim"
        elif kind == "chiqim":
            title = picking.partner_id.name or "Chiqim"
        else:
            title = "%s → %s" % (picking.location_id.name, picking.location_dest_id.name)
        return self._doc(
            kind, "stock.picking", picking.id, picking.name, self._to_local(when or picking.create_date),
            picking.state, PICKING_STATES.get(picking.state, picking.state), title, self._items_label(items),
            total=self._sum_label([(q, u) for _n, q, u in items]), amount=round(amount, 2),
            origin=picking.origin or "", is_return=bool(picking.return_id))

    def _melt_doc(self, melt, stale_limit):
        when = self._to_local(self._utc(melt.date, time(12)))
        title = " · ".join(x for x in [melt.equipment_id.name, "%s-plavka" % melt.day_no if melt.day_no else ""] if x)
        if melt.charge_metal or melt.billet_qty:
            sub = "Metall %s kg → stalba %s kg" % (_q(melt.charge_metal), _q(melt.billet_qty))
            if melt.billet_qty:
                sub += " · угар %s%%" % fmt(melt.burn_loss_pct, 1)
        else:
            sub = "Shixta yozilmagan"
        stale = melt.state == "draft" and stale_limit and melt.date <= stale_limit
        return self._doc("plavka", "craf.foundry.melt", melt.id, melt.name, when, melt.state,
                         MELT_STATES.get(melt.state, melt.state), title or "Plavka", sub,
                         total="%s kg" % _q(melt.billet_qty) if melt.billet_qty else "",
                         balance=melt.balance_state, stale=bool(stale))

    def _count_doc(self, count):
        when = self._to_local(count.done_date) if count.done_date else self._to_local(self._utc(count.date, time(23, 59)))
        if count.state == "done":
            sub = "%s ta material, %s tasida farq" % (count.counted_count, count.diff_count)
        else:
            sub = "%s ta material yozilgan" % count.counted_count
        return self._doc("sanash", "craf.litey.count", count.id, count.name, when, count.state,
                         COUNT_STATES.get(count.state, count.state), count.location_id.name,
                         sub + (" · %s" % count.user_id.name if count.user_id else ""))

    @api.model
    def documents(self, date_from=None, date_to=None):
        """Davrdagi barcha Литейка hujjatlari (yangisi tepada)."""
        dfrom, dto = self._period(date_from, date_to)
        start, end = self._utc(dfrom), self._utc(dto + timedelta(days=1))
        products = self._all_litey_products()
        pids = set(products.ids)
        litey = self._litey_location()
        litey_locs = set(self.env["stock.location"].search([("id", "child_of", litey.id)]).ids) if litey else set()
        info = self._count_info()
        stale_limit = fields.Date.to_date(info["draft_limit"]) if info.get("draft_limit") else None
        docs = []
        for melt in self.env["craf.foundry.melt"].search([("date", ">=", dfrom), ("date", "<=", dto)]):
            docs.append(self._melt_doc(melt, stale_limit))
        pickings = self.env["stock.picking"].search([
            ("move_ids.product_id", "in", list(pids)), ("company_id", "=", self.env.company.id),
            "|", "&", ("state", "=", "done"), "&", ("date_done", ">=", start), ("date_done", "<", end),
            "&", ("state", "!=", "done"), "&", ("scheduled_date", ">=", start), ("scheduled_date", "<", end),
        ])
        for picking in pickings:
            kind = self._picking_kind(picking, litey_locs)
            if kind:
                docs.append(self._picking_doc(picking, kind, pids))
        counts = self.env["craf.litey.count"].search([("date", ">=", dfrom), ("date", "<=", dto)])
        for count in counts:
            docs.append(self._count_doc(count))
        # hujjatsiz inventarizatsiya (Excel qoldig'i, Odoo da qo'lda tuzatish) — nomi va kuni bo'yicha
        counted_moves = self.env["craf.litey.count"].search([("state", "=", "done")]).move_ids
        inv = self.env["stock.move"].search([
            ("is_inventory", "=", True), ("state", "=", "done"), ("product_id", "in", list(pids)),
            ("date", ">=", start), ("date", "<", end), ("id", "not in", counted_moves.ids)], order="date, id")
        groups = defaultdict(lambda: self.env["stock.move"])
        for mv in inv:
            groups[(mv.reference or "", self._to_local(mv.date).date())] |= mv
        for (ref, _day), moves in groups.items():
            plus = sum(m.quantity for m in moves if m.location_dest_id.usage == "internal")
            minus = sum(m.quantity for m in moves if m.location_id.usage == "internal")
            docs.append(self._doc(
                "tuzatish", "stock.move", moves[0].id, ref or "Qoldiq tuzatish", self._to_local(moves[-1].date),
                "done", "Bajarildi", "Hujjatsiz inventarizatsiya",
                "%s ta material · +%s / −%s" % (len(moves.product_id), _q(plus), _q(minus)),
                move_ids=moves.ids))
        docs.sort(key=lambda d: d["sort"], reverse=True)
        counts_by_kind = defaultdict(int)
        for d in docs:
            counts_by_kind[d["kind"]] += 1
        return {
            "date_from": fields.Date.to_string(dfrom), "date_to": fields.Date.to_string(dto),
            "docs": docs, "kinds": [{"key": k, "label": v, "count": counts_by_kind.get(k, 0)}
                                    for k, v in DOC_KINDS.items()],
            "drafts": sum(1 for d in docs if d["state"] == "draft"),
        }

    # ------------------------------------------------------------------ bitta hujjat
    @api.model
    def document_detail(self, model, res_id, move_ids=None):
        if model == "craf.foundry.melt":
            return self._melt_detail(self.env[model].browse(int(res_id)).exists())
        if model == "stock.picking":
            return self._picking_detail(self.env[model].browse(int(res_id)).exists())
        if model == "craf.litey.count":
            return self._count_detail(self.env[model].browse(int(res_id)).exists())
        if model == "stock.move":
            return self._inventory_detail(self.env[model].browse(move_ids or [int(res_id)]).exists())
        raise UserError("Noma'lum hujjat turi: %s" % model)

    def _not_found(self, rec):
        if not rec:
            raise UserError("Hujjat topilmadi (o'chirilgan bo'lishi mumkin).")

    def _melt_detail(self, melt):
        self._not_found(melt)
        info = self._count_info()
        stale = any(d["id"] == melt.id for d in info["stale_drafts"])
        lines = [{"name": self._short(l.product_id), "text": l.qty_text or "", "qty": l.qty, "uom": l.uom_name,
                  "metal": l.is_metal} for l in melt.line_ids.sorted(lambda l: (not l.is_metal, l.sequence, l.id))
                 if l.qty > EPS]
        outputs = [(n, q) for n, q in [("Stalba", melt.billet_qty), ("Сталба отход", melt.cut_waste_qty),
                                       ("Литейка отход", melt.foundry_waste_qty), ("Шлак", melt.slag_qty)] if q > EPS]
        return {
            "kind": "plavka", "kind_label": "Plavka", "model": "craf.foundry.melt", "id": melt.id, "name": melt.name,
            "state": melt.state, "state_label": MELT_STATES.get(melt.state, melt.state),
            "date_label": melt.date.strftime("%d.%m.%Y"),
            "meta": [m for m in [
                ("Pech", melt.equipment_id.name), ("Kun ichida №", str(melt.day_no) if melt.day_no else ""),
                ("Smena", dict(melt._fields["shift"].selection).get(melt.shift)),
                ("Mas'ul", melt.employee_id.name), ("Stalba uzunligi", "%s m" % fmt(melt.billet_length, 2)
                                                    if melt.billet_length else ""),
                ("Ishlab chiqarish", ", ".join(melt.production_ids.mapped("name"))),
                ("Avto ko'chirish", ", ".join(melt.picking_ids.mapped("name"))),
            ] if m[1]],
            "lines": [{"name": l["name"], "note": l["text"], "qty": l["qty"], "uom": l["uom"],
                       "group": "Shixta" if l["metal"] else "Sarf buyumlari"} for l in lines],
            "outputs": [{"name": n, "qty": q, "uom": "kg"} for n, q in outputs],
            "balance": {"metal": melt.charge_metal, "out": melt.output_total, "loss": melt.burn_loss_qty,
                        "pct": melt.burn_loss_pct, "state": melt.balance_state} if melt.charge_metal else False,
            "note": melt.balance_note or melt.note or "",
            "warning": ("Bu plavka sanasidan keyin qoldiq sanalgan («%s», %s): uning sarfi sanashga kirib bo'lgan. "
                        "Tasdiqlab bo'lmaydi — bekor qiling yoki sanasini to'g'rilang." % (
                            info["last_count"]["name"], info["last_count"]["label"])) if stale else "",
            "actions": [a for a, ok in [("open", True), ("cancel", melt.state == "draft"),
                                        ("draft", melt.state == "cancel"),
                                        ("delete", melt.state in ("draft", "cancel"))] if ok],
        }

    def _picking_detail(self, picking):
        self._not_found(picking)
        pids = set(self._all_litey_products().ids)
        litey = self._litey_location()
        litey_locs = set(self.env["stock.location"].search([("id", "child_of", litey.id)]).ids) if litey else set()
        kind = self._picking_kind(picking, litey_locs) or "kochirish"
        lines, amount = [], 0.0
        for mv in picking.move_ids:
            qty = mv.quantity if picking.state == "done" else mv.product_uom_qty
            price = mv.craf_price or 0.0
            amount += price * qty
            lines.append({"name": self._short(mv.product_id) if mv.product_id.id in pids else mv.product_id.name,
                          "qty": qty, "uom": self._uom(mv.product_id), "price": price,
                          "amount": round(price * qty, 2), "note": ""})
        when = picking.date_done if picking.state == "done" else picking.scheduled_date
        returns = picking.return_ids.filtered(lambda p: p.state != "cancel")
        can_return = (picking.state == "done" and kind in ("kirim", "kochirish") and not returns
                      and not picking.return_id)
        return {
            "kind": kind, "kind_label": DOC_KINDS[kind], "model": "stock.picking", "id": picking.id,
            "name": picking.name, "state": picking.state, "state_label": PICKING_STATES.get(picking.state, ""),
            "date_label": self._local(when) if when else "",
            "meta": [m for m in [
                ("Mashina", picking.craf_vehicle), ("Yetkazib beruvchi" if kind == "kirim" else "Mijoz",
                                                    picking.partner_id.name),
                ("Qayerdan", picking.location_id.name), ("Qayerga", picking.location_dest_id.name),
                ("Asos", picking.origin), ("Qaytarilgan hujjat", picking.return_id.name),
                ("Qaytarish", ", ".join(returns.mapped("name"))),
            ] if m[1]],
            "lines": lines, "amount": round(amount, 2), "outputs": [], "balance": False, "note": "", "warning": "",
            "actions": [a for a, ok in [("open", True), ("return", can_return)] if ok],
        }

    def _count_detail(self, count):
        self._not_found(count)
        lines = []
        for line in count.line_ids.filtered("counted"):
            lines.append({"name": self._short(line.product_id), "qty": line.counted_qty, "uom": line.uom_name,
                          "system": line.system_qty if count.state == "done" else None,
                          "diff": line.diff_qty if count.state == "done" else None, "note": line.counted_text or ""})
        manager = self._is_editor()
        return {
            "kind": "sanash", "kind_label": "Sanash", "model": "craf.litey.count", "id": count.id, "name": count.name,
            "state": count.state, "state_label": COUNT_STATES.get(count.state, ""),
            "date_label": count.date.strftime("%d.%m.%Y"),
            "meta": [m for m in [("Joy", count.location_id.name), ("Sanagan", count.user_id.name),
                                 ("Qoldiq vaqti", self._local(count.done_date) if count.done_date else ""),
                                 ("Izoh", count.note)] if m[1]],
            "lines": lines, "outputs": [], "balance": False, "note": "", "warning": "", "amount": 0,
            "is_count": True,
            "actions": [a for a, ok in [("edit", count.state == "draft"), ("done", count.state == "draft" and manager),
                                        ("cancel", count.state == "draft"), ("draft", count.state == "cancel"),
                                        ("delete", count.state in ("draft", "cancel")), ("open", True)] if ok],
        }

    def _inventory_detail(self, moves):
        self._not_found(moves)
        lines = []
        for mv in moves:
            sign = 1 if mv.location_dest_id.usage == "internal" else -1
            loc = mv.location_dest_id if sign > 0 else mv.location_id
            lines.append({"name": self._short(mv.product_id), "qty": sign * mv.quantity, "uom": self._uom(mv.product_id),
                          "note": loc.name})
        return {
            "kind": "tuzatish", "kind_label": "Tuzatish", "model": "stock.move", "id": moves[0].id,
            "move_ids": moves.ids, "name": moves[0].reference or "Qoldiq tuzatish", "state": "done",
            "state_label": "Bajarildi", "date_label": self._local(moves[-1].date),
            "meta": [("Turi", "Hujjatsiz inventarizatsiya (Excel qoldig'i yoki Odoo da qo'lda)"),
                     ("Kim", moves[0].create_uid.name)],
            "lines": lines, "outputs": [], "balance": False, "note": "", "warning": "", "amount": 0,
            "signed": True, "actions": ["open"],
        }

    @api.model
    def document_action(self, model, res_id, action):
        """Hujjat ustida amal: cancel, draft, delete, done (sanash), return (kirim / ko'chirish)."""
        self._check_editor()
        rec = self.env[model].browse(int(res_id)).exists()
        self._not_found(rec)
        name = rec.display_name
        if model in ("craf.foundry.melt", "craf.litey.count"):
            if action == "cancel":
                rec.action_cancel()
            elif action == "draft":
                rec.action_draft()
            elif action == "delete":
                if rec.state not in ("draft", "cancel"):
                    raise UserError("Faqat qoralama yoki bekor qilingan hujjat o'chiriladi.")
                rec.unlink()
                return {"result": "deleted", "name": name}
            elif action == "done" and model == "craf.litey.count":
                rec.action_done()
            else:
                raise UserError("Bu amal mumkin emas.")
            return {"result": action, "name": name, "state": rec.state}
        if model == "stock.picking" and action == "return":
            new = self._return_picking(rec)
            return {"result": "return", "name": name, "new_name": new.name}
        raise UserError("Bu amal mumkin emas.")

    def _return_picking(self, picking):
        if picking.state != "done":
            raise UserError("Faqat bajarilgan hujjat qaytariladi.")
        if picking.return_ids.filtered(lambda p: p.state != "cancel"):
            raise UserError("%s allaqachon qaytarilgan." % picking.name)
        missing = []
        for mv in picking.move_ids.filtered(lambda m: m.state == "done"):
            have = mv.product_id.with_context(location=mv.location_dest_id.id).qty_available
            qty = mv.product_uom._compute_quantity(mv.quantity, mv.product_id.uom_id)
            if qty - have > EPS:
                missing.append("• %s: qaytarish uchun %s kerak, %s da %s qolgan" % (
                    mv.product_id.name, _q(qty), mv.location_dest_id.name, _q(have)))
        if missing:
            raise UserError("Qaytarib bo'lmaydi — material ishlatilgan:\n%s" % "\n".join(missing))
        wizard = self.env["stock.return.picking"].with_context(
            active_id=picking.id, active_ids=picking.ids, active_model="stock.picking").create({"picking_id": picking.id})
        for line in wizard.product_return_moves:
            line.quantity = line.move_id.quantity
        new = wizard._create_return()
        self._validate_picking(new)
        picking.message_post(body="Qaytarildi: %s (Литейка hisobotidan)" % new.name)
        return new
