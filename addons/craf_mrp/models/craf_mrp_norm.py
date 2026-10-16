import math

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

# Kimyo: mahsulot kodi -> me'yor maydoni
CHEM_FIELDS = [("XA-03", "chem_ac20"), ("XA-04", "chem_cr51"), ("XA-05", "chem_ac52")]


class CrafMrpNorm(models.Model):
    _name = "craf.mrp.norm"
    _description = "Craf ishlab chiqarish me'yorlari"
    _rec_name = "company_id"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)

    # Press
    press_yield_pct = fields.Float("Press chiqishi, %", default=85.0,
                                   help="Quyma kg dan necha foizi profilga aylanadi.")
    press_rest_pct = fields.Float("Press qoldig'i (питак), %", default=8.0)
    press_scrap_pct = fields.Float("Press braki, %", default=5.0)
    press_kg_h = fields.Float("Press unumdorligi, kg/soat", default=450.0)
    # Bo'yash
    paint_defect_pct = fields.Float("Bo'yash braki, %", default=1.5)
    powder_g_m2 = fields.Float("Kukun, g/m²", default=120.0)
    chem_ac20 = fields.Float("POLITOKSAL AC 20, kg/m²", default=0.012, digits=(16, 4))
    chem_cr51 = fields.Float("ALUPOL CR 51, kg/m²", default=0.008, digits=(16, 4))
    chem_ac52 = fields.Float("ALUPOL AC 52, kg/m²", default=0.006, digits=(16, 4))
    paint_m2_h = fields.Float("Bo'yash liniyasi, m²/soat", default=60.0)
    # Литейка va qadoqlash
    foundry_kg_h = fields.Float("Pech unumdorligi, kg/soat", default=800.0)
    pack_min = fields.Float("Qadoqlash, daqiqa/pachka", default=3.0)
    film_kg_per_pack = fields.Float("Plyonka, kg/pachka", default=0.05, digits=(16, 3),
                                    help="Bo'yash smenasida plyonka sarfi shu me'yor × pachka soni bilan taklif qilinadi")
    tape_m_per_pack = fields.Float("Lenta, m/pachka", default=3.0, digits=(16, 2))

    # Bosqich operatsiya turlari va ish markazlari
    foundry_type_id = fields.Many2one("stock.picking.type", "Литейка bosqichi", domain=[("code", "=", "mrp_operation")])
    press_type_id = fields.Many2one("stock.picking.type", "Press bosqichi", domain=[("code", "=", "mrp_operation")])
    press_pack_type_id = fields.Many2one("stock.picking.type", "Press → Qadoqlash bosqichi",
                                         domain=[("code", "=", "mrp_operation")])
    paint_type_id = fields.Many2one("stock.picking.type", "Bo'yash bosqichi", domain=[("code", "=", "mrp_operation")])
    wc_foundry_id = fields.Many2one("mrp.workcenter", "Pech")
    wc_press_id = fields.Many2one("mrp.workcenter", "Asosiy press")
    wc_press_alt_id = fields.Many2one("mrp.workcenter", "Muqobil press")
    wc_paint_id = fields.Many2one("mrp.workcenter", "Bo'yash liniyasi")
    wc_pack_id = fields.Many2one("mrp.workcenter", "Qadoqlash")

    bom_count = fields.Integer("Craf BoM lar", compute="_compute_bom_count")
    last_run = fields.Datetime("Oxirgi hisoblash", readonly=True)
    last_result = fields.Text("Natija", readonly=True)

    _company_uniq = models.Constraint("unique(company_id)", "Har bir kompaniyada bitta me'yorlar yozuvi bo'ladi.")

    def _compute_bom_count(self):
        for norm in self:
            norm.bom_count = self.env["mrp.bom"].search_count([("craf_auto", "=", True)])

    # ------------------------------------------------------------------ yordamchi
    @api.model
    def _get_norm(self, company=None):
        company = company or self.env.company
        norm = self.sudo().search([("company_id", "=", company.id)], limit=1)
        if not norm:
            norm = self.sudo().create({"company_id": company.id})
        return norm.sudo(False)

    @api.model
    def action_open(self):
        norm = self._get_norm()
        return {
            "type": "ir.actions.act_window",
            "name": "Ishlab chiqarish me'yorlari",
            "res_model": "craf.mrp.norm",
            "res_id": norm.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def _product(self, code):
        return self.env["product.product"].search([("default_code", "=", code)], limit=1)

    def action_view_boms(self):
        action = self.env["ir.actions.act_window"]._for_xml_id("mrp.mrp_bom_form_action")
        action["domain"] = [("craf_auto", "=", True)]
        action["context"] = {}
        return action

    # ------------------------------------------------------------------ BoM sinxronlash
    def _sync_bom(self, tmpl, base_qty, picking_type, operations, lines, byproducts):
        """tmpl uchun Craf BoM ni yaratadi yoki yangilaydi.

        operations: [(name, workcenter, minutes, alt_workcenter)]
        lines: [(product, qty, op_name)]
        byproducts: [(product, qty, op_name)]
        """
        Bom = self.env["mrp.bom"]
        bom = Bom.search([("product_tmpl_id", "=", tmpl.id), ("craf_auto", "=", True)], limit=1)
        if not bom:
            if Bom.search_count([("product_tmpl_id", "=", tmpl.id), ("type", "=", "normal")]):
                return "manual"
            bom = Bom.create({
                "product_tmpl_id": tmpl.id,
                "product_qty": base_qty,
                "product_uom_id": tmpl.uom_id.id,
                "type": "normal",
                "craf_auto": True,
            })
            state = "created"
        else:
            state = "updated"
        bom.write({
            "product_qty": base_qty,
            "code": "Craf me'yori",
            "consumption": "flexible",
            "picking_type_id": picking_type.id if picking_type else False,
            "ready_to_produce": "asap",
        })
        # operatsiyalar: nomi bo'yicha yangilanadi (ish buyurtmalari bog'langan bo'lishi mumkin)
        ops_by_name = {op.name: op for op in bom.operation_ids}
        keep = self.env["mrp.routing.workcenter"]
        for seq, (name, wc, minutes, alt) in enumerate(operations, 1):
            vals = {
                "name": name,
                "workcenter_id": wc.id,
                "time_mode": "manual",
                "time_cycle_manual": max(round(minutes, 2), 0.1),
                "sequence": seq * 10,
            }
            op = ops_by_name.get(name)
            if op:
                op.write(vals)
            else:
                op = self.env["mrp.routing.workcenter"].create(dict(vals, bom_id=bom.id))
            if alt:
                wc.alternative_workcenter_ids = [Command.link(alt.id)]
            keep |= op
        obsolete = bom.operation_ids - keep
        if obsolete:
            try:
                with self.env.cr.savepoint():
                    obsolete.unlink()
            except Exception:  # ish buyurtmasi bog'langan bo'lsa, arxivlanadi
                obsolete.write({"active": False})
        ops = {op.name: op for op in keep}
        bom.write({
            "bom_line_ids": [Command.clear()] + [Command.create({
                "product_id": product.id,
                "product_qty": round(qty, 2),
                "product_uom_id": product.uom_id.id,
                "operation_id": ops[op_name].id if op_name in ops else False,
            }) for product, qty, op_name in lines if product and qty > 0.004],
            "byproduct_ids": [Command.clear()] + [Command.create({
                "product_id": product.id,
                "product_qty": round(qty, 2),
                "product_uom_id": product.uom_id.id,
                "operation_id": ops[op_name].id if op_name in ops else False,
            }) for product, qty, op_name in byproducts if product and qty > 0.004],
        })
        return state

    def action_generate_boms(self):
        """Barcha profillar va quyma uchun BoM larni me'yorlardan hisoblaydi."""
        self.ensure_one()
        if not (self.wc_foundry_id and self.wc_press_id and self.wc_paint_id and self.wc_pack_id):
            raise UserError("Ish markazlari belgilanmagan (Pech, Press, Bo'yash liniyasi, Qadoqlash).")
        y = self.press_yield_pct / 100.0
        if not 0.3 <= y <= 1.0:
            raise UserError("Press chiqishi 30% dan 100% gacha bo'lishi kerak.")
        defect = min(max(self.paint_defect_pct, 0.0), 50.0) / 100.0
        billet = self._product("XA-09")
        rest_p, scrap_p = self._product("PF-06"), self._product("PF-07")
        chems = [(self._product(code), getattr(self, fname)) for code, fname in CHEM_FIELDS]
        counts = {"created": 0, "updated": 0, "manual": 0}
        skipped = []
        manufacture = self.env.ref("mrp.route_warehouse0_manufacture", raise_if_not_found=False)
        with_bom = self.env["product.template"]

        # 1) Quyma: mavjud shixta retsepti (Литейка) — bosqich turi va operatsiya qo'shiladi
        if billet:
            Bom = self.env["mrp.bom"]
            bom = Bom.search([("product_tmpl_id", "=", billet.product_tmpl_id.id), ("type", "=", "normal")], limit=1)
            if bom:
                bom.craf_auto = True
                lines = [(l.product_id, l.product_qty, "Eritish va quyish") for l in bom.bom_line_ids]
                slag = self._product("PF-14")
                state = self._sync_bom(
                    billet.product_tmpl_id, bom.product_qty, self.foundry_type_id,
                    [("Eritish va quyish", self.wc_foundry_id, bom.product_qty / max(self.foundry_kg_h, 1) * 60, False)],
                    lines, [(slag, bom.product_qty * 0.02, "Eritish va quyish")] if slag else [])
                counts[state] += 1
                with_bom |= billet.product_tmpl_id
            else:
                skipped.append("Quyma (XA-09): shixta retsepti yo'q")

        # 2) Profillar
        Tmpl = self.env["product.template"]
        for tmpl in Tmpl.search([("craf_section_id", "!=", False)], order="default_code"):
            section = tmpl.craf_section_id
            per_pack = tmpl.craf_pcs_per_pack
            base = float(per_pack or 100)
            kg_pc = tmpl.craf_kg_per_pc
            if tmpl.craf_color_id.is_painted:
                semi = tmpl._craf_semi_product()
                if not semi:
                    skipped.append("%s: bo'yalmagan yarim tayyor mahsulot topilmadi" % tmpl.display_name)
                    continue
                area_pc = (tmpl.craf_length_m or 0.0) * (section.perimeter_m or 0.0)
                semi_qty = base / (1.0 - defect)
                area = semi_qty * area_pc
                op_paint, op_pack = "Kukun bo'yash", "Qadoqlash"
                lines = [(semi, semi_qty, op_paint)]
                powder = tmpl.craf_color_id.paint_tmpl_id.product_variant_id
                if powder and area:
                    lines.append((powder, area * self.powder_g_m2 / 1000.0, op_paint))
                for chem, per_m2 in chems:
                    if chem and area:
                        lines.append((chem, area * per_m2, op_paint))
                byproducts = [(scrap_p, (semi_qty - base) * kg_pc, op_paint)] if kg_pc else []
                paint_min = (area / max(self.paint_m2_h, 1) * 60) if area else base * 0.5
                ops = [
                    (op_paint, self.wc_paint_id, paint_min, False),
                    (op_pack, self.wc_pack_id, self.pack_min * math.ceil(base / (per_pack or base)), False),
                ]
                if not area:
                    skipped.append("%s: kesim perimetri yo'q — kukun hisoblanmadi" % tmpl.display_name)
                state = self._sync_bom(tmpl, base, self.paint_type_id, ops, lines, byproducts)
            else:
                if not kg_pc or not billet:
                    skipped.append("%s: kg/m yoki uzunlik yo'q — quyma sarfi hisoblanmadi" % tmpl.display_name)
                    continue
                billet_qty = base * kg_pc / y
                op_press = "Presslash va kesish"
                ops = [(op_press, self.wc_press_id, base * kg_pc / max(self.press_kg_h, 1) * 60, self.wc_press_alt_id)]
                picking_type = self.press_type_id
                if tmpl.sale_ok:
                    ops.append(("Qadoqlash", self.wc_pack_id,
                                self.pack_min * math.ceil(base / (per_pack or base)), False))
                    picking_type = self.press_pack_type_id
                byproducts = [
                    (rest_p, billet_qty * self.press_rest_pct / 100.0, op_press),
                    (scrap_p, billet_qty * self.press_scrap_pct / 100.0, op_press),
                ]
                state = self._sync_bom(tmpl, base, picking_type, ops, [(billet, billet_qty, op_press)], byproducts)
            counts[state] += 1
            if state != "manual":
                with_bom |= tmpl

        if manufacture and with_bom:
            with_bom.write({"route_ids": [Command.link(manufacture.id)]})
        result = "Yaratildi: %s, yangilandi: %s, qo'lda kiritilgan (tegilmadi): %s." % (
            counts["created"], counts["updated"], counts["manual"])
        if skipped:
            result += "\nO'tkazib yuborildi (%s):\n- %s" % (len(skipped), "\n- ".join(skipped[:40]))
        self.write({"last_run": fields.Datetime.now(), "last_result": result})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success" if not skipped else "warning",
                "title": "BoM lar hisoblandi",
                "message": result.split("\n")[0] + (" %s ta mahsulot o'tkazib yuborildi." % len(skipped) if skipped else ""),
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }
