"""Craf → Sotuv sahifasi (telefon uchun) server qismi."""
import base64
import uuid
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.image import binary_to_image, image_process

from . import parser as P
from .sale_order_line import packs_text


class CrafSotuv(models.AbstractModel):
    _name = "craf.sotuv"
    _description = "Craf sotuv sahifasi"

    # ------------------------------------------------------------------ rollar
    def _is_seller(self):
        return self.env.user.has_group("craf_sotuv.group_craf_seller")

    def _is_loader(self):
        return self.env.user.has_group("craf_sotuv.group_craf_loader")

    def _check_seller(self):
        if not self._is_seller():
            raise AccessError("Bu amal faqat sotuvchi uchun.")

    def _check_loader(self):
        if not self._is_loader():
            raise AccessError("Bu amal faqat yuklovchi yoki sotuvchi uchun.")

    # ------------------------------------------------------------------ yordamchi
    def _tz(self):
        return pytz.timezone(self.env.user.tz or self.env.context.get("tz") or "Asia/Tashkent")

    def _local_to_utc(self, value):
        """'2026-10-06 12:43:33' (mahalliy) -> UTC naive datetime."""
        if not value:
            return False
        if isinstance(value, datetime):
            dt = value
        else:
            value = str(value).replace("T", " ")[:19]
            fmt = "%Y-%m-%d %H:%M:%S" if len(value) > 16 else "%Y-%m-%d %H:%M"
            dt = datetime.strptime(value, fmt)
        return self._tz().localize(dt).astimezone(pytz.utc).replace(tzinfo=None)

    def _utc_to_local_str(self, value, fmt="%Y-%m-%d %H:%M"):
        if not value:
            return ""
        return pytz.utc.localize(value).astimezone(self._tz()).strftime(fmt)

    def _day_bounds(self, day):
        start = self._tz().localize(datetime.combine(day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        return start, start + timedelta(days=1)

    def _locations(self):
        locs = self.env["stock.location"].search(
            [("craf_sale_point", "=", True), ("usage", "=", "internal")], order="craf_sale_sequence, id")
        default = self.env.company.craf_sale_location_id
        if default and default not in locs:
            locs = default | locs
        return locs

    def _location(self, location_id):
        loc = self.env["stock.location"].browse(int(location_id or 0)).exists()
        return loc or self.env.company.craf_sale_location_id or self._locations()[:1]

    def _finished_domain(self):
        domain = [("sale_ok", "=", True), ("is_storable", "=", True)]
        categ = self.env.ref("craf_nomenklatura.categ_finished", raise_if_not_found=False)
        if categ:
            domain += ["|", ("categ_id", "child_of", categ.id), ("craf_section_id", "!=", False)]
        else:
            domain += [("craf_section_id", "!=", False)]
        return domain

    def _free_qty(self, products, location):
        if not products or not location:
            return {}
        return {p.id: p.free_qty for p in products.with_context(location=location.id)}

    def _product_info(self, product, avail=None):
        tmpl = product.product_tmpl_id
        info = {
            "id": product.id,
            "code": product.default_code or "",
            "name": product.name,
            "per_pack": tmpl.craf_pcs_per_pack or 0,
            "kg_pc": tmpl.craf_kg_per_pc or 0.0,
            "color": tmpl.craf_color_id.name or "",
            "length": tmpl.craf_length_m or 0.0,
        }
        if avail is not None:
            info["avail"] = avail
            info["avail_text"] = packs_text(avail, info["per_pack"]) if avail >= 0 else "%s dona" % int(avail)
        return info

    # ------------------------------------------------------------------ katalog va qidiruv
    def _catalog(self):
        rows = []
        products = self.env["product.product"].search(self._finished_domain())
        for p in products:
            tmpl = p.product_tmpl_id
            section = tmpl.craf_section_id
            color = tmpl.craf_color_id
            text = " ".join(filter(None, [section.name, p.name, p.default_code]))
            rows.append({
                "product": p,
                "type": P.norm(section.profile_type),
                "series": P.norm(section.series),
                "color": color.id or None,
                "painted": bool(color and color.is_painted),
                "length": round(tmpl.craf_length_m or 0.0, 2),
                "tokens": P.tokens(text.replace("(", " ").replace(")", " ")),
            })
        return rows

    @staticmethod
    def _tok_match(row, words):
        return all(any(t.startswith(w) for t in row["tokens"]) for w in words if w)

    def _resolve(self, line, catalog, learned):
        """Qator -> (mahsulot, holat, izoh, takliflar)."""
        hit = learned.get(line["learn_key"])
        if hit:
            product = self.env["product.product"].browse(hit["product_id"]).exists()
            if product:
                return product, "ok", "o'rgatilgan", []
        if not line["type"]:
            words = [w for w in P.tokens(line["raw"]) if any(c.isdigit() for c in w) and not w.isdigit()]
            sugg = [r["product"] for r in catalog if words and self._tok_match(r, words)][:8]
            return False, "error", "Qisqartma tanilmadi — mahsulotni tanlang", sugg
        ltype = P.norm(line["type"])
        cands = [r for r in catalog if r["type"] == ltype]
        if line["filter"]:
            cands = [r for r in cands if self._tok_match(r, [P.norm(w) for w in line["filter"]])]
        if not cands:
            return False, "error", "«%s» turida mahsulot topilmadi" % line["type"], []
        length = line["length"] or 6.0
        by_len = [r for r in cands if abs(r["length"] - length) < 0.01]
        if not by_len and not line["length"]:
            by_len = cands  # faqat 5 m bo'lgan tur (Самлед Техно)
        if not by_len:
            return False, "error", "%s m uzunlikda yo'q" % P.compact(str(length)), [r["product"] for r in cands][:8]
        cands = by_len

        def color_filter(rows):
            if not rows:
                return []
            if not line["color"]:
                return rows
            exact = [r for r in rows if r["color"] == line["color"]]
            if exact:
                return exact
            if all(not r["painted"] for r in rows):
                return rows  # Прижим, Соединитель, Ёлка — bo'yalmagan holda sotiladi
            return []

        series_opts = [P.norm(s) for s in line["series"]] or [""]
        if line["series"] and not line.get("series_strict"):
            series_opts.append("")
        found, note = [], ""
        for i, series in enumerate(series_opts):
            found = color_filter([r for r in cands if r["series"] == series])
            if found:
                missed = [s for s in series_opts[:i] if any(r["series"] == s for r in cands)]
                if i and series == "" and missed:
                    note = "%s seriyasida bu rang yo'q — standart olindi" % " / ".join(line["series"])
                break
        if not found and not line["series"]:
            found = color_filter(cands)  # seriyasiz yozilgan, faqat seriyali mahsulot bor
        if len(found) == 1:
            return found[0]["product"], "ok", note, []
        if found:
            return False, "error", "Bir nechta mos keldi — aniqlang", [r["product"] for r in found][:8]
        sugg = [r for r in cands if not line["color"] or r["color"] == line["color"]] or cands
        return False, "error", "Rang yoki seriya bo'yicha topilmadi", [r["product"] for r in sugg][:8]

    def _partner_info(self, name, learned_partners):
        name = (name or "").strip()
        Partner = self.env["res.partner"]
        if not name:
            return {"partner": None, "is_new": True, "suggestions": []}
        hit = learned_partners.get(P.compact(name))
        partner = Partner.browse(hit["partner_id"]).exists() if hit else Partner
        if not partner:
            partner = Partner.search([("name", "=ilike", name)], limit=1)
        if partner:
            return {"partner": {"id": partner.id, "name": partner.name}, "is_new": False, "suggestions": []}
        first = name.split()[0]
        sugg = Partner.search([("name", "ilike", first), ("is_company", "in", [True, False])], limit=5)
        return {"partner": None, "is_new": True,
                "suggestions": [{"id": p.id, "name": p.name} for p in sugg]}

    # ------------------------------------------------------------------ sahifa API
    @api.model
    def get_init(self):
        self._check_loader()
        company = self.env.company
        return {
            "locations": [{"id": l.id, "label": l._craf_sale_label(), "name": l.complete_name}
                          for l in self._locations()],
            "default_location_id": company.craf_sale_location_id.id or False,
            "settings": {
                "allow_negative": company.craf_sale_allow_negative,
                "use_price": company.craf_sale_use_price,
                "location_id": company.craf_sale_location_id.id or False,
                "use_scan": company.craf_sale_use_scan,
            },
            "is_manager": self.env.user.has_group("sales_team.group_sale_manager"),
            "is_seller": self._is_seller(),
            "is_loader": self._is_loader(),
            "user": self.env.user.name,
            "today": fields.Date.to_string(fields.Date.context_today(self)),
            "queue_count": self.env["sale.order"].sudo().search_count(self._queue_domain()),
            "trucks": self._recent_trucks(),
        }

    def _recent_trucks(self, limit=40):
        self.env.cr.execute("""
            SELECT craf_truck FROM sale_order
             WHERE craf_truck IS NOT NULL AND craf_truck != ''
             GROUP BY craf_truck ORDER BY max(id) DESC LIMIT %s""", (limit,))
        return [r[0] for r in self.env.cr.fetchall()]

    @api.model
    def save_settings(self, vals):
        if not self.env.user.has_group("sales_team.group_sale_manager"):
            raise UserError("Sozlamalarni faqat sotuv rahbari o'zgartira oladi.")
        company = self.env.company
        write = {}
        if "allow_negative" in vals:
            write["craf_sale_allow_negative"] = bool(vals["allow_negative"])
        if "use_price" in vals:
            write["craf_sale_use_price"] = bool(vals["use_price"])
        if "use_scan" in vals:
            write["craf_sale_use_scan"] = bool(vals["use_scan"])
        if vals.get("location_id"):
            write["craf_sale_location_id"] = int(vals["location_id"])
        company.sudo().write(write)
        return self.get_init()

    @api.model
    def parse(self, text=None, messages=None, location_id=None):
        """Yozilgan buyurtma matni -> qoralama buyurtma kartochkalari (ko'rib chiqish uchun)."""
        self._check_seller()
        Alias = self.env["craf.sotuv.alias"]
        entries = Alias._craf_entries()
        dictionary = P.Dictionary(entries)
        learned = dictionary.by_kind.get("product", {})
        learned_partners = dictionary.by_kind.get("partner", {})
        default_loc = self._location(location_id)
        blocks = []
        if text:
            blocks += P.parse_text(text, dictionary, default_location=default_loc.id)
        for msg in messages or []:
            blocks += P.parse_text(msg.get("text") or "", dictionary, default_location=default_loc.id,
                                   default_date=msg.get("date"))
        catalog = self._catalog()
        keys = [b["key"] for b in blocks]
        existing = {o.craf_source_key: o for o in self.env["sale.order"].search(
            [("craf_source_key", "in", keys), ("state", "!=", "cancel")])} if keys else {}
        orders = []
        for block in blocks:
            loc = self._location(block["location"])
            lines = []
            for line in block["lines"]:
                product, status, msg, sugg = self._resolve(line, catalog, learned)
                lines.append({
                    "uid": uuid.uuid4().hex[:10],
                    "raw": line["raw"],
                    "packs": line["packs"],
                    "extra": line["extra"],
                    "product_id": product.id if product else False,
                    "parsed_product_id": product.id if product else False,
                    "status": status,
                    "msg": msg or line.get("note") or "",
                    "learn_key": line["learn_key"],
                    "suggestion_ids": [p.id for p in sugg],
                    "pack_ids": [],
                })
            dup = existing.get(block["key"]) if block["date"] else False  # faqat vaqtli matn (eski import)
            pinfo = self._partner_info(block["customer"], learned_partners)
            orders.append({
                "key": block["key"],
                "date": (block["date"] or "")[:16],
                "raw": block["raw"],
                "customer": block["customer"] or "",
                "partner": pinfo["partner"],
                "partner_is_new": pinfo["is_new"],
                "partner_suggestions": pinfo["suggestions"],
                "location_id": loc.id,
                "notes": block["notes"],
                "lines": lines,
                "duplicate": {"id": dup.id, "name": dup.name} if dup else False,
            })
        product_ids = set()
        for o in orders:
            for l in o["lines"]:
                product_ids.update(filter(None, [l["product_id"]] + l["suggestion_ids"]))
        return {"orders": orders, "products": self._products_payload(product_ids, orders)}

    def _products_payload(self, product_ids, orders=None, location_ids=None):
        """{product_id: info, avail: {location_id: qty}}."""
        products = self.env["product.product"].browse(list(product_ids)).exists()
        locs = set(location_ids or [])
        for o in orders or []:
            locs.add(o["location_id"])
        payload = {p.id: self._product_info(p) for p in products}
        for loc in self.env["stock.location"].browse(list(locs)).exists():
            for pid, qty in self._free_qty(products, loc).items():
                payload[pid].setdefault("avail", {})[loc.id] = qty
        # barcha sotuv joylarida (yuklovchi bir nechta joydan yuklashi mumkin)
        for loc in self._locations():
            for pid, qty in self._free_qty(products, loc).items():
                payload[pid]["avail_all"] = payload[pid].get("avail_all", 0.0) + max(qty, 0.0)
        return payload

    @api.model
    def stock_info(self, product_ids, location_id):
        self._check_loader()
        loc = self._location(location_id)
        return self._products_payload(set(product_ids or []), location_ids=[loc.id])

    @api.model
    def search_products(self, query="", location_id=None, limit=40):
        self._check_loader()
        loc = self._location(location_id)
        domain = self._finished_domain()
        words = P.tokens(query or "")
        products = self.env["product.product"].search(domain, order="default_code, name")
        if words:
            catalog = {r["product"].id: r for r in self._catalog()}
            products = products.filtered(lambda p: p.id in catalog and self._tok_match(catalog[p.id], words))
        products = products[:limit]
        free = self._free_qty(products, loc)
        rows = [self._product_info(p, free.get(p.id, 0.0)) for p in products]
        totals = {}
        for point in self._locations():
            for pid, qty in self._free_qty(products, point).items():
                totals[pid] = totals.get(pid, 0.0) + max(qty, 0.0)
        for row in rows:
            row["avail_all"] = totals.get(row["id"], 0.0)
        return rows

    @api.model
    def search_partners(self, query="", limit=8):
        self._check_seller()
        query = (query or "").strip()
        domain = [("name", "ilike", query)] if query else [("customer_rank", ">", 0)]
        partners = self.env["res.partner"].search(domain, limit=limit, order="customer_rank desc, name")
        return [{"id": p.id, "name": p.name} for p in partners]

    @api.model
    def scan(self, code, location_id=None):
        """QR / pachka raqami yoki mahsulot kodi -> qator uchun ma'lumot."""
        self._check_loader()
        loc = self._location(location_id)
        code = (code or "").strip()
        if not code:
            raise UserError("Kod bo'sh.")
        pack = self.env["craf.pack"]._craf_find(code)
        if pack:
            warn = ""
            if pack.craf_state == "sold":
                raise UserError("%s pachka allaqachon sotilgan (%s, %s)." % (
                    pack.name, pack.sold_partner_id.name or "", pack.sale_order_id.name or ""))
            if pack.location_id and loc and not (pack.location_id == loc or pack.location_id.parent_path.startswith(
                    loc.parent_path)):
                warn = "Pachka joyi: %s" % pack.location_id.name
            per = pack.product_id.craf_pcs_per_pack
            full = per and pack.pcs == per
            free = self._free_qty(pack.product_id, loc)
            return {
                "pack": {"id": pack.id, "name": pack.name, "pcs": pack.pcs},
                "product": self._product_info(pack.product_id, free.get(pack.product_id.id, 0.0)),
                "packs": 1 if full else 0,
                "extra": 0 if full else pack.pcs,
                "warn": warn,
            }
        short = code.rstrip("/").rsplit("/", 1)[-1].strip()
        product = self.env["product.product"].search(
            ["|", ("default_code", "=ilike", short), ("barcode", "=", short)], limit=1)
        if not product:
            raise UserError("«%s» — bunday pachka yoki mahsulot kodi topilmadi." % code)
        free = self._free_qty(product, loc)
        return {"pack": False, "product": self._product_info(product, free.get(product.id, 0.0)),
                "packs": 1, "extra": 0, "warn": ""}

    # ------------------------------------------------------------------ Berildi
    def _learn(self, order, partner):
        Alias = self.env["craf.sotuv.alias"].sudo()
        name = (order.get("customer") or "").strip()
        if partner and name and P.compact(name) != P.compact(partner.name):
            key = P.compact(name)
            alias = Alias.with_context(active_test=False).search([("kind", "=", "partner"), ("key", "=", key)],
                                                                 limit=1)
            if alias:
                alias.write({"partner_id": partner.id, "active": True})
            else:
                Alias.create({"kind": "partner", "name": name, "key": key, "partner_id": partner.id})
        for line in order.get("lines") or []:
            pid = int(line.get("product_id") or 0)
            key = line.get("learn_key")
            if not pid or not key or pid == int(line.get("parsed_product_id") or 0):
                continue
            alias = Alias.with_context(active_test=False).search([("kind", "=", "product"), ("key", "=", key)],
                                                                 limit=1)
            vals = {"product_id": pid, "active": True}
            if alias:
                alias.write(vals)
            else:
                Alias.create(dict(vals, kind="product", key=key, name=line.get("raw") or key,
                                  note="Sotuv sahifasida tanlangan"))

    def _make_order(self, order, deliver=True):
        Product = self.env["product.product"]
        company = self.env.company
        loc = self._location(order.get("location_id"))
        if order.get("partner_id"):
            partner = self.env["res.partner"].browse(int(order["partner_id"])).exists()
        else:
            partner = self.env["res.partner"]
        name = (order.get("customer") or "").strip()
        if not partner:
            if not name:
                raise UserError("Mijoz nomi yozilmagan.")
            partner = self.env["res.partner"].search([("name", "=ilike", name)], limit=1) or \
                self.env["res.partner"].create({"name": name, "customer_rank": 1})
        key = order.get("key") or False
        if key and not order.get("force"):
            dup = self.env["sale.order"].search([("craf_source_key", "=", key), ("state", "!=", "cancel")], limit=1)
            if dup:
                raise UserError("Bu buyurtma allaqachon kiritilgan: %s." % dup.name)
        line_vals, packs_by_product = [], {}
        for line in order.get("lines") or []:
            product = Product.browse(int(line.get("product_id") or 0)).exists()
            packs, extra = int(line.get("packs") or 0), int(line.get("extra") or 0)
            if not product:
                if packs or extra:
                    raise UserError("«%s» qatoriga mahsulot tanlanmagan." % (line.get("raw") or "?"))
                continue
            if packs < 0 or extra < 0:
                raise UserError("%s: manfiy miqdor bo'lmaydi." % product.display_name)
            per = product.craf_pcs_per_pack
            if packs and not per:
                raise UserError("%s: «dona / pachka» kiritilmagan — miqdorni donada yozing." % product.display_name)
            pcs = packs * per + extra
            if not pcs:
                continue
            vals = {"product_id": product.id, "product_uom_qty": pcs, "craf_source_line": line.get("raw") or False}
            if not company.craf_sale_use_price:
                vals["price_unit"] = 0.0
            line_vals.append((0, 0, vals))
            if line.get("pack_ids"):
                packs_by_product.setdefault(product.id, []).extend(int(i) for i in line["pack_ids"])
        if not line_vals:
            raise UserError("Mahsulot qatori yo'q.")
        vals = {
            "partner_id": partner.id,
            "craf_location_id": loc.id,
            "craf_source_key": key,
            "craf_source_text": order.get("raw") or False,
            "craf_load_note": (order.get("note") or "").strip() or False,
            "craf_truck": (order.get("truck") or "").strip() or False,
            "order_line": line_vals,
        }
        if not deliver:
            so = self.env["sale.order"].create(vals)
            so.action_confirm()  # band qilinadi va yuklovchilar navbatiga tushadi
            return so, partner
        given = self._local_to_utc(order.get("date")) or fields.Datetime.now()
        if given > fields.Datetime.now() + timedelta(minutes=5):
            given = fields.Datetime.now()
        vals.update({"craf_given_date": given, "date_order": given})
        so = self.env["sale.order"].create(vals)
        so.action_craf_berildi()
        if packs_by_product:
            for line in so.order_line:
                ids = packs_by_product.get(line.product_id.id)
                if ids:
                    self.env["craf.pack"].browse(ids).exists().write({
                        "sale_line_id": line.id, "sold_date": given, "location_id": False})
        return so, partner

    @api.model
    def berildi(self, orders):
        """Sotuvchi o'zi yukladi: darhol beriladi. Har bir sotuv alohida bajariladi."""
        return self._create_orders(orders, deliver=True)

    @api.model
    def send(self, orders):
        """Yuklovchiga yuborish: buyurtma tasdiqlanadi, mahsulot band qilinadi, Yuklash navbatiga tushadi."""
        return self._create_orders(orders, deliver=False)

    def _create_orders(self, orders, deliver):
        self._check_seller()
        results = []
        for order in orders or []:
            partner = self.env["res.partner"].browse(int(order.get("partner_id") or 0)).exists()
            self._learn(order, partner)
            try:
                with self.env.cr.savepoint():
                    so, partner = self._make_order(order, deliver=deliver)
                results.append({"key": order.get("key"), "ok": True, "order": self._order_card(so)})
            except UserError as e:
                self.env.invalidate_all()
                results.append({"key": order.get("key"), "ok": False, "error": str(e.args[0] if e.args else e)})
        return results

    # ------------------------------------------------------------------ Sotuvlar va Qoldiq
    def _order_card(self, so):
        when = so.craf_given_date or so.craf_sent_date or so.date_order
        lines = so.order_line.filtered(lambda l: not l.display_type)
        moves = so._craf_open_pickings().move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        sent = so.craf_sent_date or so.date_order
        labels = dict(so._fields["craf_load_state"].selection)
        partial = so.delivery_status == "partial"
        return {
            "load_state": so.craf_load_state,
            "load_label": "Qisman berildi" if partial and so.craf_load_state == "queue" else labels.get(
                so.craf_load_state, ""),
            "partial": partial,
            "loader": so.craf_loader_id.name or "",
            "is_mine": bool(so.craf_loader_id) and so.craf_loader_id == self.env.user,
            "accepted_time": self._utc_to_local_str(so.craf_load_start, "%H:%M")
            if so.craf_load_state == "loading" and so.craf_load_start else "",
            "seller": so.user_id.name or so.create_uid.name or "",
            "note": so.craf_load_note or "",
            "location_id": so.craf_location_id.id,
            "sent_time": self._utc_to_local_str(sent, "%H:%M") if sent else "",
            "age_min": int((fields.Datetime.now() - sent).total_seconds() // 60) if sent else 0,
            "progress": {"done": len(set(self.env["craf.load.alloc"].sudo().search(
                [("move_id", "in", moves.ids), ("qty", ">", 0)]).mapped("move_id").ids)), "total": len(moves)},
            "truck": so.craf_truck or "",
            "photos": self._photo_list(so),
            "given_time": self._utc_to_local_str(so.craf_given_date, "%H:%M") if so.craf_given_date else "",
            "id": so.id,
            "name": so.name,
            "partner": so.partner_id.name,
            "location": so.craf_location_id._craf_sale_label() if so.craf_location_id else "",
            "time": self._utc_to_local_str(when, "%H:%M"),
            "date": self._utc_to_local_str(when, "%d.%m.%Y"),
            "delivered": so.delivery_status == "full",
            "state": so.state,
            "c1": so.c1_state,
            "pcs": so.craf_total_pcs,
            "packs": so.craf_total_packs,
            "kg": round(so.craf_total_kg, 1),
            "lines": [{
                "product": l.product_id.name,
                "code": l.product_id.default_code or "",
                "text": l.craf_packs_text,
                "pcs": l.product_uom_qty,
                "delivered": l.qty_delivered,
                "delivered_text": packs_text(l.qty_delivered, l.product_id.craf_pcs_per_pack) if l.qty_delivered else "",
                "kg": round(l.craf_kg, 1),
                "raw": l.craf_source_line or "",
            } for l in lines],
        }

    @api.model
    def day_sales(self, day=None):
        self._check_loader()
        day = fields.Date.to_date(day) if day else fields.Date.context_today(self)
        start, end = self._day_bounds(day)
        orders = self.env["sale.order"].sudo().search([
            ("state", "=", "sale"), "|", "|",
            "&", ("craf_given_date", ">=", start), ("craf_given_date", "<", end),
            "&", ("craf_sent_date", ">=", start), ("craf_sent_date", "<", end),
            "&", "&", ("craf_given_date", "=", False), ("date_order", ">=", start), ("date_order", "<", end),
        ], order="craf_given_date desc, craf_sent_date desc, date_order desc, id desc")
        totals = {}
        for line in orders.order_line.filtered(lambda l: not l.display_type and l.product_id.is_storable):
            row = totals.setdefault(line.product_id, [0.0, 0.0])
            row[0] += line.product_uom_qty
            row[1] += line.craf_kg
        products = [{
            "id": p.id, "code": p.default_code or "", "name": p.name,
            "text": packs_text(qty, p.craf_pcs_per_pack), "pcs": qty, "kg": round(kg, 1),
        } for p, (qty, kg) in sorted(totals.items(), key=lambda kv: (kv[0].default_code or "", kv[0].name))]
        return {
            "date": fields.Date.to_string(day),
            "date_label": day.strftime("%d.%m.%Y"),
            "prev": fields.Date.to_string(day - timedelta(days=1)),
            "next": fields.Date.to_string(day + timedelta(days=1)),
            "is_today": day == fields.Date.context_today(self),
            "orders": [self._order_card(o) for o in orders],
            "products": products,
            "total_pcs": sum(orders.mapped("craf_total_pcs")),
            "total_packs": sum(orders.mapped("craf_total_packs")),
            "total_kg": round(sum(orders.mapped("craf_total_kg")), 1),
            "c1_new": len(orders.filtered(lambda o: o.c1_state == "new" and o.delivery_status == "full")),
            "waiting": len(orders.filtered(lambda o: o.craf_load_state in ("queue", "loading"))),
        }

    @api.model
    def mark_c1(self, day=None):
        self._check_seller()
        data = self.day_sales(day)
        orders = self.env["sale.order"].browse([o["id"] for o in data["orders"] if o["delivered"]])
        orders = orders.filtered(lambda o: o.c1_state == "new")
        orders.action_c1_done()
        return len(orders)

    @api.model
    def berildi_existing(self, order_id):
        self._check_seller()
        so = self.env["sale.order"].browse(int(order_id)).exists()
        if not so:
            raise UserError("Buyurtma topilmadi.")
        so.action_craf_berildi()
        return self._order_card(so)

    @api.model
    def stock_list(self, location_id=None, query="", show_all=False):
        self._check_loader()
        loc = self._location(location_id)
        products = self.env["product.product"].search(self._finished_domain())
        words = P.tokens(query or "")
        catalog = {r["product"].id: r for r in self._catalog()} if words else {}
        if words:
            products = products.filtered(lambda p: p.id in catalog and self._tok_match(catalog[p.id], words))
        ctx_products = products.with_context(location=loc.id)
        rows = []
        for p in ctx_products:
            qty, free = p.qty_available, p.free_qty
            if not show_all and abs(qty) < 1e-6:
                continue
            tmpl = p.product_tmpl_id
            per = tmpl.craf_pcs_per_pack
            min_qty = tmpl.craf_min_qty or 0.0
            rows.append({
                "id": p.id, "code": p.default_code or "", "name": p.name,
                "type": tmpl.craf_section_id.profile_type or "",
                "qty": qty, "free": free, "text": packs_text(qty, per) if qty >= 0 else "%s dona" % int(qty),
                "kg": round(qty * (tmpl.craf_kg_per_pc or 0.0), 1),
                "low": bool(min_qty) and qty < min_qty, "negative": qty < 0, "per_pack": per,
            })
        rows.sort(key=lambda r: (r["type"], r["code"], r["name"]))
        return {
            "location_id": loc.id,
            "rows": rows,
            "total_pcs": sum(r["qty"] for r in rows),
            "total_kg": round(sum(r["kg"] for r in rows), 1),
            "count": len(rows),
        }

    # ------------------------------------------------------------------ Yuklash (yuklovchi)
    def _queue_domain(self):
        return [("state", "=", "sale"), ("craf_load_state", "in", ("queue", "loading"))]

    def _load_so(self, order_id):
        self._check_loader()
        so = self.env["sale.order"].sudo().browse(int(order_id or 0)).exists()
        if not so:
            raise UserError("Buyurtma topilmadi.")
        return so

    def _load_move(self, so, move_id):
        move = self.env["stock.move"].sudo().browse(int(move_id or 0)).exists()
        if not move or move not in so._craf_open_pickings().move_ids or move.state in ("done", "cancel"):
            raise UserError("Bu qator endi ochiq emas — ro'yxatni yangilang.")
        return move

    def _ensure_loading(self, so):
        """Yuklashni faqat «Qabul qilish» ni bosgan yuklovchi o'zgartiradi."""
        if so.craf_load_state == "queue":
            raise UserError("%s: avval «Qabul qilish» ni bosing." % so.name)
        if so.craf_load_state != "loading":
            raise UserError("%s endi yuklashda emas — ro'yxatni yangilang." % so.name)
        if not so.craf_loader_id:
            so.write({"craf_loader_id": self.env.user.id,
                      "craf_load_start": so.craf_load_start or fields.Datetime.now()})
        elif so.craf_loader_id != self.env.user:
            raise UserError("%s ni %s yuklamoqda. Davom ettirish uchun «Men davom ettiraman» ni bosing." % (
                so.name, so.craf_loader_id.name))

    @api.model
    def load_queue(self):
        self._check_loader()
        orders = self.env["sale.order"].sudo().search(self._queue_domain(), order="craf_sent_date, id")
        return {"orders": [self._order_card(o) for o in orders], "count": len(orders)}

    def _alloc_map(self, moves):
        """{move_id: {location_id: qty}}"""
        out = {}
        for a in self.env["craf.load.alloc"].sudo().search([("move_id", "in", moves.ids)]):
            row = out.setdefault(a.move_id.id, {})
            row[a.location_id.id] = row.get(a.location_id.id, 0.0) + a.qty
        return out

    def _set_alloc(self, so, move, qty_by_loc):
        """Qator rejasini almashtiradi: {location: dona}. Bo'sh — yuklanmagan."""
        Alloc = self.env["craf.load.alloc"].sudo()
        Alloc.search([("move_id", "=", move.id)]).unlink()
        vals = [{"move_id": move.id, "order_id": so.id, "location_id": loc.id, "qty": qty,
                 "user_id": self.env.user.id} for loc, qty in qty_by_loc.items() if qty > 0]
        if vals:
            Alloc.create(vals)

    @api.model
    def load_order(self, order_id):
        so = self._load_so(order_id)
        moves = so._craf_open_pickings().move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        packs = self.env["craf.pack"].sudo().search([("load_move_id", "in", moves.ids)])
        points = self._locations()
        for loc in moves.location_id:
            if loc not in points:
                points |= loc
        products = moves.product_id
        onhand = {loc.id: {p.id: p.qty_available for p in products.with_context(location=loc.id)} for loc in points}
        allocs = self._alloc_map(moves)
        lines = []
        for m in moves.sorted(lambda m: (m.sale_line_id.sequence, m.id)):
            p = m.product_id
            per = p.craf_pcs_per_pack
            demand = m.product_uom._compute_quantity(m.product_uom_qty, p.uom_id)
            amap = allocs.get(m.id, {})
            loaded = sum(amap.values())
            stock = []
            for loc in points:
                have = onhand[loc.id].get(p.id, 0.0)
                q = amap.get(loc.id, 0.0)
                stock.append({
                    "location_id": loc.id, "label": loc._craf_sale_label(),
                    "onhand": have, "onhand_text": packs_text(max(have, 0), per),
                    "qty": q, "qty_text": packs_text(q, per) if q else "",
                    "primary": loc == m.location_id,
                })
            lines.append({
                "move_id": m.id,
                "product": self._product_info(p),
                "demand": demand,
                "demand_text": packs_text(demand, per),
                "loaded": loaded,
                "loaded_text": packs_text(loaded, per) if loaded else "",
                "picked": loaded > 0,
                "primary_id": m.location_id.id,
                "stock": stock,
                "split": len([x for x in stock if x["qty"]]) > 1 or any(x["qty"] and not x["primary"] for x in stock),
                "onhand": onhand.get(m.location_id.id, {}).get(p.id, 0.0),
                "onhand_text": packs_text(max(onhand.get(m.location_id.id, {}).get(p.id, 0.0), 0), per),
                "packs": [x.name for x in packs if x.load_move_id == m],
                "raw": m.sale_line_id.craf_source_line or "",
            })
        given = so.order_line.filtered(lambda l: l.qty_delivered > 0)
        card = self._order_card(so)
        card.update({
            "lines_open": lines,
            "given_before": [{"product": l.product_id.name,
                              "text": packs_text(l.qty_delivered, l.product_id.craf_pcs_per_pack)} for l in given],
            "is_mine": so.craf_loader_id == self.env.user,
        })
        return card

    @api.model
    def load_accept(self, order_id, force=False):
        """«Qabul qilish»: buyurtma shu yuklovchiga o'tadi, holati «Yuklanmoqda»."""
        so = self._load_so(order_id)
        me = self.env.user
        if so.craf_load_state not in ("queue", "loading"):
            label = dict(so._fields["craf_load_state"].selection).get(so.craf_load_state, so.craf_load_state)
            raise UserError("%s endi navbatda emas (%s)." % (so.name, label))
        if so.craf_load_state == "loading" and so.craf_loader_id == me:
            return self.load_order(so.id)
        prev = so.craf_loader_id if so.craf_load_state == "loading" else self.env["res.users"]
        if prev and not force:
            return {"busy": prev.name}
        so.write({"craf_load_state": "loading", "craf_loader_id": me.id, "craf_load_start": fields.Datetime.now()})
        if prev:
            title, msg = "Yuklovchi almashdi", "%s · %s — endi %s yuklaydi (%s o'rniga)" % (
                so.name, so.partner_id.name, me.name, prev.name)
        else:
            title, msg = "Qabul qilindi", "%s · %s — %s qabul qildi, yuklanmoqda" % (
                so.name, so.partner_id.name, me.name)
        so._craf_notify("loading", title, msg, users=so.user_id | prev)
        return self.load_order(so.id)

    @api.model
    def load_start(self, order_id, force=False):
        """Eski nom (keshlangan sahifalar uchun)."""
        return self.load_accept(order_id, force=force)

    @api.model
    def load_release(self, order_id):
        """Qabulni bekor qilish — buyurtma navbatga qaytadi (rejalar saqlanadi)."""
        so = self._load_so(order_id)
        if so.craf_load_state == "loading":
            if so.craf_loader_id and so.craf_loader_id != self.env.user and not self._is_seller():
                raise UserError("%s ni %s yuklamoqda." % (so.name, so.craf_loader_id.name))
            so.write({"craf_load_state": "queue", "craf_loader_id": False, "craf_load_start": False})
            so._craf_notify("queue", "Navbatga qaytdi", "%s · %s — %s qaytardi" % (
                so.name, so.partner_id.name, self.env.user.name), to_loaders=True)
        return True

    @api.model
    def load_toggle(self, order_id, move_id):
        """Bosilsa: to'liq — asosiy joydan; qayta bosilsa — yuklanmagan."""
        so = self._load_so(order_id)
        move = self._load_move(so, move_id)
        self._ensure_loading(so)
        if self.env["craf.load.alloc"].sudo().search_count([("move_id", "=", move.id), ("qty", ">", 0)]):
            self._set_alloc(so, move, {})
        else:
            demand = move.product_uom._compute_quantity(move.product_uom_qty, move.product_id.uom_id)
            self._set_alloc(so, move, {move.location_id: demand})
        return self.load_order(so.id)

    @api.model
    def load_set(self, order_id, move_id, rows=None):
        """rows: [{location_id, packs, extra}] — har joydan qancha yuklandi."""
        so = self._load_so(order_id)
        move = self._load_move(so, move_id)
        per = move.product_id.craf_pcs_per_pack
        Location = self.env["stock.location"].sudo()
        qty_by_loc = {}
        for row in rows or []:
            packs, extra = int(row.get("packs") or 0), int(row.get("extra") or 0)
            if packs < 0 or extra < 0:
                raise UserError("Manfiy miqdor bo'lmaydi.")
            if packs and not per:
                raise UserError("%s: «dona / pachka» kiritilmagan — donada yozing." % move.product_id.display_name)
            loc = Location.browse(int(row.get("location_id") or 0)).exists()
            if not loc or loc.usage != "internal":
                raise UserError("Joy topilmadi.")
            pcs = packs * per + extra
            if pcs:
                qty_by_loc[loc] = qty_by_loc.get(loc, 0.0) + pcs
        self._ensure_loading(so)
        self._set_alloc(so, move, qty_by_loc)
        return self.load_order(so.id)

    def _photo_list(self, so):
        trip = so.sudo().craf_trip_photo_ids
        return [{
            "id": a.id,
            "url": "/craf/sotuv/photo/%s" % a.id,
            "thumb": "/craf/sotuv/photo/%s?size=256" % a.id,
            "trip": a in trip,
            "time": self._utc_to_local_str(a.create_date, "%H:%M") if a.create_date else "",
        } for a in so.sudo().craf_truck_photo_ids.sorted("id")]

    @api.model
    def load_photo(self, order_id, data, name=None, mimetype=None):  # noqa: ARG002
        """Yuklangan mashina rasmi (base64). Faqat qabul qilgan yuklovchi."""
        so = self._load_so(order_id)
        self._ensure_loading(so)
        if not data:
            raise UserError("Rasm bo'sh.")
        if "," in data[:100]:
            data = data.split(",", 1)[1]
        if len(data) > 20 * 1024 * 1024:
            raise UserError("Rasm juda katta.")
        try:
            raw = base64.b64decode(data)
            fmt = (binary_to_image(raw).format or "").upper()
        except Exception:  # noqa: BLE001
            raise UserError("Bu rasm emas — kamera bilan qayta oling.") from None
        if fmt not in ("JPEG", "PNG", "WEBP", "MPO"):
            raise UserError("Rasm turi qo'llanmaydi (%s) — kamera bilan oling." % (fmt or "?"))
        # telefondan kelgan katta rasm kichraytiriladi (yo'nalish EXIF bo'yicha to'g'rilanadi)
        raw = image_process(raw, size=(1920, 1920), quality=82, output_format="JPEG")
        n = len(so.sudo().craf_truck_photo_ids) + 1
        when = self._utc_to_local_str(fields.Datetime.now(), "%Y%m%d-%H%M")
        att = self.env["ir.attachment"].sudo().create({
            "name": "%s-mashina-%s-%s.jpg" % (so.name, when, n),
            "raw": raw,
            "mimetype": "image/jpeg",
            "res_model": "sale.order",
            "res_id": so.id,
        })
        so.sudo().write({"craf_truck_photo_ids": [(4, att.id)], "craf_trip_photo_ids": [(4, att.id)]})
        so._craf_notify("photo", "Mashina rasmi", "%s · %s" % (so.name, so.partner_id.name), users=self.env["res.users"])
        return self.load_order(so.id)

    @api.model
    def load_photo_remove(self, order_id, attachment_id):
        so = self._load_so(order_id)
        self._ensure_loading(so)
        att = so.sudo().craf_trip_photo_ids.filtered(lambda a: a.id == int(attachment_id or 0))
        if not att:
            raise UserError("Bu rasmni o'chirib bo'lmaydi (allaqachon berilgan).")
        att.unlink()
        return self.load_order(so.id)

    @api.model
    def load_truck(self, order_id, truck):
        so = self._load_so(order_id)
        so.craf_truck = (truck or "").strip() or False
        so._craf_notify("truck", "Mashina", "%s · %s — %s" % (so.name, so.partner_id.name, so.craf_truck or "—"))
        return {"truck": so.craf_truck or ""}

    @api.model
    def load_scan(self, order_id, code):
        so = self._load_so(order_id)
        code = (code or "").strip()
        if not code:
            raise UserError("Kod bo'sh.")
        moves = so._craf_open_pickings().move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        pack = self.env["craf.pack"].sudo()._craf_find(code)
        loc = False
        if pack:
            if pack.craf_state == "sold":
                raise UserError("%s allaqachon sotilgan (%s)." % (pack.name, pack.sold_partner_id.name or ""))
            move = moves.filtered(lambda m: m.product_id == pack.product_id)[:1]
            if not move:
                raise UserError("%s — %s bu buyurtmada yo'q." % (pack.name, pack.product_id.display_name))
            if pack.load_move_id == move:
                raise UserError("%s allaqachon skanerlangan." % pack.name)
            if pack.load_move_id and pack.load_move_id.state not in ("done", "cancel"):
                raise UserError("%s boshqa buyurtmaga skanerlangan (%s)." % (
                    pack.name, pack.load_move_id.sale_line_id.order_id.name or pack.load_move_id.reference))
            pcs = pack.pcs
            if pack.location_id and pack.location_id.craf_sale_point:
                loc = pack.location_id
        else:
            short = code.rstrip("/").rsplit("/", 1)[-1].strip()
            product = self.env["product.product"].search(
                ["|", ("default_code", "=ilike", short), ("barcode", "=", short)], limit=1)
            move = moves.filtered(lambda m: m.product_id == product)[:1] if product else moves.browse()
            if not move:
                raise UserError("«%s» — bu buyurtmada bunday mahsulot yo'q." % code)
            pcs = product.craf_pcs_per_pack or 1
        loc = loc or move.location_id
        self._ensure_loading(so)
        current = {}
        for a in self.env["craf.load.alloc"].sudo().search([("move_id", "=", move.id)]):
            current[a.location_id] = current.get(a.location_id, 0.0) + a.qty
        current[loc] = current.get(loc, 0.0) + pcs
        self._set_alloc(so, move, current)
        if pack:
            pack.load_move_id = move
        res = self.load_order(so.id)
        res["scanned"] = {"name": pack.name if pack else code, "product": move.product_id.name, "pcs": pcs}
        return res

    @api.model
    def load_done(self, order_id, rest="backorder"):
        so = self._load_so(order_id)
        if rest not in ("backorder", "cancel"):
            rest = "backorder"
        self._ensure_loading(so)
        so._craf_load_done(rest=rest)
        return {"card": self._order_card(so)}
