"""Diller portali server qismi. Barcha metodlar _api_ bilan boshlanadi va faqat controller orqali chaqiriladi
(RPC dan yopiq). Har bir chaqiruv _me() dan o'tadi: foydalanuvchi faqat o'z kompaniyasining ma'lumotini ko'radi,
narx va miqdor serverda hisoblanadi, brauzerdan kelgan narxga ishonilmaydi."""
import base64
import secrets
from datetime import timedelta

from odoo import fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.image import binary_to_image, image_process

from odoo.addons.craf_pul.models.sale_order import PRICE_MIN
from odoo.addons.craf_sotuv.models import parser as P
from odoo.addons.craf_sotuv.models.sale_order_line import packs_text
from odoo.addons.craf_telegram.models.craf_telegram import P_BOT

from .craf_diller_return import REASONS, STATES as RETURN_STATES

API = {
    "init", "catalog", "search", "favorite", "submit", "update", "cancel", "truck", "request", "repeat",
    "orders", "order", "stats", "notices", "notices_seen", "telegram", "finance",
    "return_info", "return_save", "returns",
}
MAX_PHOTOS = 5
EPS = 1e-6


class CrafDiller(models.AbstractModel):
    _name = "craf.diller"
    _description = "Diller portali"

    # ------------------------------------------------------------------ kirish
    def _me(self):
        user = self.env.user
        dealer = user.partner_id.commercial_partner_id
        if not user.share or not dealer.craf_is_diller:
            raise AccessError("Portal faqat dillerlar uchun.")
        if dealer.craf_diller_blocked:
            raise UserError("Akkaunt bloklangan. Zavod bilan bog'laning.")
        return user, dealer.sudo()

    def _craf_call(self, method, params):
        if method not in API:
            raise AccessError("Noma'lum amal.")
        user, dealer = self._me()
        return getattr(self, "_api_" + method)(user, dealer, **(params or {}))

    def _order_of(self, dealer, order_id):
        order = self.env["sale.order"].sudo().browse(int(order_id or 0)).exists()
        if not order or order.partner_id.commercial_partner_id != dealer:
            raise UserError("Buyurtma topilmadi.")
        return order

    def _date(self, value):
        return value.strftime("%d.%m.%Y") if value else ""

    def _time(self, value, fmt="%d.%m.%Y %H:%M"):
        return self.env["craf.sotuv"]._utc_to_local_str(value, fmt) if value else ""

    # ------------------------------------------------------------------ boshlang'ich
    def _api_init(self, user, dealer):
        company = self.env.company
        return {
            "user": user.name, "dealer": dealer.name, "uid": user.id, "company": company.name,
            "currency": company.currency_id.symbol or company.currency_id.name,
            "reasons": [{"id": k, "label": v} for k, v in REASONS],
            "unread": self._unread(user, dealer),
            "telegram": bool(user.partner_id.sudo().craf_telegram_id),
            "today": fields.Date.to_string(fields.Date.context_today(self)),
        }

    # ------------------------------------------------------------------ katalog
    def _prices(self, dealer, products):
        pricelist = dealer.property_product_pricelist
        if pricelist:
            return pricelist._get_products_price(products, quantity=1.0)
        return {p.id: p.lst_price for p in products}

    def _levels(self, products):
        """Mavjudlik darajasi: aniq son brauzerga chiqmaydi."""
        Sotuv = self.env["craf.sotuv"]
        low = int(self.env["ir.config_parameter"].sudo().get_param("craf_diller.low_packs", 5) or 5)
        free = {}
        for loc in Sotuv._locations():
            for pid, qty in Sotuv._free_qty(products, loc).items():
                free[pid] = free.get(pid, 0.0) + max(qty, 0.0)
        levels = {}
        for product in products:
            qty = free.get(product.id, 0.0)
            per = product.craf_pcs_per_pack or 1
            levels[product.id] = "ko'p" if qty >= low * per else ("kam" if qty > 0 else "yo'q")
        return levels

    def _top_ids(self, dealer, limit=20):
        rows = self.env["sale.order.line"].sudo()._read_group(
            [("order_partner_id", "=", dealer.id), ("state", "=", "sale"), ("display_type", "=", False)],
            ["product_id"], ["product_uom_qty:sum"], order="product_uom_qty:sum desc", limit=limit)
        return [p.id for p, _qty in rows if p]

    def _api_catalog(self, user, dealer):
        Sotuv = self.env["craf.sotuv"]
        products = self.env["product.product"].search(Sotuv._finished_domain(), order="default_code, name")
        prices = self._prices(dealer, products)
        levels = self._levels(products)
        favorites = set(dealer.craf_favorite_ids.ids)
        top = self._top_ids(dealer)
        rows = []
        for p in products:
            tmpl = p.product_tmpl_id
            section = tmpl.craf_section_id
            price = prices.get(p.id, 0.0)
            rows.append({
                "id": p.id, "code": p.default_code or "", "name": p.name,
                "type": section.profile_type or "Boshqa", "series": section.series or "",
                "color": tmpl.craf_color_id.name or "", "length": tmpl.craf_length_m or 0.0,
                "per_pack": tmpl.craf_pcs_per_pack or 0, "kg_pc": tmpl.craf_kg_per_pc or 0.0,
                "price": price if price > PRICE_MIN else 0.0, "level": levels[p.id],
                "favorite": p.id in favorites, "top": p.id in top,
                "image": bool(p.image_128 or section.drawing),
            })
        return {"rows": rows, "top": top}

    def _alias_match(self, row, entry):
        if entry["kind"] == "product":
            return row["product"].id == entry.get("product_id")
        if entry.get("type") and P.norm(entry["type"]) != row["type"]:
            return False
        if entry.get("family_type") and P.norm(entry["family_type"]) != row["type"]:
            return False
        if entry.get("series") and row["series"] not in [P.norm(s) for s in entry["series"]]:
            return False
        if entry.get("color") and entry["color"] != row["color"]:
            return False
        if entry.get("length") and abs(entry["length"] - row["length"]) > 0.01:
            return False
        if entry.get("filter") and not self.env["craf.sotuv"]._tok_match(row, [P.norm(w) for w in entry["filter"]]):
            return False
        return True

    def _api_search(self, user, dealer, query=""):
        """Oddiy so'z va qisqartmalar lug'ati: «TB oq», «Kraf antrasid L»."""
        Sotuv = self.env["craf.sotuv"]
        words = P.tokens(query)
        if not words:
            return []
        entries = {}
        for entry in self.env["craf.sotuv.alias"].sudo()._craf_entries():
            if entry["kind"] in ("item", "group", "product"):
                entries.setdefault(entry["key"], entry)
        checks, i = [], 0
        while i < len(words):
            pair = P.compact("".join(words[i:i + 2])) if i + 1 < len(words) else ""
            if pair and pair in entries:
                checks.append((None, entries[pair]))
                i += 2
                continue
            checks.append((words[i], entries.get(P.compact(words[i]))))
            i += 1
        found = []
        for row in Sotuv._catalog():
            for word, entry in checks:
                if not ((word and Sotuv._tok_match(row, [word])) or (entry and self._alias_match(row, entry))):
                    break
            else:
                found.append(row["product"].id)
        return found

    def _api_favorite(self, user, dealer, product_id, on=True):
        self._product(product_id)
        dealer.craf_favorite_ids = [(4 if on else 3, int(product_id))]
        return True

    def _product(self, product_id):
        product = self.env["product.product"].browse(int(product_id or 0)).exists()
        if not product or not product.filtered_domain(self.env["craf.sotuv"]._finished_domain()):
            raise UserError("Mahsulot topilmadi.")
        return product

    # ------------------------------------------------------------------ buyurtma
    def _int(self, value):
        try:
            number = int(value or 0)
        except (TypeError, ValueError):
            raise UserError("Miqdor butun son bo'lishi kerak.") from None
        if number < 0:
            raise UserError("Miqdor manfiy bo'lishi mumkin emas.")
        return number

    def _line_cmds(self, lines):
        """Faqat mahsulot va miqdor olinadi — narxni Odoo narxlar ro'yxatidan o'zi hisoblaydi."""
        cmds = {}
        for row in lines or []:
            product = self._product(row.get("id"))
            packs, extra = self._int(row.get("packs")), self._int(row.get("extra"))
            if packs and not product.craf_pcs_per_pack:
                raise UserError("%s: «dona / pachka» kiritilmagan — miqdorni donada yozing." % product.display_name)
            cmds[product.id] = cmds.get(product.id, 0) + packs * (product.craf_pcs_per_pack or 0) + extra
        cmds = [(0, 0, {"product_id": pid, "product_uom_qty": pcs, "craf_diller_qty": pcs})
                for pid, pcs in cmds.items() if pcs]
        if not cmds:
            raise UserError("Savat bo'sh.")
        return cmds

    def _order_vals(self, data):
        """Olish joyini diller tanlamaydi: uni sotuvchi yoki yuklovchi belgilaydi."""
        need = fields.Date.to_date(data.get("need_date")) if data.get("need_date") else False
        if need and need < fields.Date.context_today(self):
            raise UserError("Kerakli sana o'tib ketgan.")
        return {
            "craf_need_date": need,
            "craf_truck": (data.get("truck") or "").strip() or False,
            "craf_load_note": (data.get("note") or "").strip()[:250] or False,
        }

    def _api_submit(self, user, dealer, data):
        key = "dl-%s" % (data.get("key") or secrets.token_hex(8))
        Order = self.env["sale.order"].sudo()
        same = Order.search([("craf_source_key", "=", key), ("partner_id", "=", dealer.id)], limit=1)
        if same:  # internet uzilib, qayta bosilgan
            return self._order_row(same)
        vals = self._order_vals(data)
        vals.update({
            "partner_id": dealer.id, "craf_portal": True, "craf_diller_user_id": user.id, "craf_source_key": key,
            "require_signature": False, "require_payment": False, "order_line": self._line_cmds(data.get("lines")),
        })
        order = Order.create(vals)
        order._craf_after_submit()
        return self._order_row(order)

    def _editable(self, order):
        return order.craf_portal and order.state == "draft" \
            and order.craf_approval in ("submitted", "credit")

    def _api_update(self, user, dealer, order_id, data):
        order = self._order_of(dealer, order_id)
        if not self._editable(order):
            raise UserError("%s tasdiqlangan — o'zgartirish faqat so'rov orqali." % order.name)
        vals = self._order_vals(data)
        vals["order_line"] = [(5, 0, 0)] + self._line_cmds(data.get("lines"))
        order.write(vals)
        order._craf_after_submit(is_new=False)
        return self._order_row(order)

    def _api_cancel(self, user, dealer, order_id):
        order = self._order_of(dealer, order_id)
        if not self._editable(order):
            raise UserError("%s tasdiqlangan — bekor qilish faqat so'rov orqali." % order.name)
        order.with_context(craf_no_push=True).action_cancel()
        order.message_post(body="Diller bekor qildi: %s" % user.name)
        order._craf_seller_notify("Diller buyurtmani bekor qildi", "%s · %s" % (order.name, dealer.name))
        return self._order_row(order)

    def _api_truck(self, user, dealer, order_id, truck):
        order = self._order_of(dealer, order_id)
        if order.state == "cancel" or order.craf_load_state == "done":
            raise UserError("Bu buyurtmada mashinani o'zgartirib bo'lmaydi.")
        order.craf_truck = (truck or "").strip() or False
        return {"truck": order.craf_truck or ""}

    def _api_request(self, user, dealer, order_id, text):
        order = self._order_of(dealer, order_id)
        text = (text or "").strip()[:250]
        if not text:
            raise UserError("So'rov matnini yozing.")
        if order.state == "cancel" or order.craf_load_state == "done":
            raise UserError("Bu buyurtma yopilgan.")
        order.craf_change_request = text
        order._craf_seller_notify("Diller so'rovi", "%s · %s: %s" % (order.name, dealer.name, text))
        return True

    def _api_repeat(self, user, dealer, order_id):
        """Takrorlash: katalogda hali bor mahsulotlar savatga, qolganlari ro'yxatda."""
        order = self._order_of(dealer, order_id)
        domain = self.env["craf.sotuv"]._finished_domain()
        rows, missing = [], []
        for line in order.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty > 0):
            product = line.product_id
            if not product.filtered_domain(domain):
                missing.append(product.name)
                continue
            per, pcs = product.craf_pcs_per_pack, int(round(line.product_uom_qty))
            packs, extra = divmod(pcs, per) if per else (0, pcs)
            rows.append({"id": product.id, "packs": packs, "extra": extra})
        return {"lines": rows, "missing": missing}

    # ------------------------------------------------------------------ tarix
    def _order_row(self, order):
        code, label = order._craf_diller_status()
        lines = order.order_line.filtered(lambda l: not l.display_type)
        priced = lines.filtered(lambda l: l.price_unit > PRICE_MIN)
        return {
            "id": order.id, "name": order.name, "status": code, "status_label": label,
            "date": self._time(order.date_order), "packs": order.craf_total_packs, "pcs": order.craf_total_pcs,
            "kg": round(order.craf_total_kg, 1), "amount": sum(priced.mapped("price_total")),
            "unpriced": len(lines) - len(priced),
            "truck": order.craf_truck or "",
        }

    def _api_orders(self, user, dealer, status="", date_from=None, date_to=None, product="", limit=100):
        domain = [("partner_id", "=", dealer.id), ("state", "!=", "sent")]
        if date_from:
            domain.append(("date_order", ">=", fields.Date.to_date(date_from)))
        if date_to:
            domain.append(("date_order", "<", fields.Date.to_date(date_to) + timedelta(days=1)))
        if product:
            domain.append(("order_line.product_id.name", "ilike", product))
        orders = self.env["sale.order"].sudo().search(domain, order="date_order desc, id desc",
                                                      limit=min(int(limit or 100), 300))
        rows = [self._order_row(o) for o in orders]
        return [r for r in rows if not status or r["status"] == status]

    def _steps(self, order):
        code = order._craf_diller_status()[0]
        confirmed = order.state == "sale"
        return [
            {"label": "Yuborildi", "time": self._time(order.create_date), "done": True},
            {"label": "Zavod tasdiqladi", "time": self._time(order.craf_approved_date or order.craf_sent_date),
             "done": confirmed},
            {"label": "Yuklanmoqda", "time": self._time(order.craf_load_start),
             "done": code in ("loading", "partial", "done")},
            {"label": "Berildi", "time": self._time(order.craf_given_date), "done": code == "done"},
        ]

    def _api_order(self, user, dealer, order_id):
        order = self._order_of(dealer, order_id)
        lines = []
        for line in order.order_line.filtered(lambda l: not l.display_type):
            per = line.product_id.craf_pcs_per_pack
            wanted = line.craf_diller_qty
            rest = max(line.product_uom_qty - line.qty_delivered, 0.0) if order.state == "sale" else 0.0
            lines.append({
                "id": line.id, "product_id": line.product_id.id, "product": line.product_id.name,
                "code": line.product_id.default_code or "", "per_pack": per or 0,
                "packs": line.craf_packs, "extra": line.craf_extra,
                "text": line.craf_packs_text, "kg": round(line.craf_kg, 1),
                "price": line.price_unit if line.price_unit > PRICE_MIN else 0.0, "total": line.price_total,
                "changed": packs_text(wanted, per) if wanted and abs(wanted - line.product_uom_qty) > EPS else "",
                "delivered": packs_text(line.qty_delivered, per) if line.qty_delivered else "",
                "rest": packs_text(rest, per) if line.qty_delivered and rest > EPS else "",
            })
        invoices = order.invoice_ids.filtered(lambda m: m.state == "posted")
        row = self._order_row(order)
        row.update({
            "lines": lines, "steps": self._steps(order), "note": order.craf_load_note or "",
            "need_date": fields.Date.to_string(order.craf_need_date) if order.craf_need_date else "",
            "by": order.craf_diller_user_id.name or "", "reject_note": order.craf_reject_note or "",
            "request": order.craf_change_request or "",
            "credit_note": order.craf_credit_note or "",
            "photos": [{"id": a.id} for a in order.craf_truck_photo_ids.sorted("id")],
            "invoices": [{"id": m.id, "name": m.name, "amount": m.amount_total, "refund": m.move_type == "out_refund"}
                         for m in invoices],
            "returns": self._return_rows(self.env["craf.diller.return"].sudo().search([("order_id", "=", order.id)])),
            "can_edit": self._editable(order),
            "can_request": order.state == "sale" and order.craf_load_state != "done",
            "can_truck": order.state != "cancel" and order.craf_load_state != "done",
            "can_return": order.state == "sale" and any(
                l.qty_delivered > EPS for l in order.order_line),
        })
        return row

    # ------------------------------------------------------------------ moliya
    def _api_finance(self, user, dealer, date_from=None, date_to=None):
        detail = self.env["craf.pul"].partner_detail(dealer.id, "customer", date_from or False, date_to or False)
        payments = [r for r in detail["rows"] if r["payment_id"]][:10]
        exposure = dealer._craf_exposure()
        limit = dealer.craf_credit_limit
        return {
            "debt": detail["current"], "limit": limit, "exposure": exposure,
            "free": max(limit - exposure, 0.0) if limit else 0.0,
            "date_from": detail["date_from"], "date_to": detail["date_to"],
            "opening": detail["opening"], "closing": detail["closing"], "plus": detail["plus"],
            "minus": detail["minus"], "payments": payments,
            "rows": [{k: r[k] for k in ("date", "name", "label", "amount", "balance")} for r in detail["rows"]],
        }

    def _api_stats(self, user, dealer):
        since = fields.Date.context_today(self).replace(day=1) - timedelta(days=330)
        lines = self.env["sale.order.line"].sudo().search([
            ("order_partner_id", "=", dealer.id), ("state", "=", "sale"), ("display_type", "=", False),
            ("craf_date", ">=", since), ("qty_delivered", ">", 0)])
        months, products = {}, {}
        for line in lines:
            key = self._time(line.craf_date, "%Y-%m")
            kg = line.qty_delivered * (line.product_id.craf_kg_per_pc or 0.0)
            amount = line.qty_delivered * line.price_unit
            month = months.setdefault(key, {"month": key, "kg": 0.0, "pcs": 0.0, "amount": 0.0})
            month["kg"] += kg
            month["pcs"] += line.qty_delivered
            month["amount"] += amount
            row = products.setdefault(line.product_id.id, {"name": line.product_id.name, "kg": 0.0, "pcs": 0.0})
            row["kg"] += kg
            row["pcs"] += line.qty_delivered
        return {
            "months": [months[k] for k in sorted(months)],
            "top": sorted(products.values(), key=lambda r: -r["pcs"])[:10],
        }

    # ------------------------------------------------------------------ qaytarish
    def _return_rows(self, records):
        states = dict(RETURN_STATES)
        reasons = dict(REASONS)
        return [{
            "id": r.id, "name": r.name, "order": r.order_id.name, "order_id": r.order_id.id, "state": r.state,
            "state_label": states[r.state], "reason": reasons.get(r.reason), "date": self._time(r.create_date),
            "reject_note": r.reject_note or "",
            "lines": [{"product": l.product_id.name, "text": l.qty_text} for l in r.line_ids],
        } for r in records]

    def _returnable(self, order):
        """{qator: qaytarsa bo'ladigan dona} — berilgan, ochiq so'rovlarga kirmagan."""
        pending = self.env["craf.diller.return.line"].sudo().search(
            [("return_id.order_id", "=", order.id), ("return_id.state", "in", ("new", "approved"))])
        out = {}
        for line in order.order_line.filtered(lambda l: not l.display_type and l.product_id.is_storable):
            out[line] = line.qty_delivered - sum(pending.filtered(lambda p: p.sale_line_id == line).mapped("qty"))
        return out

    def _api_return_info(self, user, dealer, order_id):
        order = self._order_of(dealer, order_id)
        lines = [{
            "id": line.id, "product": line.product_id.name, "per_pack": line.product_id.craf_pcs_per_pack or 0,
            "max": qty, "max_text": packs_text(qty, line.product_id.craf_pcs_per_pack),
        } for line, qty in self._returnable(order).items() if qty > EPS]
        return {"id": order.id, "name": order.name, "lines": lines}

    def _photo(self, data):
        """Telefon rasmi: faqat haqiqiy rasm qabul qilinadi va kichraytiriladi."""
        data = data.split(",", 1)[1] if "," in data[:100] else data
        if len(data) > 20 * 1024 * 1024:
            raise UserError("Rasm juda katta.")
        try:
            raw = base64.b64decode(data)
            fmt = (binary_to_image(raw).format or "").upper()
        except Exception:  # noqa: BLE001
            raise UserError("Bu rasm emas.") from None
        if fmt not in ("JPEG", "PNG", "WEBP", "MPO"):
            raise UserError("Rasm turi qo'llanmaydi (%s)." % (fmt or "?"))
        return image_process(raw, size=(1920, 1920), quality=82, output_format="JPEG")

    def _api_return_save(self, user, dealer, order_id, data):
        order = self._order_of(dealer, order_id)
        if order.state != "sale":
            raise UserError("Faqat berilgan buyurtmadan qaytarish mumkin.")
        if data.get("reason") not in dict(REASONS):
            raise UserError("Sababni tanlang.")
        # qaytgan mahsulot tushadigan joyni sotuvchi so'rovda o'zgartirishi mumkin
        location = order.craf_location_id or self.env.company.craf_sale_location_id
        allowed = self._returnable(order)
        cmds = []
        for row in data.get("lines") or []:
            line = order.order_line.filtered(lambda l: l.id == int(row.get("id") or 0))
            if not line:
                raise UserError("Qator topilmadi.")
            qty = self._int(row.get("packs")) * (line.product_id.craf_pcs_per_pack or 0) + self._int(row.get("extra"))
            if not qty:
                continue
            if qty - allowed.get(line, 0.0) > EPS:
                raise UserError("%s: qaytarish berilgandan ko'p bo'lishi mumkin emas." % line.product_id.name)
            cmds.append((0, 0, {"sale_line_id": line.id, "qty": qty}))
        if not cmds:
            raise UserError("Qaytariladigan miqdorni yozing.")
        photos = (data.get("photos") or [])[:MAX_PHOTOS]
        rec = self.env["craf.diller.return"].sudo().create({
            "order_id": order.id, "partner_id": dealer.id, "user_id": user.id, "reason": data["reason"],
            "note": (data.get("note") or "").strip()[:250] or False, "location_id": location.id, "line_ids": cmds,
        })
        atts = self.env["ir.attachment"].sudo().create([{
            "name": "%s-%s.jpg" % (rec.name, i + 1), "raw": self._photo(p), "mimetype": "image/jpeg",
            "res_model": rec._name, "res_id": rec.id,
        } for i, p in enumerate(photos)])
        rec.photo_ids = [(6, 0, atts.ids)]
        order._craf_seller_notify("Qaytarish so'rovi", "%s · %s · %s" % (rec.name, dealer.name, order.name))
        return self._return_rows(rec)[0]

    def _api_returns(self, user, dealer):
        return self._return_rows(self.env["craf.diller.return"].sudo().search(
            [("partner_id", "=", dealer.id)], limit=100))

    # ------------------------------------------------------------------ xabarlar
    def _unread(self, user, dealer):
        return self.env["craf.diller.notice"].sudo().search_count(
            [("partner_id", "=", dealer.id), ("id", ">", user.sudo().craf_notice_seen_id)])

    def _api_notices(self, user, dealer):
        seen = user.sudo().craf_notice_seen_id
        notices = self.env["craf.diller.notice"].sudo().search([("partner_id", "=", dealer.id)], limit=50)
        return {"unread": self._unread(user, dealer), "rows": [{
            "id": n.id, "title": n.title, "body": n.body or "", "time": self._time(n.create_date),
            "order_id": n.order_id.id or False, "new": n.id > seen,
        } for n in notices]}

    def _api_notices_seen(self, user, dealer):
        last = self.env["craf.diller.notice"].sudo().search([("partner_id", "=", dealer.id)], limit=1)
        if last:
            user.sudo().craf_notice_seen_id = last.id
        return True

    def _api_telegram(self, user, dealer):
        TG = self.env["craf.telegram"].sudo()
        bot = TG._param(P_BOT)
        if not bot and TG._token():
            bot = TG.check_bot()
        if not bot:
            raise UserError("Telegram bot hali sozlanmagan.")
        token = secrets.token_urlsafe(16)
        user.partner_id.sudo().craf_telegram_token = token
        return {"url": "https://t.me/%s?start=d_%s" % (bot, token)}
