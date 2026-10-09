from collections import OrderedDict

from odoo import Command, api, models
from odoo.exceptions import UserError

from .craf_paint_batch import packs_text

UNIT_FIELDS = {"craf_pcs_per_pack": int, "craf_pkg_kg": float, "craf_pkg_name": str}


class CrafKunlikHisobot(models.AbstractModel):
    _inherit = "craf.kunlik.hisobot"

    # ------------------------------------------------------------------ hisobot jadvallari
    def _rows(self, bucket):
        rows = super()._rows(bucket)
        Product = self.env["product.product"]
        for row in rows:
            product = Product.browse(row["product_id"])
            per_pack = product.craf_pcs_per_pack
            # faqat qadoqlanadigan (bo'yalgan) profil; bo'yalmagani korzinkada yuradi
            if per_pack and product.craf_color_id.is_painted and row["uom"] == "dona" and row["qty"] >= per_pack:
                row["packs"] = packs_text(row["qty"], per_pack)
        return rows

    # ------------------------------------------------------------------ kalkulyator
    def _calc_product_info(self, product):
        tmpl = product.product_tmpl_id
        is_kg = self._is_kg(product)
        if tmpl.craf_section_id:
            kind = "painted" if tmpl.craf_color_id.is_painted else "semi"
        else:
            kind = "kg" if is_kg else "other"
        return {
            "id": product.id,
            "code": product.default_code or "",
            "name": product.name,
            "label": "%s · %s" % (product.default_code, product.name) if product.default_code else product.name,
            "uom": "kg" if is_kg else self._uom(product),
            "kind": kind,
            "per_pack": tmpl.craf_pcs_per_pack or 0,
            "pkg_kg": tmpl.craf_pkg_kg or 0.0,
            "pkg_name": tmpl.craf_pkg_name or "qop",
            "kg_pc": tmpl.craf_kg_per_pc or 0.0,
        }

    @api.model
    def get_calc_products(self):
        kg = self.env.ref("uom.product_uom_kgm", raise_if_not_found=False)
        domain = [("is_storable", "=", True)]
        if kg:
            domain += ["|", ("craf_section_id", "!=", False), ("uom_id", "=", kg.id)]
        else:
            domain += [("craf_section_id", "!=", False)]
        products = self.env["product.product"].search(domain, order="default_code, name")
        return [self._calc_product_info(p) for p in products]

    @api.model
    def calc_set_unit(self, product_id, field, value):
        """Kalkulyatordan mahsulotning dona/pachka yoki o'ram og'irligini saqlash."""
        if field not in UNIT_FIELDS:
            raise UserError("Bu maydonni kalkulyatordan o'zgartirib bo'lmaydi.")
        product = self.env["product.product"].browse(int(product_id)).exists()
        if not product:
            raise UserError("Mahsulot topilmadi.")
        cast = UNIT_FIELDS[field]
        value = cast(value or (0 if cast is not str else ""))
        if cast is not str and value < 0:
            raise UserError("Manfiy qiymat bo'lmaydi.")
        product.product_tmpl_id.write({field: value})
        return self._calc_product_info(product)

    def _calc_rows(self, rows):
        """[(product, a, b)] — a: pachka / o'ram, b: dona / kg; bo'sh qatorlar tashlanadi."""
        Product = self.env["product.product"]
        result = []
        for row in rows or []:
            product = Product.browse(int(row.get("product_id") or 0)).exists()
            a = float(row.get("a") or 0)
            b = float(row.get("b") or 0)
            if product and (a or b):
                if a < 0 or b < 0:
                    raise UserError("%s: manfiy miqdor bo'lmaydi." % product.display_name)
                result.append((product, a, b))
        return result

    def _calc_kg(self, product, bags, kg):
        pkg = product.craf_pkg_kg
        if bags and not pkg:
            raise UserError("%s: \"1 o'ram, kg\" kiritilmagan." % product.display_name)
        return round(bags * pkg + kg, 3)

    @api.model
    def calc_to_paint(self, day, rows):
        """Bo'yash va qadoqlash yozuvini shu kunning qoralama bo'yash hujjatlariga yozadi (rang bo'yicha)."""
        day = self._parse_day(day)
        Batch = self.env["craf.paint.batch"]
        per_color = OrderedDict()
        kg_rows = OrderedDict()
        skipped = []
        for product, a, b in self._calc_rows(rows):
            tmpl = product.product_tmpl_id
            if tmpl.craf_section_id and tmpl.craf_color_id.is_painted:
                if a and not tmpl.craf_pcs_per_pack:
                    raise UserError("%s: \"dona / pachka\" kiritilmagan." % product.display_name)
                item = per_color.setdefault(tmpl.craf_color_id, OrderedDict()).setdefault(product, [0, 0])
                item[0] += int(a)
                item[1] += int(b)
            elif self._is_kg(product):
                item = kg_rows.setdefault(product, [0.0, 0.0])
                item[0] += a
                item[1] += self._calc_kg(product, a, b)
            else:
                skipped.append(product.display_name)
        if not per_color:
            raise UserError("Bo'yalgan profil qatori yo'q. Bo'yash hujjatiga bo'yalgan profillar yoziladi.")

        docs = []
        for color, items in per_color.items():
            batch = Batch.search([("date", "=", day), ("color_id", "=", color.id), ("state", "=", "draft")],
                                 order="id desc", limit=1)
            if not batch:
                batch = Batch.create({"date": day, "color_id": color.id})
            commands = []
            for product, (packs, extra) in items.items():
                packed = packs * product.craf_pcs_per_pack + extra
                line = batch.line_ids.filtered(lambda l, p=product: l.product_id == p)[:1]
                if line:
                    vals = {"out_packs": packs, "out_extra": extra}
                    vals.update(line._craf_packed_vals(packed))
                    commands.append(Command.update(line.id, vals))
                    continue
                semi = product.product_tmpl_id._craf_semi_product()
                if not semi:
                    skipped.append(product.display_name)
                    continue
                commands.append(Command.create({
                    "semi_product_id": semi.id, "product_id": product.id,
                    "out_packs": packs, "out_extra": extra, "pcs_in": packed, "pcs_in_auto": True,
                }))
            vals = {"line_ids": commands}
            powder = batch.powder_product_id
            if powder and powder in kg_rows:
                bags, kg = kg_rows.pop(powder)
                vals.update({"powder_bags": bags, "powder_qty": kg})
            batch.write(vals)
            docs.append(batch)
        skipped += [p.display_name for p in kg_rows]
        return self._calc_result(docs, skipped)

    @api.model
    def calc_to_melt(self, day, rows):
        """Pech yozuvini (kg / o'ram) shu kunning qoralama plavkasiga yozadi."""
        day = self._parse_day(day)
        Melt = self.env["craf.foundry.melt"]
        items = OrderedDict()
        skipped = []
        for product, a, b in self._calc_rows(rows):
            if not self._is_kg(product) or product.craf_section_id:
                skipped.append(product.display_name)
                continue
            item = items.setdefault(product, [0.0, 0.0])
            item[0] += a
            item[1] += self._calc_kg(product, a, b)
        if not items:
            raise UserError("Pech uchun kg dagi xom-ashyo qatori yo'q.")
        melt = Melt.search([("date", "=", day), ("state", "=", "draft")], order="id desc", limit=1)
        if not melt:
            melt = Melt.create({"date": day})
        commands = []
        seq = max(melt.line_ids.mapped("sequence") or [0])
        for product, (bags, kg) in items.items():
            line = melt.line_ids.filtered(lambda l, p=product: l.product_id == p)[:1]
            if line:
                commands.append(Command.update(line.id, {"qty": kg, "bags": bags}))
            else:
                seq += 1
                commands.append(Command.create({"sequence": seq, "product_id": product.id, "qty": kg, "bags": bags}))
        melt.write({"line_ids": commands})
        return self._calc_result(melt, skipped)

    def _calc_result(self, docs, skipped):
        return {
            "docs": [{"model": d._name, "id": d.id, "name": d.name} for d in docs],
            "skipped": skipped,
        }
