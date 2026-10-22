from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, NORM_STATUS, fmt

BILLET_CODES = ("XA-09", "XA-02")


class CrafExtrusionShift(models.Model):
    _name = "craf.extrusion.shift"
    _description = "Press smenasi"
    _inherit = ["craf.production.mixin", "mail.activity.mixin"]
    _craf_weighted_avg = {
        "yield_pct": ("output_kg", "billet_qty", 100.0),
        "productivity": ("output_kg", "duration", 1.0),
    }
    _order = "date desc, id desc"

    _craf_sequence_code = "craf.extrusion.shift"
    _craf_stage = "press"
    _craf_default_src = "Press sexi"
    _craf_default_waste = "Литейка"  # brak profil va питак Liteykada qayta eritiladi

    section_id = fields.Many2one("craf.profile.section", string="Matritsa (kesim)", tracking=True,
                                 help="Bir varaqda bir nechta profil bo'lsa — eng ko'p chiqqani (norma shundan olinadi).")
    die_code = fields.Char(related="section_id.die_code", string="Matritsa kodi")
    kg_per_m = fields.Float(related="section_id.kg_per_m", string="kg/m")
    billet_product_id = fields.Many2one(
        "product.product", string="Quyma", required=True,
        domain=[("default_code", "in", BILLET_CODES)],
        default=lambda self: self._craf_product("XA-09"))
    melt_ids = fields.Many2many(
        "craf.foundry.melt", string="Quyma partiyasi (plavka)", domain=[("state", "=", "done")])
    billet_qty = fields.Float("Quyma sarfi, kg", digits=(16, 1), tracking=True, aggregator="sum",
                              help="Ixtiyoriy: stalba sarfi Liteyka kunlik qoldig'i orqali yuritiladi. Kiritilsa, "
                                   "Press sexidan yechiladi va chiqish % hisoblanadi.")
    billet_available = fields.Float("Pressda bor", compute="_compute_billet_available", digits=(16, 1))
    billet_days_left = fields.Float(related="billet_product_id.product_tmpl_id.craf_press_days_left",
                                    string="Quyma necha kunga yetadi")
    line_ids = fields.One2many("craf.extrusion.shift.line", "shift_id", string="Chiqish", copy=True)

    rest_product_id = fields.Many2one(
        "product.product", string="Press qoldig'i (mahsulot)", compute="_compute_rest_product_id", store=True,
        readonly=False, help="Quyma kartochkasidagi «Питак (shu quymadan)»: o'z stalbamiz → вторичка, RusAl → русал")
    rest_qty = fields.Float("Press qoldig'i (питак), kg", digits=(16, 1), aggregator="sum")
    scrap_product_id = fields.Many2one(
        "product.product", string="Brak (mahsulot)", default=lambda self: self._craf_product("PF-07"))
    scrap_qty = fields.Float("Brak profil, kg", digits=(16, 1), aggregator="sum")

    output_pcs = fields.Integer("Chiqdi, dona", compute="_compute_kpi", store=True, aggregator="sum")
    output_kg = fields.Float("Chiqdi, kg", compute="_compute_kpi", store=True, digits=(16, 1), aggregator="sum")
    output_m = fields.Float("Chiqdi, metr", compute="_compute_kpi", store=True, digits=(16, 1), aggregator="sum")
    yield_pct = fields.Float("Chiqish, %", compute="_compute_kpi", store=True, digits=(16, 1), aggregator="avg")
    loss_qty = fields.Float("Hisobga olinmagan farq, kg", compute="_compute_kpi", store=True, digits=(16, 1),
                            aggregator="sum")
    productivity = fields.Float("Unumdorlik, kg/soat", compute="_compute_kpi", store=True, digits=(16, 1),
                                aggregator="avg")

    norm_yield_pct = fields.Float("Chiqish normasi, %", compute="_compute_norm", store=True, digits=(16, 1),
                                  aggregator=None, help="Matritsa normasi; smena tasdiqlanganda shu qiymat qotadi.")
    norm_productivity = fields.Float("Unumdorlik normasi, kg/soat", compute="_compute_norm", store=True,
                                     digits=(16, 1), aggregator=None)
    yield_diff = fields.Float("Normadan farq, %", compute="_compute_norm_status", store=True, digits=(16, 1),
                              aggregator=None, help="Chiqish % − norma (foiz punktlarida)")
    norm_status = fields.Selection(NORM_STATUS, string="Norma", compute="_compute_norm_status", store=True,
                                   index=True)
    norm_warning = fields.Char("Normadan chetlanish", compute="_compute_norm_status", store=True)

    @api.depends("section_id")
    def _compute_norm(self):
        # faqat matritsa tanlanganda olinadi (matritsa normasi keyin o'zgarsa, eski smenalar o'zgarmaydi)
        for shift in self:
            shift.norm_yield_pct = shift.section_id.craf_norm_yield_pct
            shift.norm_productivity = shift.section_id.craf_norm_productivity

    @api.depends("yield_pct", "productivity", "norm_yield_pct", "norm_productivity", "output_kg", "billet_qty",
                 "duration")
    def _compute_norm_status(self):
        tol = self.env["craf.bolim"]._get("press").norm_tolerance or 0.0
        for shift in self:
            has_yield = shift.billet_qty > EPS and shift.output_kg > EPS
            shift.yield_diff = shift.yield_pct - shift.norm_yield_pct if shift.norm_yield_pct and has_yield else 0.0
            issues = shift._craf_norm_issues(tol)
            has_norm = (shift.norm_yield_pct and has_yield) or (shift.norm_productivity and shift.duration > EPS)
            shift.norm_status = ("low" if issues else "ok") if has_norm and shift.output_kg > EPS else False
            shift.norm_warning = "Normadan past: " + "; ".join(issues) if issues else False

    def _craf_norm_issues(self, tol):
        """Yo'l qo'yiladigan chetlanish: chiqish uchun — foiz punkti, unumdorlik uchun — normaning foizi."""
        self.ensure_one()
        issues = []
        if self.output_kg <= EPS:
            return issues
        if self.norm_yield_pct and self.billet_qty > EPS and self.yield_pct < self.norm_yield_pct - tol:
            issues.append("chiqish %s%% (norma %s%%)" % (fmt(self.yield_pct, 1), fmt(self.norm_yield_pct, 1)))
        if (self.norm_productivity and self.duration > EPS
                and self.productivity < self.norm_productivity * (1 - tol / 100.0)):
            issues.append("unumdorlik %s kg/soat (norma %s)" % (
                fmt(self.productivity, 1), fmt(self.norm_productivity, 1)))
        return issues

    @api.depends("billet_product_id")
    def _compute_rest_product_id(self):
        default = self._craf_product("PF-06")
        for shift in self:
            shift.rest_product_id = shift.billet_product_id.product_tmpl_id.craf_butt_product_id or default

    @api.depends("billet_product_id", "location_src_id")
    def _compute_billet_available(self):
        Quant = self.env["stock.quant"]
        for shift in self:
            if shift.billet_product_id and shift.location_src_id:
                shift.billet_available = Quant._get_available_quantity(shift.billet_product_id, shift.location_src_id)
            else:
                shift.billet_available = 0.0

    @api.depends("line_ids.pcs", "line_ids.kg", "line_ids.metres", "billet_qty", "rest_qty", "scrap_qty", "duration")
    def _compute_kpi(self):
        for shift in self:
            kg = sum(shift.line_ids.mapped("kg"))
            shift.output_pcs = sum(shift.line_ids.mapped("pcs"))
            shift.output_kg = kg
            shift.output_m = sum(shift.line_ids.mapped("metres"))
            shift.yield_pct = kg / shift.billet_qty * 100.0 if shift.billet_qty else 0.0
            shift.loss_qty = shift.billet_qty - kg - shift.rest_qty - shift.scrap_qty if shift.billet_qty else 0.0
            shift.productivity = kg / shift.duration if shift.duration else 0.0

    @api.onchange("section_id")
    def _onchange_section_id(self):
        """Matritsa tanlansa, shu kesimning bo'yalmagan profillari qatorlarga qo'shiladi."""
        if not self.section_id or self.line_ids:
            return
        raw = self.env["product.template"]._craf_raw_color()
        products = self.env["product.product"].search([
            ("craf_section_id", "=", self.section_id.id), ("craf_color_id", "=", raw.id)], order="default_code")
        self.line_ids = [(0, 0, {"product_id": p.id, "pcs": 0}) for p in products]

    def _craf_action_done(self):
        self.ensure_one()
        # norma tasdiqlash paytidagi qiymatda qotadi (keyin matritsa normasi o'zgarsa ham)
        self.write({"norm_yield_pct": self.section_id.craf_norm_yield_pct,
                    "norm_productivity": self.section_id.craf_norm_productivity})
        lines = self.line_ids.filtered(lambda l: l.pcs > 0)
        if not lines:
            raise UserError("Chiqqan profil donasini kiriting.")
        if any(not l.kg_per_pc for l in lines):
            raise UserError("Kesimda kg/m yoki mahsulotda uzunlik kiritilmagan — nazariy kg hisoblanmaydi.")
        billet = self.billet_qty > EPS  # quyma ixtiyoriy: yozilmasa stalba Liteyka qoldig'i orqali yuritiladi
        if billet:
            total_out = self.output_kg + self.rest_qty + self.scrap_qty
            if total_out > self.billet_qty + EPS:
                raise UserError("Chiqish + qoldiq + brak (%s kg) quyma sarfidan (%s kg) ko'p bo'lishi mumkin emas." % (
                    fmt(total_out, 1), fmt(self.billet_qty, 1)))
            self._craf_check_available(self.location_src_id, {self.billet_product_id: self.billet_qty})
        byproducts = []
        if self.rest_qty > EPS:
            byproducts.append((self.rest_product_id, self.rest_qty, self.waste_location_id))
        if self.scrap_qty > EPS:
            byproducts.append((self.scrap_product_id, self.scrap_qty, self.waste_location_id))
        if any(not p for p, _q, _l in byproducts):
            raise UserError("Press qoldig'i / brak mahsulotini tanlang.")
        remaining = self.billet_qty
        names = []
        for i, line in enumerate(lines):
            last = i == len(lines) - 1
            share = remaining if last else round(self.billet_qty * line.kg / self.output_kg, 3)
            remaining -= share
            components = [(self.billet_product_id, share)] if billet else []
            mo = self._craf_produce(line.product_id, line.pcs, self.location_src_id, line.location_dest_id,
                                    components, byproducts if i == 0 else None)
            names.append(mo.name)
        self._craf_post_summary([
            Markup("<b>Press smenasi tasdiqlandi</b> — %s") % ", ".join(names),
            ("Quyma: %s kg%s" % (fmt(self.billet_qty, 1),
                                 (" (partiya: %s)" % ", ".join(self.melt_ids.mapped("name"))) if self.melt_ids else ""))
            if billet else "Quyma: yozilmagan (stalba Liteyka qoldig'i orqali)",
            "Profil: %s dona = %s kg%s" % (fmt(self.output_pcs), fmt(self.output_kg, 1),
                                           (", chiqish %s%%" % fmt(self.yield_pct, 1)) if billet else ""),
            "Питак %s kg, brak %s kg → %s" % (fmt(self.rest_qty, 1), fmt(self.scrap_qty, 1),
                                               self.waste_location_id.name),
        ])
        self._craf_norm_notify("press", "craf_extrusion.mail_activity_press_norm",
                               "Press: %s — normadan past" % (self.section_id.name or self.name))

    # ------------------------------------------------------------------ quyma prognozi
    @api.model
    def _craf_billet_products(self):
        return self.env["product.product"].search([("default_code", "in", BILLET_CODES)])

    @api.model
    def _craf_billet_forecast(self, products=None):
        """Quyma: qoldiq va oxirgi N kun (Press sozlamasi) sarfi bo'yicha necha kunga yetishi.

        Sarf — ichki joydan ishlab chiqarishga ketgan quyma (tasdiqlangan press smenalari va Excel'dan
        kiritilgan kunlik sarf). Qoldiq — zavod bo'yicha (barcha ichki joylar), alohida Press sexida ham."""
        if products is None:
            products = self._craf_billet_products()
        today = fields.Date.context_today(self)
        period, warn, used = self._craf_consumption(products, "press", self._craf_billet_products())
        press_loc = self._craf_loc(self._craf_default_src)
        on_hand, in_press = {}, {}
        for product, location, qty in self.env["stock.quant"].sudo()._read_group(
                [("product_id", "in", products.ids), ("location_id.usage", "=", "internal")],
                ["product_id", "location_id"], ["quantity:sum"]):
            on_hand[product.id] = on_hand.get(product.id, 0.0) + qty
            if location == press_loc:
                in_press[product.id] = qty
        rows = {}
        for product in products:
            qty = on_hand.get(product.id, 0.0)
            spent = used.get(product.id, 0.0)
            avg = spent / period
            min_qty = product.craf_min_qty or 0.0
            status, days_left = self._craf_forecast_status(qty, avg, min_qty, warn)
            rows[product.id] = {
                "product": product, "qty": qty, "in_press": in_press.get(product.id, 0.0), "min_qty": min_qty,
                "used": spent, "avg": avg, "period": period, "days_left": days_left,
                "end_date": today + timedelta(days=int(days_left)) if days_left is not None else False,
                "status": status, "uom": "kg",
            }
        return rows

    @api.model
    def _cron_billet_min_qty(self):
        self._craf_min_qty_sync(list(self._craf_billet_forecast().values()), "press",
                                "craf_extrusion.mail_activity_press_billet", "Press")

    def _craf_pack_items(self):
        return [(l.product_id, l.pcs, l.location_dest_id) for l in self.line_ids
                if l.pcs > 0 and l.product_id.sale_ok]


class CrafExtrusionShiftLine(models.Model):
    _name = "craf.extrusion.shift.line"
    _description = "Press smenasi chiqishi"
    _order = "id"

    shift_id = fields.Many2one("craf.extrusion.shift", required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one("product.product", string="Profil (bo'yalmagan)", required=True)
    length_m = fields.Float(related="product_id.craf_length_m", string="Uzunlik, m")
    kg_per_pc = fields.Float(related="product_id.craf_kg_per_pc", string="1 dona, kg")
    pcs = fields.Integer("Dona")
    packs_text = fields.Char("Pachka", compute="_compute_packs_text")
    metres = fields.Float("Metr", compute="_compute_totals", store=True, digits=(16, 1))
    kg = fields.Float("Nazariy kg", compute="_compute_totals", store=True, digits=(16, 1))
    location_dest_id = fields.Many2one(
        "stock.location", string="Qayerga", compute="_compute_location_dest_id", store=True, readonly=False,
        domain=[("usage", "=", "internal")])
    state = fields.Selection(related="shift_id.state")

    @api.depends("pcs", "product_id.craf_kg_per_pc", "product_id.craf_length_m", "product_id.craf_pcs_per_pack")
    def _compute_totals(self):
        for line in self:
            line.metres = line.pcs * (line.product_id.craf_length_m or 0.0)
            line.kg = line.pcs * (line.product_id.craf_kg_per_pc or 0.0)

    @api.depends("pcs", "product_id.craf_pcs_per_pack")
    def _compute_packs_text(self):
        Tmpl = self.env["product.template"]
        for line in self:
            line.packs_text = Tmpl._craf_packs_text(line.pcs, line.product_id.craf_pcs_per_pack) if line.pcs else False

    @api.depends("product_id")
    def _compute_location_dest_id(self):
        Mixin = self.env["craf.production.mixin"]
        paint = Mixin._craf_loc("Bo'yash sexi")
        pack = Mixin._craf_loc("Qadoqlash")
        for line in self:
            if not line.product_id:
                line.location_dest_id = False
                continue
            # Sotiladigan bo'yalmagan profil (Прижим, Соединитель…) — to'g'ri qadoqlashga, qolgani bo'yashga
            line.location_dest_id = pack if line.product_id.sale_ok else paint
