from collections import defaultdict

import pytz

from odoo import api, fields, models

KIMYO = "Kimyoviy ishlov"
PRESS = "Press sexi"
BOYASH = "Bo'yash sexi"


class CrafZavodXarita(models.AbstractModel):
    _inherit = "craf.zavod.xarita"

    @api.model
    def get_map_data(self, top_limit=12, period="today", **kwargs):
        """Press → Kimyoviy ishlov → Bo'yash.

        Press chiqargan profil ombor harakatida to'g'ri Bo'yash sexiga yoziladi; xaritada u korzinkalarda
        Kimyoviy ishlov orqali o'tadi:
        - Press → Kimyo: press chiqargani (harakatlardan);
        - Kimyo → Bo'yash: davrda tasdiqlangan kimyoviy ishlov hujjatlaridagi profil kg;
        - Kimyo blokida — ishlovni kutayotgan to'la korzinkalar (dona, kg), sarf — kimyoviy moddalar.
        """
        data = super().get_map_data(top_limit=top_limit, period=period, **kwargs)
        zones = {z["id"]: z for z in data["zones"]}
        by_name = {self.env["stock.location"].browse(zid).name: zid for zid in zones}
        kimyo, press, boyash = by_name.get(KIMYO), by_name.get(PRESS), by_name.get(BOYASH)

        loads = self.env["craf.basket.load"].search([("state", "in", ("press", "kimyo"))])
        stale = self.env["craf.basket"].search([("is_stale", "=", True)])
        for z in data["zones"]:
            z["baskets"] = 0
            z["baskets_stale"] = 0
        if not (kimyo and press and boyash):
            for z in data["zones"]:
                zl = loads.filtered(lambda l, zid=z["id"]: l.location_id.id == zid)
                z["baskets"] = len(zl)
                z["baskets_stale"] = len(stale.filtered(lambda b, zid=z["id"]: b.location_id.id == zid))
            return data

        # --- korzinkalar: kimyoni kutayotgani — Kimyo blokida, kimyodan o'tgani — Bo'yashda
        waiting = loads.filtered(lambda l: l.state == "press" and l.shift_state == "done")
        passed = loads.filtered(lambda l: l.state == "kimyo")
        kz, bz = zones[kimyo], zones[boyash]
        kz["baskets"] = len(waiting)
        kz["baskets_stale"] = len(stale.filtered(lambda b: b.current_load_id in waiting))
        bz["baskets"] = len(passed)
        queue_kg = sum(l.net_kg or l.kg_theory for l in waiting)
        kz["kg_total"] = queue_kg
        kz["pcs_total"] = sum(waiting.mapped("pcs_total"))
        kz["note"] = "%s korzinka ishlovni kutmoqda" % len(waiting) if waiting else "korzinka yo'q"
        kz["queue"] = True
        kz["hidden"] = False

        # --- davrdagi kimyoviy ishlov hujjatlari
        start, _label = self._craf_period(period)
        tz = pytz.timezone(self.env.user.tz or "Asia/Tashkent")
        first = pytz.utc.localize(start).astimezone(tz).date()
        treats = self.env["craf.chem.treatment"].search([("state", "=", "done"), ("date", ">=", first)])
        treated_kg = sum(treats.mapped("kg_total"))
        kz["used_kg"] = sum(treats.mapped("chem_kg"))
        kz["made_kg"] = treated_kg
        kz["active"] = kz["active"] or bool(self.env["craf.chem.treatment"].search_count(
            [("write_date", ">=", fields.Datetime.subtract(fields.Datetime.now(), hours=3))]))

        # --- oqimlar: Press → Bo'yash o'rniga Press → Kimyo → Bo'yash
        flows = data["flows"]
        pb = next((f for f in flows if f["from"] == press and f["to"] == boyash), None)
        rest = [f for f in flows if not (f["from"] == press and f["to"] == boyash)
                and not (kimyo in (f["from"], f["to"]) and {f["from"], f["to"]} & {press, boyash})]
        press_kg = pb["kg"] if pb else 0.0
        rest.append({"from": press, "to": kimyo, "label": "korzinka", "kg": press_kg,
                     "qty": pb["qty"] if pb else 0.0, "moves": pb["moves"] if pb else 0,
                     "products": pb["products"] if pb else []})
        products = defaultdict(float)
        for load in treats.load_ids:
            for p, q in load._product_quantities().items():
                products[p.display_name] += q * (p.product_tmpl_id.craf_kg_per_pc or 0.0)
        top = sorted(products.items(), key=lambda kv: -kv[1])[:5]
        rest.append({"from": kimyo, "to": boyash, "label": "ishlangan profil", "kg": treated_kg,
                     "qty": sum(treats.mapped("pcs_total")), "moves": len(treats),
                     "products": [{"name": n, "kg": k} for n, k in top]})
        data["flows"] = rest
        # zona statistikasi: Press chiqimi Kimyoga, Bo'yash kirimi — kimyodan o'tgani
        kz["in_kg"] = press_kg
        kz["out_kg"] = treated_kg
        bz["in_kg"] = bz["in_kg"] - press_kg + treated_kg

        for k in data["kpis"]:
            if k["key"] == "korzinka":
                k["value"] = len(loads)
        data["kpis"].insert(3, {"key": "kimyo", "label": "Kimyodan o'tdi", "icon": "fa-flask",
                                "value": treated_kg, "unit": "kg"})
        return data
