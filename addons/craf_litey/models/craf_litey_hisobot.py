from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL

from odoo.addons.craf_production.models.craf_production_mixin import fmt

MAX_DAYS = 93
PRODUCED_ROW = ("Ишлаб чикарилган литейка", 75)   # Excel dagi qator: kunlik chiqqan stalba
DAILY_PRODUCED_CODES = ("PF-14",)                  # Шлак — Excel da kunlik chiqish sifatida

# Harakat turlari (davr jadvali ustunlari)
KINDS = ["kirim", "chiqish_plavka", "chiqish_boshqa", "sarf_plavka", "sarf_boshqa", "tuzatish", "boshqa"]


class CrafLiteyHisobot(models.AbstractModel):
    _name = "craf.litey.hisobot"
    _description = "Литейка hisoboti: qoldiq, sarf, ishlab chiqarish, otxod"

    # ------------------------------------------------------------------ yordamchi
    def _tz(self):
        return pytz.timezone(self.env.user.tz or self.env.context.get("tz") or "Asia/Tashkent")

    def _utc(self, day, at=time.min):
        return self._tz().localize(datetime.combine(day, at)).astimezone(pytz.utc).replace(tzinfo=None)

    def _local(self, dt, pattern="%d.%m.%Y %H:%M"):
        return pytz.utc.localize(dt).astimezone(self._tz()).strftime(pattern) if dt else ""

    @api.model
    def _products(self, hidden=False):
        """Литейка materiallari (hisobot tartibida). hidden=True — ro'yxatdan chiqarilganlari."""
        products = self.env["product.product"].search(
            [("craf_litey_seq", ">", 0), ("craf_litey_hidden", "=", bool(hidden))])
        return products.sorted(lambda p: (p.craf_litey_seq, p.default_code or ""))

    @api.model
    def _is_editor(self):
        """Liteyka kirim-chiqimi, plavka, sanash va materiallarni yozuvchi (ombor mudiri).

        craf_sex da: faqat Omborchi va Direktor (sotuvchida ombor huquqi bo'lsa ham — faqat ko'radi)."""
        return self._is_editor()

    @api.model
    def _check_editor(self):
        if not self._is_editor():
            raise UserError("Liteyka kirim-chiqimini faqat ombor mudiri (Omborchi) yoki Direktor yozadi.")

    @api.model
    def _litey_location(self):
        return self.env["craf.production.mixin"]._craf_loc("Литейка")

    # ------------------------------------------------------------------ sana va qulf
    @api.model
    def _moment(self, day, at=time(12, 0)):
        """Hujjat sanasi → ombor harakati vaqti (UTC).

        Bugungi sana → None (harakat hozirgi vaqt bilan yoziladi). O'tgan kun → shu kunning `at` vaqti.
        Kelajak sanasi bilan yozib bo'lmaydi.
        """
        day = fields.Date.to_date(day) if day else None
        today = fields.Date.context_today(self)
        if not day or day == today:
            return None
        if day > today:
            raise UserError("Kelajak sanasi bilan yozib bo'lmaydi: %s." % day.strftime("%d.%m.%Y"))
        return self._utc(day, at)

    @api.model
    def _last_count_move(self, products=None, after=None):
        """Oxirgi qoldiq sanash (inventarizatsiya) harakati: Sanash hujjati, Excel qoldig'i yoki Odoo da qo'lda."""
        domain = [("is_inventory", "=", True), ("state", "=", "done"), ("company_id", "=", self.env.company.id)]
        if products is not None:
            domain.append(("product_id", "in", products.ids))
        if after:
            domain.append(("date", ">=", after))
        return self.env["stock.move"].search(domain, order="date desc, id desc", limit=1)

    @api.model
    def _check_lock(self, products, moment, what):
        """O'tgan sanaga yoziladigan harakatdan keyin qoldiq sanalgan bo'lsa — to'xtatadi.

        Sanashdan oldingi vaqtga harakat yozilsa, u sanalgan qoldiqqa ikkinchi marta qo'shiladi.
        """
        if not moment or not products:
            return
        move = self._last_count_move(products, moment)
        if not move:
            return
        raise UserError(
            "%s: %s sanasiga yozib bo'lmaydi.\n\n"
            "%s da «%s» qoldig'i sanalgan (%s). Bu sanagacha bo'lgan sarf va kirim o'sha sanashga kirib bo'lgan — "
            "yana yozilsa, ikki marta hisoblanadi.\n\n"
            "• Hujjat sanashdan keyin bo'lgan bo'lsa — sanasini o'zgartiring.\n"
            "• Sanashga kirgan bo'lsa — hujjatni bekor qiling." % (
                what, self._local(moment, "%d.%m.%Y"), self._local(move.date), move.product_id.display_name,
                move.reference or move.inventory_name or "inventarizatsiya"))

    def _uom(self, product):
        kg = self.env.ref("uom.product_uom_kgm", raise_if_not_found=False)
        unit = self.env.ref("uom.product_uom_unit", raise_if_not_found=False)
        if product.uom_id == kg:
            return "kg"
        if product.uom_id == unit:
            return "dona"
        return product.uom_id.name or ""

    def _excel_uom(self, product):
        return {"kg": "КГ", "dona": "ШТ", "рул": "РУЛ"}.get(self._uom(product), (product.uom_id.name or "").upper())

    @api.model
    def _period(self, date_from=None, date_to=None):
        today = fields.Date.context_today(self)
        dto = fields.Date.to_date(date_to) if date_to else today
        dfrom = fields.Date.to_date(date_from) if date_from else dto - timedelta(days=6)
        if dfrom > dto:
            dfrom, dto = dto, dfrom
        if (dto - dfrom).days >= MAX_DAYS:
            dfrom = dto - timedelta(days=MAX_DAYS - 1)
        return dfrom, dto

    @staticmethod
    def _kind(src, dst, melt_use, melt_out):
        """(tur, ishora): ichki joylar balansiga ta'siri."""
        if src == "internal":
            if dst == "production":
                return ("sarf_plavka" if melt_use else "sarf_boshqa"), -1
            if dst == "inventory":
                return "tuzatish", -1
            if dst == "supplier":
                return "kirim", -1
            return "boshqa", -1
        if src == "production":
            return ("chiqish_plavka" if melt_out else "chiqish_boshqa"), 1
        if src == "inventory":
            return "tuzatish", 1
        if src == "supplier":
            return "kirim", 1
        return "boshqa", 1

    def _flows(self, products, start):
        """{day: {product_id: {kind: imzoli miqdor}}} — start (UTC) dan keyingi bajarilgan tashqi harakatlar."""
        Melt = self.env["craf.foundry.melt"]
        field = Melt._fields["production_ids"]
        self.env["stock.move"].flush_model()
        Melt.flush_model(["production_ids"])
        melt_mos = SQL("(SELECT %s FROM %s)", SQL.identifier(field.column2), SQL.identifier(field.relation))
        self.env.cr.execute(SQL(
            """
            SELECT m.product_id, m.product_uom,
                   (m.date AT TIME ZONE 'UTC' AT TIME ZONE %(tz)s)::date,
                   ls.usage, ld.usage,
                   COALESCE(m.raw_material_production_id IN %(mos)s, FALSE),
                   COALESCE(m.production_id IN %(mos)s, FALSE),
                   SUM(m.quantity)
              FROM stock_move m
              JOIN stock_location ls ON ls.id = m.location_id
              JOIN stock_location ld ON ld.id = m.location_dest_id
             WHERE m.state = 'done'
               AND m.product_id = ANY(%(pids)s)
               AND m.date >= %(start)s
               AND m.company_id = %(cid)s
               AND (ls.usage = 'internal') <> (ld.usage = 'internal')
             GROUP BY 1, 2, 3, 4, 5, 6, 7
            """,
            tz=self._tz().zone, mos=melt_mos, pids=products.ids, start=start, cid=self.env.company.id,
        ))
        Product = self.env["product.product"]
        Uom = self.env["uom.uom"]
        flows = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        for pid, uom_id, day, src, dst, melt_use, melt_out, qty in self.env.cr.fetchall():
            product = Product.browse(pid)
            uom = Uom.browse(uom_id)
            if uom and uom != product.uom_id:
                qty = uom._compute_quantity(qty, product.uom_id)
            kind, sign = self._kind(src, dst, melt_use, melt_out)
            flows[day][pid][kind] += sign * (qty or 0.0)
        return flows

    def _on_hand(self, products):
        groups = self.env["stock.quant"]._read_group(
            [("product_id", "in", products.ids), ("location_id.usage", "=", "internal"),
             ("company_id", "in", [self.env.company.id, False])],
            ["product_id"], ["quantity:sum"])
        return {product.id: qty for product, qty in groups}

    def _by_location(self, products):
        """{product_id: [{id, name, qty}]} — hozirgi qoldiq joylar bo'yicha (0 bo'lmaganlari)."""
        groups = self.env["stock.quant"]._read_group(
            [("product_id", "in", products.ids), ("location_id.usage", "=", "internal"),
             ("company_id", "in", [self.env.company.id, False])],
            ["product_id", "location_id"], ["quantity:sum"])
        res = defaultdict(list)
        for product, location, qty in groups:
            if abs(qty) > 1e-6:
                res[product.id].append({"id": location.id, "name": location.name, "qty": round(qty, 3)})
        for rows in res.values():
            rows.sort(key=lambda r: -abs(r["qty"]))
        return res

    def _material_info(self, product):
        tmpl = product.product_tmpl_id
        return {
            "tmpl_id": tmpl.id,
            "kind": "aux" if tmpl.craf_not_metal else "metal",
            "melt": tmpl.craf_melt_seq > 0,
            "seq": tmpl.craf_litey_seq,
            "min_qty": tmpl.craf_min_qty,
            "main_location": tmpl.craf_litey_location_id.name or "",
        }

    def _count_info(self):
        """Oxirgi sanash va undan oldingi sanadagi qoralama plavkalar."""
        move = self._last_count_move(self._products() | self._products(hidden=True))
        if not move:
            return {"last_count": False, "stale_drafts": [], "draft_limit": False}
        day = pytz.utc.localize(move.date).astimezone(self._tz()).date()
        # Bugun sanalgan bo'lsa, bugungi plavka sanashdan keyin yoziladi; o'tgan kun sanalgan bo'lsa — o'sha kun ham yopiq
        limit = day - timedelta(days=1) if day >= fields.Date.context_today(self) else day
        stale = self.env["craf.foundry.melt"].search([("state", "=", "draft"), ("date", "<=", limit)], order="date, id")
        return {
            "last_count": {"label": self._local(move.date), "date": fields.Date.to_string(day),
                           "name": move.reference or move.inventory_name or ""},
            "stale_drafts": [{"id": m.id, "name": m.name, "date_label": m.date.strftime("%d.%m.%Y")} for m in stale],
            "draft_limit": fields.Date.to_string(limit),
        }

    # ------------------------------------------------------------------ asosiy
    @api.model
    def get_data(self, date_from=None, date_to=None):
        dfrom, dto = self._period(date_from, date_to)
        days = [dfrom + timedelta(days=i) for i in range((dto - dfrom).days + 1)]
        Melt = self.env["craf.foundry.melt"]
        products = self._products()
        billet = Melt._craf_product("XA-09")
        all_products = products | billet
        start, end = self._utc(dfrom), self._utc(dto + timedelta(days=1))

        flows = self._flows(all_products, start)
        on_hand = self._on_hand(all_products)
        by_loc = self._by_location(products)

        def net(day, pid):
            return sum(flows.get(day, {}).get(pid, {}).values())

        # kun oxiridagi qoldiq: hozirgi qoldiqdan keyingi harakatlarni ayirib, orqaga yuramiz
        closing = {}
        for product in all_products:
            pid = product.id
            after = sum(net(d, pid) for d in flows if d > dto)
            value = on_hand.get(pid, 0.0) - after
            for day in reversed(days):
                closing[(day, pid)] = value
                value -= net(day, pid)
            closing[(dfrom - timedelta(days=1), pid)] = value

        # 1) davr harakati
        movement = []
        for product in products:
            pid = product.id
            row = {k: 0.0 for k in KINDS}
            for day in days:
                for kind, qty in flows.get(day, {}).get(pid, {}).items():
                    row[kind] += qty
            row["sarf_plavka"] = -row["sarf_plavka"] + 0.0
            row["sarf_boshqa"] = -row["sarf_boshqa"] + 0.0
            opening = closing[(dfrom - timedelta(days=1), pid)]
            close = closing[(dto, pid)]
            min_qty = product.craf_min_qty
            movement.append({
                "product_id": pid, "code": product.default_code or "", "name": product.name,
                "excel_name": product.craf_litey_name or product.name, "uom": self._uom(product),
                "opening": round(opening, 2), "closing": round(close, 2),
                **{k: round(v, 2) for k, v in row.items()},
                "min_qty": min_qty, "low": bool(min_qty) and close < min_qty, "negative": close < -1e-6,
                "on_hand": round(on_hand.get(pid, 0.0), 3), "locs": by_loc.get(pid, []),
                **self._material_info(product),
            })

        # 2) kunlik jadval (Excel Лист1 ko'rinishi)
        matrix = []
        seqs = []
        for product in products:
            produced = (product.default_code or "") in DAILY_PRODUCED_CODES
            values = [round(flows.get(d, {}).get(product.id, {}).get("chiqish_plavka", 0.0), 2) if produced
                      else round(closing[(d, product.id)], 2) for d in days]
            seqs.append((product.craf_litey_seq, {
                "key": "p%s" % product.id, "product_id": product.id,
                "label": product.craf_litey_name or product.name, "uom": self._excel_uom(product),
                "kind": "produced" if produced else "balance", "values": values,
            }))
        if billet:
            label, seq = PRODUCED_ROW
            seqs.append((seq, {
                "key": "produced", "product_id": billet.id, "label": label, "uom": "КГ", "kind": "produced",
                "values": [round(flows.get(d, {}).get(billet.id, {}).get("chiqish_plavka", 0.0), 2) for d in days],
            }))
        matrix = [row for _seq, row in sorted(seqs, key=lambda s: s[0])]

        # 3) plavkalar
        melts = Melt.search([("date", ">=", dfrom), ("date", "<=", dto), ("state", "!=", "cancel")],
                            order="date, equipment_id, day_no, id")
        used = melts.line_ids.filtered(lambda l: l.qty > 1e-6).product_id
        used = used.sorted(lambda p: (p.craf_melt_seq or 999, p.default_code or ""))
        metal_cols = [{"product_id": p.id, "name": p.name, "short": p.craf_litey_name or p.name,
                       "uom": self._uom(p)} for p in used if not p.craf_not_metal]
        aux_cols = [{"product_id": p.id, "name": p.name, "short": p.craf_litey_name or p.name,
                     "uom": self._uom(p)} for p in used if p.craf_not_metal]
        melt_rows = []
        for m in melts:
            qty, text = defaultdict(float), {}
            for line in m.line_ids:
                qty[line.product_id.id] += line.qty
                if line.qty_text:
                    text[line.product_id.id] = line.qty_text
            melt_rows.append({
                "id": m.id, "name": m.name, "date": fields.Date.to_string(m.date),
                "date_label": m.date.strftime("%d.%m"), "pech": m.equipment_id.name or "", "day_no": m.day_no,
                "state": m.state, "qty": {str(k): round(v, 2) for k, v in qty.items()},
                "text": {str(k): v for k, v in text.items()},
                "charge_metal": round(m.charge_metal, 1), "billet_qty": round(m.billet_qty, 1),
                "billet_length": m.billet_length, "billet_count": m.billet_count,
                "cut_waste_qty": round(m.cut_waste_qty, 1), "foundry_waste_qty": round(m.foundry_waste_qty, 1),
                "slag_qty": round(m.slag_qty, 1), "output_total": round(m.output_total, 1),
                "loss_qty": round(m.burn_loss_qty, 1), "loss_pct": round(m.burn_loss_pct, 2),
                "balance_state": m.balance_state, "note": m.balance_note or "",
            })

        done = melts.filtered(lambda m: m.state == "done")
        metal = sum(done.mapped("charge_metal"))
        loss = sum(done.mapped("burn_loss_qty"))
        kpi = {
            "melts": len(done), "drafts": len(melts) - len(done),
            "metal": round(metal, 1), "billet": round(sum(done.mapped("billet_qty")), 1),
            "waste": round(sum(done.mapped("waste_total")), 1), "slag": round(sum(done.mapped("slag_qty")), 1),
            "loss": round(loss, 1), "loss_pct": round(loss / metal * 100.0, 2) if metal else 0.0,
        }

        # 4) kirimlar
        receipts = []
        moves = self.env["stock.move"].search([
            ("state", "=", "done"), ("date", ">=", start), ("date", "<", end),
            ("product_id", "in", products.ids), ("picking_id.picking_type_id.code", "=", "incoming"),
        ], order="date, id")
        tz = self._tz()
        for mv in moves:
            local = pytz.utc.localize(mv.date).astimezone(tz)
            qty = mv.product_uom._compute_quantity(mv.quantity, mv.product_id.uom_id)
            receipts.append({
                "picking_id": mv.picking_id.id, "name": mv.picking_id.name, "date_label": local.strftime("%d.%m.%Y"),
                "vehicle": mv.picking_id.craf_vehicle or "", "partner": mv.picking_id.partner_id.name or "",
                "product": mv.product_id.name, "qty": round(qty, 2), "uom": self._uom(mv.product_id),
                "price": mv.craf_price or 0.0, "amount": round((mv.craf_price or 0.0) * qty, 2),
            })

        today = fields.Date.context_today(self)
        return {
            "date_from": fields.Date.to_string(dfrom), "date_to": fields.Date.to_string(dto),
            "label": "%s — %s" % (dfrom.strftime("%d.%m.%Y"), dto.strftime("%d.%m.%Y")) if dfrom != dto
            else dfrom.strftime("%d.%m.%Y"),
            "days": [{"date": fields.Date.to_string(d), "label": d.strftime("%d.%m"),
                      "weekday": d.weekday(), "full": d.strftime("%d.%m.%Y")} for d in days],
            "today": fields.Date.to_string(today),
            "movement": movement,
            "low_count": sum(1 for r in movement if r["low"]),
            "negative_count": sum(1 for r in movement if r["negative"]),
            "matrix": matrix,
            "melts": melt_rows, "metal_cols": metal_cols, "aux_cols": aux_cols,
            "kpi": kpi,
            "receipts": receipts,
            "receipt_total": round(sum(r["amount"] for r in receipts), 2),
            "drafts_total": Melt.search_count([("state", "=", "draft")]),
            "count_drafts": self.env["craf.litey.count"].search_count([("state", "=", "draft")]),
            "is_manager": self._is_editor(),
            **self._count_info(),
        }

    # ------------------------------------------------------------------ tugmalar
    @api.model
    def action_open_moves(self, product_id, date_from=None, date_to=None):
        dfrom, dto = self._period(date_from, date_to)
        product = self.env["product.product"].browse(product_id)
        action = self.env["ir.actions.act_window"]._for_xml_id("stock.stock_move_line_action")
        action.update({
            "name": "%s — harakat" % product.display_name,
            "domain": [("product_id", "=", product.id), ("state", "=", "done"),
                       ("date", ">=", self._utc(dfrom)), ("date", "<", self._utc(dto + timedelta(days=1)))],
            "context": {"create": False},
        })
        return action

    @api.model
    def action_inventory(self):
        action = self.env["stock.quant"].action_view_inventory()
        action["domain"] = [("product_id", "in", self._products().ids), ("location_id.usage", "=", "internal")]
        action["name"] = "Литейка: qoldiqni sanash va tuzatish"
        return action
