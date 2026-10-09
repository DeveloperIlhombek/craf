import math

from odoo import api, fields, models

EPS = 1e-9


class CrafCalculator(models.TransientModel):
    _name = "craf.calculator"
    _description = "Pachka / dona / metr / kg kalkulyatori"

    # Majburiy emas: sahifadan chiqib ketganda bo'sh kalkulyator xato bermasligi uchun
    product_id = fields.Many2one(
        "product.product", string="Mahsulot",
        domain=[("craf_section_id", "!=", False)])
    mode = fields.Selection(
        [("pack", "Pachka"), ("pcs", "Dona"), ("m", "Metr"), ("kg", "Kg")],
        string="Nimani kiritasiz", default="pack", required=True)
    in_packs = fields.Integer("Pachka")
    in_extra_pcs = fields.Integer("+ dona")
    in_pcs = fields.Integer("Dona")
    in_m = fields.Float("Metr", digits=(16, 2))
    in_kg = fields.Float("Kg", digits=(16, 2))

    # Mahsulotdan olinadi, lekin shu yerda o'zgartirib, "Saqlash" bilan mahsulotga yozish mumkin
    kg_per_m = fields.Float(
        "kg/m", digits=(10, 4), compute="_compute_params", store=True, readonly=False,
        help="Kesimning 1 metr og'irligi. Saqlansa, shu kesimdagi barcha mahsulotlarga taalluqli.")
    length_m = fields.Float(
        "Uzunlik, m", digits=(10, 3), compute="_compute_params", store=True, readonly=False)
    pcs_per_pack = fields.Integer(
        "Dona / pachka", compute="_compute_params", store=True, readonly=False)
    params_changed = fields.Boolean(compute="_compute_params_changed")
    res_text = fields.Char("Natija", compute="_compute_result")

    res_pcs = fields.Integer("Jami dona", compute="_compute_result")
    res_packs = fields.Integer("Natija: pachka", compute="_compute_result")
    res_rest = fields.Integer("Qoldiq dona", compute="_compute_result")
    res_m = fields.Float("Jami metr", digits=(16, 2), compute="_compute_result")
    res_kg = fields.Float("Kg (nazariy)", digits=(16, 2), compute="_compute_result")
    warning = fields.Char(compute="_compute_result")

    stock_text = fields.Char("Omborda (umumiy)", compute="_compute_stock")
    free_text = fields.Char("Erkin miqdor", compute="_compute_stock")
    stock_kg = fields.Float("Omborda, kg", digits=(16, 1), compute="_compute_stock")

    def _compute_display_name(self):
        for wiz in self:
            wiz.display_name = "Kalkulyator"

    @api.model
    def _calc(self, mode, length_m, kg_per_m, per_pack, packs=0, extra=0, pcs=0, meters=0.0, kg=0.0):
        """Asosiy hisob: kiritilgan qiymatdan jami donani topadi, qolganini undan chiqaradi."""
        if mode == "pack":
            total = (packs or 0) * (per_pack or 0) + (extra or 0)
        elif mode == "pcs":
            total = pcs or 0
        elif mode == "m":
            total = int(math.floor(meters / length_m + EPS)) if length_m else 0
        else:
            unit = (length_m or 0.0) * (kg_per_m or 0.0)
            total = int(math.floor(kg / unit + EPS)) if unit else 0
        total = max(total, 0)
        packs_out, rest = divmod(total, per_pack) if per_pack else (0, total)
        meters_out = total * (length_m or 0.0)
        return {
            "pcs": total,
            "packs": packs_out,
            "rest": rest,
            "m": meters_out,
            "kg": meters_out * (kg_per_m or 0.0),
        }

    @api.depends("product_id")
    def _compute_params(self):
        for wiz in self:
            tmpl = wiz.product_id.product_tmpl_id
            wiz.kg_per_m = tmpl.craf_section_id.kg_per_m
            wiz.length_m = tmpl.craf_length_m
            wiz.pcs_per_pack = tmpl.craf_pcs_per_pack

    @api.depends("product_id", "kg_per_m", "length_m", "pcs_per_pack")
    def _compute_params_changed(self):
        for wiz in self:
            tmpl = wiz.product_id.product_tmpl_id
            wiz.params_changed = bool(wiz.product_id) and (
                abs((wiz.kg_per_m or 0.0) - (tmpl.craf_section_id.kg_per_m or 0.0)) > 1e-9
                or abs((wiz.length_m or 0.0) - (tmpl.craf_length_m or 0.0)) > 1e-9
                or (wiz.pcs_per_pack or 0) != (tmpl.craf_pcs_per_pack or 0))

    @api.depends("product_id", "mode", "in_packs", "in_extra_pcs", "in_pcs", "in_m", "in_kg",
                 "kg_per_m", "length_m", "pcs_per_pack")
    def _compute_result(self):
        for wiz in self:
            missing = []
            if not wiz.kg_per_m:
                missing.append("kg/m")
            if not wiz.length_m:
                missing.append("uzunlik")
            if not wiz.pcs_per_pack:
                missing.append("dona/pachka")
            wiz.warning = (
                "Kiritilmagan: %s. Chapdagi maydonlarga yozing va \"Mahsulotga saqlash\" ni bosing."
                % ", ".join(missing)) if (wiz.product_id and missing) else False
            res = self._calc(
                wiz.mode, wiz.length_m, wiz.kg_per_m, wiz.pcs_per_pack,
                packs=wiz.in_packs, extra=wiz.in_extra_pcs, pcs=wiz.in_pcs, meters=wiz.in_m, kg=wiz.in_kg)
            wiz.res_pcs = res["pcs"]
            wiz.res_packs = res["packs"]
            wiz.res_rest = res["rest"]
            wiz.res_m = res["m"]
            wiz.res_kg = res["kg"]
            if wiz.pcs_per_pack:
                wiz.res_text = "%s pachka + %s dona" % (res["packs"], res["rest"]) if res["rest"] else "%s pachka" % res["packs"]
            else:
                wiz.res_text = "%s dona" % res["pcs"]

    def action_save_params(self):
        """kg/m ni kesimga, uzunlik va dona/pachka ni mahsulotga yozadi; kalkulyator sahifasi ochiq qoladi."""
        self.ensure_one()
        if not self.product_id:
            return True
        tmpl = self.product_id.product_tmpl_id
        if tmpl.craf_section_id and abs((self.kg_per_m or 0.0) - (tmpl.craf_section_id.kg_per_m or 0.0)) > 1e-9:
            tmpl.craf_section_id.kg_per_m = self.kg_per_m
        vals = {}
        if abs((self.length_m or 0.0) - (tmpl.craf_length_m or 0.0)) > 1e-9:
            vals["craf_length_m"] = self.length_m
        if (self.pcs_per_pack or 0) != (tmpl.craf_pcs_per_pack or 0):
            vals["craf_pcs_per_pack"] = self.pcs_per_pack
        if vals:
            tmpl.write(vals)
        # Sahifa rejimi: shu yozuvda qolamiz, forma yangilanadi
        return True

    @api.depends("product_id")
    def _compute_stock(self):
        for wiz in self:
            tmpl = wiz.product_id.product_tmpl_id
            if not wiz.product_id:
                wiz.stock_text = wiz.free_text = False
                wiz.stock_kg = 0.0
                continue
            wiz.stock_text = tmpl._craf_packs_text(wiz.product_id.qty_available, tmpl.craf_pcs_per_pack)
            wiz.free_text = tmpl._craf_packs_text(wiz.product_id.free_qty, tmpl.craf_pcs_per_pack)
            wiz.stock_kg = wiz.product_id.qty_available * (tmpl.craf_kg_per_pc or 0.0)
