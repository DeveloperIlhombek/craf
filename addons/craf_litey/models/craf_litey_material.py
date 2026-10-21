"""Литейка materiallari: ro'yxat, yaratish, tahrirlash, o'chirish / ro'yxatdan chiqarish, qaytarish.

Material — Odoo dagi oddiy mahsulot (Inventarizatsiya → Mahsulotlar). Литейка ga tegishliligi
`craf_litey_seq > 0` bilan belgilanadi, shuning uchun bu yerda yaratilgan material Inventarizatsiya,
Xarid va Excel eksportida ham ko'rinadi.
"""
import re

import pytz

from odoo import api, models
from odoo.exceptions import UserError

KINDS = {"metal": "Metall", "aux": "Qo'shimcha / sarf"}
CODE_PREFIX = {"metal": "PF", "aux": "LS"}
UOM_REFS = [("uom.product_uom_kgm", "kg"), ("uom.product_uom_unit", "dona"), ("craf_litey.uom_roll", "рул")]


class CrafLiteyHisobot(models.AbstractModel):
    _inherit = "craf.litey.hisobot"

    # ------------------------------------------------------------------ yordamchi
    def _uom_options(self):
        res = []
        for xmlid, label in UOM_REFS:
            uom = self.env.ref(xmlid, raise_if_not_found=False)
            if uom:
                res.append({"id": uom.id, "label": label})
        return res

    @api.model
    def _next_code(self, kind):
        prefix = CODE_PREFIX.get(kind, "PF")
        codes = self.env["product.product"].with_context(active_test=False).search_read(
            [("default_code", "=like", prefix + "-%")], ["default_code"])
        numbers = [int(m.group(1)) for c in codes
                   if (m := re.match(r"^%s-(\d+)$" % prefix, c["default_code"] or ""))]
        return "%s-%02d" % (prefix, (max(numbers) if numbers else 0) + 1)

    def _has_history(self, product):
        """Hujjatlarda ishlatilganmi (o'chirib bo'lmaydi, faqat ro'yxatdan chiqariladi)."""
        env = self.env
        if env["stock.move"].search_count([("product_id", "=", product.id)], limit=1):
            return True
        if env["stock.quant"].search_count([("product_id", "=", product.id)], limit=1):
            return True
        if env["craf.foundry.melt.line"].search_count([("product_id", "=", product.id)], limit=1):
            return True
        if env["mrp.bom.line"].search_count([("product_id", "=", product.id)], limit=1):
            return True
        for model in ("purchase.order.line", "sale.order.line"):
            if model in env and env[model].search_count([("product_id", "=", product.id)], limit=1):
                return True
        return False

    def _last_price(self, product):
        move = self.env["stock.move"].search([
            ("product_id", "=", product.id), ("state", "=", "done"), ("craf_price", ">", 0),
            ("picking_id.picking_type_id.code", "=", "incoming")], order="date desc, id desc", limit=1)
        return move.craf_price if move else 0.0

    def _material_dict(self, product):
        tmpl = product.product_tmpl_id
        return {
            "product_id": product.id,
            "tmpl_id": tmpl.id,
            "name": product.name,
            "code": product.default_code or "",
            "excel_name": tmpl.craf_litey_name or "",
            "name_1c": tmpl.craf_name_1c or "",
            "kind": "aux" if tmpl.craf_not_metal else "metal",
            "uom_id": product.uom_id.id,
            "uom": self._uom(product),
            "melt": tmpl.craf_melt_seq > 0,
            "min_qty": tmpl.craf_min_qty,
            "location_id": tmpl.craf_litey_location_id.id or False,
            "location": tmpl.craf_litey_location_id.name or "",
            "hidden": tmpl.craf_litey_hidden,
            "on_hand": round(product.qty_available, 3),
        }

    def _check_manager(self):
        self._check_editor()

    # ------------------------------------------------------------------ o'qish
    @api.model
    def material_options(self):
        loc = self._litey_location()
        return {
            "kinds": [{"key": k, "label": v} for k, v in KINDS.items()],
            "uoms": self._uom_options(),
            "locations": [{"id": l.id, "name": l.name} for l in self.env["stock.location"].search(
                [("usage", "=", "internal"), ("company_id", "in", [self.env.company.id, False])], order="name")],
            "litey_location_id": loc.id or False,
            "next_codes": {k: self._next_code(k) for k in KINDS},
        }

    @api.model
    def material_get(self, product_id):
        product = self.env["product.product"].browse(int(product_id)).exists()
        if not product:
            raise UserError("Material topilmadi (o'chirilgan bo'lishi mumkin).")
        res = self._material_dict(product)
        res["can_delete"] = not self._has_history(product)
        return res

    @api.model
    def material_hidden(self):
        return [self._material_dict(p) for p in self._products(hidden=True)]

    @api.model
    def material_detail(self, product_id, limit=25):
        product = self.env["product.product"].browse(int(product_id)).exists()
        if not product:
            raise UserError("Material topilmadi (o'chirilgan bo'lishi mumkin).")
        res = self._material_dict(product)
        res["can_delete"] = not self._has_history(product)
        res["locs"] = self._by_location(product).get(product.id, [])
        res["last_price"] = self._last_price(product)
        res["melt_count"] = self.env["craf.foundry.melt.line"].search_count(
            [("product_id", "=", product.id), ("qty", ">", 0), ("melt_id.state", "=", "done")])
        moves = self.env["stock.move"].search(
            [("product_id", "=", product.id), ("state", "=", "done")], order="date desc, id desc", limit=limit)
        tz = self._tz()
        rows = []
        for mv in moves:
            src, dst = mv.location_id.usage, mv.location_dest_id.usage
            qty = mv.product_uom._compute_quantity(mv.quantity, product.uom_id)
            if src == "internal" and dst == "internal":
                sign, label = 0, "Ko'chirish"
            elif mv.is_inventory:
                sign, label = (1 if dst == "internal" else -1), "Sanash / tuzatish"
            elif dst == "internal":
                sign = 1
                label = {"supplier": "Kirim", "production": "Ishlab chiqarildi", "customer": "Qaytdi"}.get(src, "Kirim")
            else:
                sign = -1
                label = {"production": "Sarf", "customer": "Chiqim (sotuv)", "supplier": "Qaytarildi"}.get(dst, "Chiqim")
            mo = mv.raw_material_production_id or mv.production_id
            if sign == 0:
                place = "%s → %s" % (mv.location_id.name, mv.location_dest_id.name)
            else:
                place = (mv.location_dest_id if sign > 0 else mv.location_id).name
            rows.append({
                "id": mv.id,
                "date_label": pytz.utc.localize(mv.date).astimezone(tz).strftime("%d.%m.%Y %H:%M"),
                "label": label,
                "reference": mv.reference or "",
                "origin": (mo.origin if mo else mv.picking_id.origin) or "",
                "from": mv.location_id.name, "to": mv.location_dest_id.name,
                "qty": round(qty, 3), "sign": sign, "place": place, "adj": bool(mv.is_inventory),
            })
        res["moves"] = rows
        return res

    # ------------------------------------------------------------------ yozish
    @api.model
    def material_save(self, vals):
        """Yangi material yaratadi yoki mavjudini o'zgartiradi. vals: name, code, kind, uom_id, excel_name,
        name_1c, melt, min_qty, location_id; tahrirlashda product_id."""
        self._check_manager()
        Product = self.env["product.product"].with_context(active_test=False)
        product = Product.browse(int(vals["product_id"])).exists() if vals.get("product_id") else Product
        if vals.get("product_id") and not product:
            raise UserError("Material topilmadi (o'chirilgan bo'lishi mumkin).")
        kind = vals.get("kind") if vals.get("kind") in KINDS else "metal"
        name = re.sub(r"\s+", " ", (vals.get("name") or "")).strip()
        if len(name) < 2:
            raise UserError("Material nomini yozing.")
        code = re.sub(r"\s+", "", vals.get("code") or "").upper() or (product.default_code if product else "")
        if not code:
            code = self._next_code(kind)
        dup = Product.search([("default_code", "=ilike", code), ("id", "!=", product.id or 0)], limit=1)
        if dup:
            raise UserError("«%s» kodi band: %s. Boshqa kod yozing yoki bo'sh qoldiring (avtomatik beriladi)." % (
                code, dup.display_name))
        same = self._products().filtered(lambda p: p.id != product.id and p.name.strip().lower() == name.lower())
        if same:
            raise UserError("«%s» nomli material Литейка ro'yxatida allaqachon bor (%s)." % (
                name, same[0].default_code or ""))
        uom_ids = [u["id"] for u in self._uom_options()]
        uom = self.env["uom.uom"].browse(int(vals.get("uom_id") or 0))
        if uom.id not in uom_ids:
            if product:
                uom = product.uom_id
            else:
                raise UserError("O'lchov birligini tanlang: kg, dona yoki рул.")
        location = self.env["stock.location"].browse(int(vals.get("location_id") or 0)).exists()
        if location and location.usage != "internal":
            raise UserError("Asosiy joy ichki joy (ombor/sex) bo'lishi kerak.")
        tvals = {
            "name": name,
            "default_code": code,
            "craf_not_metal": kind == "aux",
            "craf_litey_name": (vals.get("excel_name") or "").strip() or False,
            "craf_name_1c": (vals.get("name_1c") or "").strip() or False,
            "craf_min_qty": max(float(vals.get("min_qty") or 0.0), 0.0),
            "craf_litey_location_id": location.id or self._litey_location().id or False,
        }
        # huquq _check_manager da tekshirildi (ombor mudiri); mahsulot kartochkasini yozish Inventarizatsiya
        # mahsulot menejeri huquqini talab qiladi — shuning uchun sudo
        Tmpl = self.env["product.template"].sudo().with_context(active_test=False)
        all_litey = Tmpl.search([("craf_litey_seq", ">", 0)])
        melt = bool(vals.get("melt"))
        if not product:
            same_kind = all_litey.filtered(lambda t: bool(t.craf_not_metal) == (kind == "aux"))
            categ = self.env.ref("craf_nomenklatura.categ_semi" if kind == "metal" else "craf_litey.categ_litey_aux",
                                 raise_if_not_found=False)
            tvals.update({
                "type": "consu",
                "is_storable": True,
                "uom_id": uom.id,
                "sale_ok": False,
                "purchase_ok": True,
                "craf_litey_seq": max(all_litey.mapped("craf_litey_seq") or [0]) + 10,
                "craf_melt_seq": (max(same_kind.mapped("craf_melt_seq") or [0]) + 10) if melt else 0,
            })
            if categ:
                tvals["categ_id"] = categ.id
            tmpl = Tmpl.create(tvals)
            product = tmpl.product_variant_id
            tmpl.message_post(body="Литейка hisobotidan yaratildi (%s)." % KINDS[kind])
        else:
            tmpl = product.product_tmpl_id.sudo()
            if uom != product.uom_id:
                if self.env["stock.move"].search_count([("product_id", "=", product.id)], limit=1):
                    raise UserError("O'lchov birligini o'zgartirib bo'lmaydi: «%s» bo'yicha ombor harakatlari bor. "
                                    "Kerak bo'lsa, yangi material yarating." % product.name)
                tvals["uom_id"] = uom.id
            if melt and tmpl.craf_melt_seq <= 0:
                same_kind = all_litey.filtered(lambda t: bool(t.craf_not_metal) == (kind == "aux"))
                tvals["craf_melt_seq"] = max(same_kind.mapped("craf_melt_seq") or [0]) + 10
            elif not melt:
                tvals["craf_melt_seq"] = 0
            kind_changed = bool(tmpl.craf_not_metal) != (kind == "aux")
            tmpl.write(tvals)
            if kind_changed:
                # qoralama plavkalarda bu material to'g'ri blokka (shixta / sarf buyumi) o'tadi
                lines = self.env["craf.foundry.melt.line"].search(
                    [("product_id", "=", product.id), ("melt_id.state", "=", "draft")])
                lines.write({"is_metal": kind == "metal"})
        return self.material_get(product.id)

    @api.model
    def material_remove(self, product_id):
        """Hujjatlarda ishlatilmagan material o'chiriladi; ishlatilgani Литейка ro'yxatidan chiqariladi
        (mahsulot va tarixi Inventarizatsiya da qoladi, keyin qaytarish mumkin)."""
        self._check_manager()
        product = self.env["product.product"].with_context(active_test=False).browse(int(product_id)).exists()
        if not product:
            raise UserError("Material topilmadi.")
        name = product.display_name
        if not self._has_history(product):
            tmpl = product.product_tmpl_id.sudo()
            try:
                with self.env.cr.savepoint():
                    tmpl.unlink()
                return {"result": "deleted", "name": name}
            except Exception:  # noqa: BLE001 — boshqa modul bog'lagan bo'lsa, ro'yxatdan chiqaramiz
                product = self.env["product.product"].with_context(active_test=False).browse(int(product_id))
        product.product_tmpl_id.sudo().craf_litey_hidden = True
        # qoralama plavkalardagi bo'sh qatorlari olib tashlanadi
        self.env["craf.foundry.melt.line"].search([
            ("product_id", "=", product.id), ("melt_id.state", "=", "draft"), ("qty", "<=", 0)]).unlink()
        return {"result": "hidden", "name": name, "on_hand": round(product.qty_available, 3),
                "uom": self._uom(product)}

    @api.model
    def material_restore(self, product_id):
        self._check_manager()
        product = self.env["product.product"].with_context(active_test=False).browse(int(product_id)).exists()
        if not product:
            raise UserError("Material topilmadi.")
        product.product_tmpl_id.sudo().write({"craf_litey_hidden": False, "active": True})
        return self.material_get(product.id)
