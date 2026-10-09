import math

from odoo import api, fields, models

# Ishlab chiqarish oqimi: (qayerdan, qayerga, yozuv) - joylashuv nomlari bo'yicha
FLOWS = [
    ("Xom-ashyo ombori", "Литейка", "shixta"),
    ("Литейка", "Press sexi", "quyma"),
    ("Press sexi", "Bo'yash sexi", "profil"),
    ("Bo'yash sexi", "Qadoqlash", "bo'yalgan"),
    ("Qadoqlash", "Tayyor mahsulot ombori", "pachka"),
    ("Chiqindi", "Литейка", "qayta eritish"),
]


class CrafZavodXarita(models.AbstractModel):
    _name = "craf.zavod.xarita"
    _description = "Zavod xaritasi ma'lumotlari"

    @api.model
    def get_map_data(self, top_limit=12):
        locations = self.env["stock.location"].search(
            [("craf_map_show", "=", True), ("usage", "=", "internal")], order="craf_map_sequence, id")
        kg_uom = self.env.ref("uom.product_uom_kgm", raise_if_not_found=False)
        quants = self.env["stock.quant"].search([("location_id", "child_of", locations.ids)]) if locations else []
        by_loc = {loc.id: {} for loc in locations}
        loc_index = {}
        for loc in locations:
            loc_index[loc.id] = loc
        for q in quants:
            # quant joylashuvini xaritadagi eng yaqin ota joylashuvga bog'laymiz
            loc = q.location_id
            while loc and loc.id not in by_loc:
                loc = loc.location_id
            if not loc or not q.quantity:
                continue
            products = by_loc[loc.id]
            row = products.setdefault(q.product_id.id, {"product": q.product_id, "qty": 0.0})
            row["qty"] += q.quantity

        zones = []
        for loc in locations:
            items = []
            kg_total = pcs_total = 0.0
            packs_total = 0
            for row in by_loc[loc.id].values():
                product, qty = row["product"], row["qty"]
                tmpl = product.product_tmpl_id
                is_kg = bool(kg_uom) and product.uom_id == kg_uom
                kg = qty if is_kg else qty * (tmpl.craf_kg_per_pc or 0.0)
                packs = rest = 0
                per_pack = tmpl.craf_pcs_per_pack
                if not is_kg:
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
                    "packs_text": ("%s pachka + %s" % (packs, rest) if rest else "%s pachka" % packs) if per_pack and not is_kg else "",
                })
            items.sort(key=lambda r: (-r["kg"], -r["qty"]))
            zones.append({
                "id": loc.id,
                "name": loc.name,
                "full_name": loc.complete_name,
                "kind": loc.craf_map_kind or "process",
                "x": loc.craf_map_x, "y": loc.craf_map_y, "w": loc.craf_map_w, "h": loc.craf_map_h,
                "kg_total": kg_total,
                "pcs_total": pcs_total,
                "packs_total": packs_total,
                "product_count": len(items),
                "top": items[:top_limit],
            })

        by_name = {z["name"]: z["id"] for z in zones}
        flows = [
            {"from": by_name[a], "to": by_name[b], "label": label}
            for a, b, label in FLOWS if a in by_name and b in by_name
        ]
        return {
            "zones": zones,
            "flows": flows,
            "updated": fields.Datetime.to_string(fields.Datetime.now()),
        }
