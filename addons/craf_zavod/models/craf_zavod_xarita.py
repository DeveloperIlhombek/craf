"""Zavod xaritasi: har bir bo'limdagi jonli qoldiq va tanlangan davrdagi REAL oqimlar.

Oqimlar bajarilgan ombor harakatlaridan hisoblanadi:
- ichki joy → ichki joy (ko'chirish), ta'minotchi → joy (kirim), joy → mijoz (sotuv);
- ishlab chiqarish chiqishi (plavka, press, bo'yash) — MRP buyurtmasining xomashyo joyidan chiquvchi joyga
  (Liteyka → Press: stalba, Press → Bo'yash: profil, Press → Liteyka: otxod, Liteyka → Chiqindi: shlak ...);
- joy → ishlab chiqarish — shu joyning «sarfi»; inventarizatsiya — «sanash tuzatishi» (strelka emas).
"""
import json
import math
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import AccessError

# Asosiy zanjir (davrda harakat bo'lmasa ham xira chiziq bilan ko'rsatiladi) va oqim nomlari
CHAIN = [
    ("supplier", "Литейка"),
    ("Литейка", "Press sexi"),
    ("Press sexi", "Bo'yash sexi"),
    ("Bo'yash sexi", "Tayyor mahsulot ombori"),
    ("Tayyor mahsulot ombori", "customer"),
]
# Xaritada bitta blok: «Qadoqlash» joyi «Bo'yash sexi» bilan birga ko'rsatiladi (ombor joylari o'zgarmaydi)
MERGE = {"Qadoqlash": "Bo'yash sexi"}
DISPLAY = {"Bo'yash sexi": "Bo'yash va qadoqlash"}
LABELS = {
    ("supplier", "Литейка"): "kirim",
    ("supplier", "Xom-ashyo ombori"): "kirim",
    ("Литейка", "Press sexi"): "stalba",
    ("Press sexi", "Bo'yash sexi"): "profil",
    ("Press sexi", "Kimyoviy ishlov"): "korzinka",
    ("Kimyoviy ishlov", "Bo'yash sexi"): "profil",
    ("Bo'yash sexi", "Qadoqlash"): "bo'yalgan",
    ("Bo'yash sexi", "Tayyor mahsulot ombori"): "bo'yalgan · pachka",
    ("Qadoqlash", "Tayyor mahsulot ombori"): "pachka",
    ("Tayyor mahsulot ombori", "customer"): "sotuv",
    ("Press sexi", "Литейка"): "otxod / pitak",
    ("Bo'yash sexi", "Литейка"): "brak",
    ("Литейка", "Chiqindi"): "shlak",
    ("Chiqindi", "Литейка"): "qayta eritish",
    ("Xom-ashyo ombori", "Bo'yash sexi"): "kukun / kimyo",
}
# KPI kartochkalari: (kalit, nom, belgi, [(qayerdan, qayerga), ...])
KPIS = [
    ("kirim", "Kirim", "fa-truck", [("supplier", "*")]),
    ("stalba", "Stalba quyildi", "fa-fire", [("Литейка", "Press sexi")]),
    ("press", "Press chiqardi", "fa-industry", [("Press sexi", "Bo'yash sexi"), ("Press sexi", "Kimyoviy ishlov")]),
    ("boyash", "Bo'yaldi", "fa-paint-brush", [("Bo'yash sexi", "Qadoqlash"), ("Bo'yash sexi", "Tayyor mahsulot ombori")]),
    ("sotuv", "Sotildi", "fa-shopping-cart", [("*", "customer")]),
]
VIRTUAL = {
    "supplier": {"name": "Ta'minotchilar", "kind": "external", "icon": "fa-truck", "x": 30, "y": 90, "w": 190, "h": 190},
    "customer": {"name": "Mijozlar", "kind": "external", "icon": "fa-users", "x": 670, "y": 430, "w": 230, "h": 190},
}
PERIODS = {"today": 1, "7": 7, "30": 30}
ICP_KEY = "craf_zavod.virtual_layout"


class CrafZavodXarita(models.AbstractModel):
    _name = "craf.zavod.xarita"
    _description = "Zavod xaritasi ma'lumotlari"

    # ------------------------------------------------------------------ yordamchilar
    @api.model
    def _craf_can_edit(self):
        return self.env.user.has_group("stock.group_stock_manager") or self.env.is_admin()

    @api.model
    def _craf_period(self, period):
        tz = pytz.timezone(self.env.user.tz or "Asia/Tashkent")
        today = datetime.now(tz).date()
        days = PERIODS.get(str(period), 1)
        first = today - timedelta(days=days - 1)
        start = tz.localize(datetime.combine(first, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        label = "Bugun" if days == 1 else "%s – %s" % (first.strftime("%d.%m"), today.strftime("%d.%m"))
        return start, label

    @api.model
    def _craf_virtual(self):
        nodes = {k: dict(v, id=k) for k, v in VIRTUAL.items()}
        try:
            saved = json.loads(self.env["ir.config_parameter"].sudo().get_param(ICP_KEY) or "{}")
        except ValueError:
            saved = {}
        for key, pos in saved.items():
            if key in nodes and isinstance(pos, dict):
                nodes[key].update({k: int(pos[k]) for k in ("x", "y") if k in pos})
                if "hidden" in pos:
                    nodes[key]["hidden"] = bool(pos["hidden"])
        return nodes

    @api.model
    def _craf_merge(self, locations):
        """MERGE dagi joylarni xaritadan olib tashlaydi: {birlashgan joy id: asosiy blok id}."""
        by_name = {loc.name: loc for loc in locations}
        merged = {}
        for src, dst in MERGE.items():
            if src in by_name and dst in by_name:
                merged[by_name[src].id] = by_name[dst].id
        return locations.filtered(lambda l: l.id not in merged), merged

    @api.model
    def _craf_kg(self, product, qty, kg_uom):
        if kg_uom and product.uom_id == kg_uom:
            return qty
        return qty * (product.product_tmpl_id.craf_kg_per_pc or 0.0)

    # ------------------------------------------------------------------ asosiy ma'lumot
    @api.model
    def get_map_data(self, top_limit=12, period="today", **kwargs):
        Location = self.env["stock.location"]
        locations = Location.search([("usage", "=", "internal"), ("craf_map_kind", "!=", False)],
                                    order="craf_map_sequence, id")
        if not locations:
            locations = Location.search([("craf_map_show", "=", True), ("usage", "=", "internal")],
                                        order="craf_map_sequence, id")
        kg_uom = self.env.ref("uom.product_uom_kgm", raise_if_not_found=False)
        locations, merged = self._craf_merge(locations)

        # ichki joy → xaritadagi eng yaqin ota joy (birlashtirilgan joy — asosiy blokka)
        zone_of = {}
        for loc in Location.search([("usage", "=", "internal")]):
            p = loc
            while p and p.id not in locations.ids and p.id not in merged:
                p = p.location_id
            zone_of[loc.id] = merged.get(p.id, p.id) if p else None

        # --- qoldiq
        by_loc = {loc.id: {} for loc in locations}
        for q in self.env["stock.quant"].search([("location_id", "child_of", locations.ids)]) if locations else []:
            zid = zone_of.get(q.location_id.id)
            if not zid or not q.quantity:
                continue
            row = by_loc[zid].setdefault(q.product_id.id, {"product": q.product_id, "qty": 0.0})
            row["qty"] += q.quantity

        # --- davrdagi oqimlar
        start, period_label = self._craf_period(period)
        moves = self.env["stock.move"].search([("state", "=", "done"), ("date", ">=", start)])
        flows = defaultdict(lambda: {"kg": 0.0, "qty": 0.0, "moves": 0, "products": defaultdict(float)})
        stats = defaultdict(lambda: defaultdict(float))  # zona → {in, out, sarf, ishlab, tuzatish}
        last_move = {}
        for m in moves:
            product = m.product_id
            kg = self._craf_kg(product, m.product_qty, kg_uom)
            su, du = m.location_id.usage, m.location_dest_id.usage
            src = zone_of.get(m.location_id.id) if su == "internal" else su
            dst = zone_of.get(m.location_dest_id.id) if du == "internal" else du
            for z in (src, dst):
                if isinstance(z, int) and (z not in last_move or m.date > last_move[z]):
                    last_move[z] = m.date
            if su == "production":
                mo = m.production_id
                if not mo:  # MRP siz ishlab chiqarish yozuvi (qo'lda tuzatish) — zonada «tuzatish»
                    if isinstance(dst, int):
                        stats[dst]["tuzatish"] += kg
                    continue
                src = zone_of.get(mo.location_src_id.id)
                if isinstance(src, int):  # ishlab chiqargan bo'lim (plavka — Liteyka, press — Press ...)
                    stats[src]["ishlab"] += kg
            if du == "production":
                if isinstance(src, int):
                    stats[src]["sarf"] += kg
                continue
            if su == "inventory" or du == "inventory":
                z = dst if su == "inventory" else src
                if isinstance(z, int):
                    stats[z]["tuzatish"] += kg if su == "inventory" else -kg
                continue
            if src is None or dst is None or src == dst:
                continue
            f = flows[(src, dst)]
            f["kg"] += kg
            f["qty"] += m.product_qty
            f["moves"] += 1
            f["products"][product.display_name] += kg
            if isinstance(src, int):
                stats[src]["out"] += kg
            if isinstance(dst, int):
                stats[dst]["in"] += kg

        # --- korzinkalar (craf_korzinka o'rnatilgan bo'lsa)
        baskets = defaultdict(int)
        if "craf.basket.load" in self.env:
            for load in self.env["craf.basket.load"].search([("state", "in", ("press", "kimyo"))]):
                zid = zone_of.get(load.location_id.id)
                if zid:
                    baskets[zid] += 1

        # --- zonalar
        names = {loc.id: loc.name for loc in locations}
        recent = fields.Datetime.now() - timedelta(hours=3)
        zones = []
        for loc in locations:
            items, units = [], defaultdict(float)
            kg_total = pcs_total = 0.0
            packs_total = 0
            for row in by_loc[loc.id].values():
                product, qty = row["product"], row["qty"]
                tmpl = product.product_tmpl_id
                is_kg = bool(kg_uom) and product.uom_id == kg_uom
                kg = self._craf_kg(product, qty, kg_uom)
                packs = rest = 0
                per_pack = tmpl.craf_pcs_per_pack
                if not is_kg:
                    units[product.uom_id.name] += qty
                    if tmpl.craf_kg_per_pc:
                        pcs_total += qty
                    if per_pack:
                        packs, rest = divmod(int(math.floor(qty + 1e-9)), per_pack)
                        packs_total += packs
                kg_total += kg
                items.append({
                    "id": product.id,
                    "code": product.default_code or "",
                    "name": product.name,
                    "qty": qty,
                    "uom": product.uom_id.name,
                    "is_kg": is_kg,
                    "kg": kg,
                    "packs_text": ("%s pachka + %s" % (packs, rest) if rest else "%s pachka" % packs)
                    if per_pack and not is_kg else "",
                })
            items.sort(key=lambda r: (-r["kg"], -r["qty"]))
            st = stats.get(loc.id, {})
            zones.append({
                "id": loc.id,
                "name": DISPLAY.get(loc.name, loc.name),
                "full_name": loc.complete_name,
                "kind": loc.craf_map_kind or "process",
                "hidden": not loc.craf_map_show,
                "x": loc.craf_map_x, "y": loc.craf_map_y, "w": loc.craf_map_w, "h": loc.craf_map_h,
                "kg_total": kg_total,
                "pcs_total": pcs_total,
                "packs_total": packs_total,
                "units": [{"uom": u, "qty": q} for u, q in sorted(units.items(), key=lambda kv: -kv[1]) if q],
                "product_count": len(items),
                "top": items[:top_limit],
                "items": items[:200],
                "in_kg": st.get("in", 0.0), "out_kg": st.get("out", 0.0),
                "made_kg": st.get("ishlab", 0.0), "used_kg": st.get("sarf", 0.0), "fix_kg": st.get("tuzatish", 0.0),
                "baskets": baskets.get(loc.id, 0),
                "active": bool(last_move.get(loc.id) and last_move[loc.id] >= recent),
                "last_move": fields.Datetime.to_string(last_move[loc.id]) if last_move.get(loc.id) else False,
            })

        # --- virtual tugunlar (ta'minotchi, mijoz)
        virtual = self._craf_virtual()
        for key, node in virtual.items():
            node["kg"] = sum(f["kg"] for (s, d), f in flows.items() if key in (s, d))

        # --- oqimlar ro'yxati
        def label(src, dst):
            return LABELS.get((names.get(src, src), names.get(dst, dst)), "ko'chirish")

        known = set(names) | set(virtual)
        out_flows = []
        for (src, dst), f in flows.items():
            if src in known and dst in known:
                top = sorted(f["products"].items(), key=lambda kv: -kv[1])[:5]
                out_flows.append({"from": src, "to": dst, "label": label(src, dst), "kg": f["kg"], "qty": f["qty"],
                                  "moves": f["moves"], "products": [{"name": n, "kg": k} for n, k in top]})
        by_name = {v: k for k, v in names.items()}
        by_name.update({k: k for k in virtual})
        for a, b in CHAIN:
            src, dst = by_name.get(a), by_name.get(b)
            if src and dst and (src, dst) not in flows:
                out_flows.append({"from": src, "to": dst, "label": label(src, dst), "kg": 0.0, "qty": 0.0, "moves": 0,
                                  "products": []})

        # --- KPI
        kpis = []
        for key, title, icon, pairs in KPIS:
            total = 0.0
            for (src, dst), f in flows.items():
                for a, b in pairs:
                    if (a == "*" or names.get(src, src) == a) and (b == "*" or names.get(dst, dst) == b):
                        total += f["kg"]
                        break
            kpis.append({"key": key, "label": title, "icon": icon, "value": total, "unit": "kg"})
        kpis.append({"key": "korzinka", "label": "To'la korzinka", "icon": "fa-shopping-basket",
                     "value": sum(baskets.values()), "unit": "ta"})

        return {
            "zones": zones,
            "virtual": list(virtual.values()),
            "flows": out_flows,
            "kpis": kpis,
            "period": str(period) if str(period) in PERIODS else "today",
            "period_label": period_label,
            "can_edit": self._craf_can_edit(),
            "updated": fields.Datetime.to_string(fields.Datetime.now()),
        }

    @api.model
    def get_zone_moves(self, zone_id, period="today", limit=15):
        """Tanlangan bo'limning davrdagi oxirgi harakatlari."""
        zone = self.env["stock.location"].browse(int(zone_id)).exists()
        if not zone:
            return []
        start, _label = self._craf_period(period)
        kg_uom = self.env.ref("uom.product_uom_kgm", raise_if_not_found=False)
        all_locs = self.env["stock.location"].search([("usage", "=", "internal"), ("craf_map_kind", "!=", False)])
        _visible, merged = self._craf_merge(all_locs)
        zones = zone | self.env["stock.location"].browse([k for k, v in merged.items() if v == zone.id])
        inside = self.env["stock.location"].search([("id", "child_of", zones.ids)])
        moves = self.env["stock.move"].search([
            ("state", "=", "done"), ("date", ">=", start),
            "|", ("location_id", "in", inside.ids), ("location_dest_id", "in", inside.ids),
            "!", "&", ("location_id", "in", inside.ids), ("location_dest_id", "in", inside.ids)],
            order="date desc, id desc", limit=int(limit))
        tz = pytz.timezone(self.env.user.tz or "Asia/Tashkent")
        res = []
        for m in moves:
            incoming = m.location_dest_id in inside
            other = m.location_id if incoming else m.location_dest_id
            res.append({
                "id": m.id,
                "date": pytz.utc.localize(m.date).astimezone(tz).strftime("%d.%m %H:%M"),
                "ref": m.reference or m.origin or "",
                "product": m.product_id.display_name,
                "qty": m.product_qty,
                "uom": m.product_id.uom_id.name,
                "kg": self._craf_kg(m.product_id, m.product_qty, kg_uom),
                "incoming": incoming,
                "other": other.name if other.usage == "internal" else dict(
                    m.location_id._fields["usage"].selection).get(other.usage, other.usage),
            })
        return res

    @api.model
    def save_layout(self, positions, hidden=None):
        """Tartiblash rejimi: bloklar joyi va ko'rinishi. positions = {id: {x, y}}, hidden = [id, ...]."""
        if not self._craf_can_edit():
            raise AccessError("Xaritani tartiblash uchun ombor menejeri huquqi kerak.")
        hidden = set(str(h) for h in (hidden or []))
        virtual = {}
        for key, pos in (positions or {}).items():
            x, y = int(round(pos.get("x", 0))), int(round(pos.get("y", 0)))
            if key in VIRTUAL:
                virtual[key] = {"x": x, "y": y, "hidden": key in hidden}
                continue
            loc = self.env["stock.location"].browse(int(key)).exists()
            if loc:
                loc.sudo().write({"craf_map_x": x, "craf_map_y": y, "craf_map_show": str(loc.id) not in hidden})
        if virtual:
            self.env["ir.config_parameter"].sudo().set_param(ICP_KEY, json.dumps(virtual))
        return True
