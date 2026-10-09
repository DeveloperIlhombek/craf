from collections import OrderedDict

from markupsafe import Markup, escape

from odoo import fields, models


def _n(value, digits=2):
    """1234.5 -> '1 234,50'; kichik sonlar uchun ko'proq raqam."""
    if value and abs(value) < 0.1 and digits < 4:
        digits = 4
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    if "," in text:
        text = text.rstrip("0").rstrip(",")
    return text


def _minutes(value):
    if value >= 60:
        return "%d soat %02d daq" % (int(value // 60), round(value % 60))
    return "%s daq" % _n(value, 1)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    craf_bom_id = fields.Many2one("mrp.bom", "Ishlab chiqarish me'yori", compute="_compute_craf_mrp")
    craf_stages_html = fields.Html("Bosqichlar", compute="_compute_craf_mrp", sanitize=False)
    craf_consumption_html = fields.Html("Xom-ashyo sarfi", compute="_compute_craf_mrp", sanitize=False)

    # ------------------------------------------------------------------ portlash
    def _craf_find_bom(self, product):
        return self.env["mrp.bom"]._bom_find(product, bom_type="normal")[product]

    def _craf_explode(self, product, qty, level, steps, raws, seen):
        bom = self._craf_find_bom(product)
        if not bom or product.id in seen:
            raws.setdefault(product, 0.0)
            raws[product] += qty
            return
        factor = qty / (bom.product_qty or 1.0)
        steps.append({
            "level": level,
            "bom": bom,
            "product": product,
            "qty": qty,
            "inputs": [(l.product_id, l.product_qty * factor) for l in bom.bom_line_ids],
            "byproducts": [(b.product_id, b.product_qty * factor) for b in bom.byproduct_ids],
            "operations": [(op, op.time_cycle_manual * factor) for op in bom.operation_ids],
        })
        for line in bom.bom_line_ids:
            self._craf_explode(line.product_id, line.product_qty * factor, level + 1, steps, raws,
                               seen | {product.id})

    def _compute_craf_mrp(self):
        for tmpl in self:
            product = tmpl.product_variant_id
            bom = tmpl._craf_find_bom(product) if product and tmpl.id else self.env["mrp.bom"]
            tmpl.craf_bom_id = bom
            if not bom:
                tmpl.craf_stages_html = False
                tmpl.craf_consumption_html = False
                continue
            per_pack = tmpl.craf_pcs_per_pack
            base = float(per_pack) if per_pack and tmpl.craf_section_id else bom.product_qty
            steps, raws = [], OrderedDict()
            tmpl._craf_explode(product, base, 0, steps, raws, frozenset())
            tmpl.craf_stages_html = tmpl._craf_render_stages(steps, base)
            tmpl.craf_consumption_html = tmpl._craf_render_consumption(raws, base)

    def _craf_qty_text(self, product, qty):
        uom = product.uom_id.name or ""
        text = "%s %s" % (_n(qty), uom)
        if product.craf_section_id and product.craf_kg_per_pc and uom != "kg":
            text += " <span class='text-muted'>(%s kg)</span>" % _n(qty * product.craf_kg_per_pc, 1)
        return text

    def _craf_render_stages(self, steps, base):
        unit = "pachka (%s dona)" % _n(base, 0) if self.craf_pcs_per_pack and self.craf_section_id else \
            "%s %s" % (_n(base), self.uom_id.name)
        rows = []
        for i, st in enumerate(sorted(steps, key=lambda s: -s["level"]), 1):
            bom = st["bom"]
            stage = escape(bom.picking_type_id.name or "Ishlab chiqarish")
            ops = "<br/>".join(
                "%s — %s <span class='text-muted'>(%s)</span>" % (
                    escape(op.name), escape(op.workcenter_id.name), _minutes(minutes))
                for op, minutes in st["operations"]) or "—"
            inputs = "<br/>".join("%s: <b>%s</b>" % (escape(p.display_name), self._craf_qty_text(p, q))
                                  for p, q in st["inputs"])
            outputs = "<b>%s</b>: %s" % (escape(st["product"].display_name), self._craf_qty_text(st["product"], st["qty"]))
            if st["byproducts"]:
                outputs += "<br/><span class='text-muted'>%s</span>" % "<br/>".join(
                    "+ %s: %s" % (escape(p.display_name), self._craf_qty_text(p, q)) for p, q in st["byproducts"])
            rows.append(
                "<tr><td class='text-nowrap'><span class='badge rounded-pill text-bg-primary me-1'>%s</span>"
                "<b>%s</b></td><td>%s</td><td>%s</td><td>%s</td></tr>" % (i, stage, ops, inputs, outputs))
        html = (
            "<p class='text-muted mb-2'>1 %s uchun, me'yorlar asosida. Qatorlar jarayon tartibida: "
            "Литейка → Press → Bo'yash → Qadoqlash.</p>"
            "<div class='table-responsive'><table class='table table-sm table-bordered align-top mb-0'>"
            "<thead class='table-light'><tr><th style='width: 12%%'>Bosqich</th>"
            "<th style='width: 24%%'>Operatsiya — ish markazi (vaqt)</th>"
            "<th style='width: 32%%'>Kiradi</th><th>Chiqadi</th></tr></thead><tbody>%s</tbody></table></div>"
        ) % (unit, "".join(rows))
        return Markup(html)

    def _craf_render_consumption(self, raws, base):
        per_pc = 1.0 / base if base else 0.0
        has_pack = bool(self.craf_pcs_per_pack and self.craf_section_id)
        head_unit = "1 dona" if has_pack else "1 %s" % (self.uom_id.name or "")
        rows = []
        total_kg = [0.0, 0.0, 0.0]
        for product, qty in sorted(raws.items(), key=lambda kv: -kv[1]):
            q1 = qty * per_pc
            cols = [q1, qty if has_pack else q1 * 100, q1 * 1000]
            uom = product.uom_id.name or ""
            if uom == "kg":
                for k in range(3):
                    total_kg[k] += cols[k]
            rows.append(
                "<tr><td>%s</td><td class='text-end'>%s</td><td class='text-end'>%s</td>"
                "<td class='text-end'>%s</td><td>%s</td></tr>" % (
                    escape(product.display_name), _n(cols[0], 3), _n(cols[1]), _n(cols[2], 1), escape(uom)))
        mid = "1 pachka (%s dona)" % _n(base, 0) if has_pack else "100 %s" % (self.uom_id.name or "")
        rows.append(
            "<tr class='fw-bold table-light'><td>Jami (kg)</td><td class='text-end'>%s</td>"
            "<td class='text-end'>%s</td><td class='text-end'>%s</td><td>kg</td></tr>" % (
                _n(total_kg[0], 3), _n(total_kg[1]), _n(total_kg[2], 1)))
        html = (
            "<p class='text-muted mb-2'>Barcha bosqichlar yig'indisi: faqat sotib olinadigan xom-ashyo "
            "(oraliq mahsulotlar — quyma, bo'yalmagan profil — ochib hisoblangan).</p>"
            "<div class='table-responsive'><table class='table table-sm table-hover mb-0'>"
            "<thead class='table-light'><tr><th>Xom-ashyo</th><th class='text-end'>%s</th>"
            "<th class='text-end'>%s</th><th class='text-end'>1000 %s</th><th>Birlik</th></tr></thead>"
            "<tbody>%s</tbody></table></div>"
        ) % (head_unit, mid, "dona" if has_pack else (self.uom_id.name or ""), "".join(rows))
        return Markup(html)

    # ------------------------------------------------------------------ tugmalar
    def action_craf_open_bom(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "mrp.bom",
            "res_id": self.craf_bom_id.id,
            "views": [(False, "form")],
        }

    def action_craf_bom_overview(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("mrp.action_report_mrp_bom")
        action["context"] = {"active_id": self.craf_bom_id.id, "active_model": "mrp.bom"}
        return action

    def action_craf_new_mo(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Ishlab chiqarish buyurtmasi",
            "res_model": "mrp.production",
            "views": [(False, "form")],
            "context": {
                "default_product_id": self.product_variant_id.id,
                "default_bom_id": self.craf_bom_id.id,
            },
        }
