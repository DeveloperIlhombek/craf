from datetime import timedelta

from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, NORM_STATUS, fmt

# Kimyo normasi, kg / m² (namuna; haqiqiy norma bilan almashtiriladi)
CHEM_NORMS = [("XA-03", 0.012), ("XA-04", 0.008), ("XA-05", 0.006)]
# Bo'yash va qadoqlash materiallari (kukun bo'yoqlar rang kartochkasidan qo'shiladi): rangsiz kukunlar
# (9005, Uzpon), kimyo, kaustik soda, plyonka, lenta
MATERIAL_CODES = ("XA-01", "XA-03", "XA-04", "XA-05", "XA-10", "XA-11", "XA-12", "QM-01", "QM-02")
DEFAULT_POWDER_NORM = 120.0


class CrafPaintBatch(models.Model):
    _name = "craf.paint.batch"
    _description = "Bo'yash smenasi"
    _inherit = ["craf.production.mixin", "mail.activity.mixin"]
    _order = "date desc, id desc"
    _craf_weighted_avg = {
        "defect_pct": ("pcs_defect", "pcs_in", 100.0),
        "powder_diff_pct": ("powder_qty", "powder_norm_qty", 100.0, -100.0),
        "powder_g_m2": ("powder_qty", "area_total", 1000.0),
    }

    _craf_sequence_code = "craf.paint.batch"
    _craf_stage = "paint"
    _craf_default_src = "Bo'yash sexi"
    _craf_default_dest = "Qadoqlash"
    _craf_default_waste = "Литейка"  # brak profil Liteykada qayta eritiladi

    color_id = fields.Many2one("craf.color", string="Rang", required=True, domain=[("is_painted", "=", True)],
                               tracking=True)
    powder_product_id = fields.Many2one(
        "product.product", string="Kukun bo'yoq", compute="_compute_powder_product_id", store=True, readonly=False)
    powder_norm = fields.Float("Kukun normasi, g/m²", compute="_compute_powder_norm", store=True, readonly=False,
                               help="Rang kartochkasidagi normadan olinadi (yo'q bo'lsa 120 g/m²).")
    powder_norm_qty = fields.Float("Kukun normada, kg", compute="_compute_kpi", store=True, digits=(16, 2))
    powder_qty = fields.Float("Kukun sarfi, kg", digits=(16, 2), tracking=True, aggregator="sum")
    powder_diff_pct = fields.Float("Kukun farqi, %", compute="_compute_kpi", store=True, digits=(16, 1),
                                   aggregator="avg")
    powder_g_m2 = fields.Float("Kukun fakt, g/m²", compute="_compute_powder_g_m2", store=True, digits=(16, 1),
                               aggregator="avg")
    location_dest_id = fields.Many2one(
        "stock.location", string="Bo'yalgan qayerga", required=True, domain=[("usage", "=", "internal")],
        default=lambda self: self._craf_loc(self._craf_default_dest))
    line_ids = fields.One2many("craf.paint.batch.line", "batch_id", string="Profillar", copy=True)
    chem_line_ids = fields.One2many("craf.paint.chem.line", "batch_id", string="Kimyo", copy=True)
    scrap_product_id = fields.Many2one(
        "product.product", string="Brak (mahsulot)", default=lambda self: self._craf_product("PF-07"))
    # qadoqlash materiallari
    film_product_id = fields.Many2one(
        "product.product", string="Plyonka (mahsulot)", default=lambda self: self._craf_product("QM-01"))
    film_qty = fields.Float("Plyonka sarfi", digits=(16, 2), aggregator="sum")
    tape_product_id = fields.Many2one(
        "product.product", string="Lenta (mahsulot)", default=lambda self: self._craf_product("QM-02"))
    tape_qty = fields.Float("Lenta sarfi", digits=(16, 1), aggregator="sum")

    pcs_in = fields.Integer("Kirdi, dona", compute="_compute_kpi", store=True, aggregator="sum")
    pcs_defect = fields.Integer("Brak, dona", compute="_compute_kpi", store=True, aggregator="sum")
    pcs_ok = fields.Integer("Bo'yaldi, dona", compute="_compute_kpi", store=True, aggregator="sum")
    kg_ok = fields.Float("Bo'yaldi, kg", compute="_compute_kpi", store=True, digits=(16, 1), aggregator="sum")
    area_total = fields.Float("Maydon, m²", compute="_compute_kpi", store=True, digits=(16, 1), aggregator="sum")
    defect_pct = fields.Float("Brak, %", compute="_compute_kpi", store=True, digits=(16, 2), aggregator="avg")

    norm_status = fields.Selection(NORM_STATUS, string="Norma", compute="_compute_norm_status", store=True,
                                   index=True)
    norm_warning = fields.Char("Normadan chetlanish", compute="_compute_norm_status", store=True)
    powder_days_left = fields.Float(related="powder_product_id.product_tmpl_id.craf_boyash_days_left",
                                    string="Kukun necha kunga yetadi")

    @api.depends("color_id")
    def _compute_powder_norm(self):
        for batch in self:
            batch.powder_norm = batch.color_id.craf_powder_norm or DEFAULT_POWDER_NORM

    @api.depends("powder_qty", "area_total")
    def _compute_powder_g_m2(self):
        for batch in self:
            has_data = batch.area_total > EPS and batch.powder_qty > EPS
            batch.powder_g_m2 = batch.powder_qty * 1000.0 / batch.area_total if has_data else 0.0

    @api.depends("defect_pct", "powder_diff_pct", "powder_g_m2", "powder_norm", "pcs_in", "powder_qty")
    def _compute_norm_status(self):
        bolim = self.env["craf.bolim"]._get("boyash")
        for batch in self:
            issues = batch._craf_norm_issues(bolim)
            batch.norm_status = ("low" if issues else "ok") if batch.pcs_in else False
            batch.norm_warning = "Normadan tashqari: " + "; ".join(issues) if issues else False

    def _craf_norm_issues(self, bolim):
        """Brak — Bo'yash sozlamasidagi chegaradan ko'p; kukun — normadan chegara foizidan ortiq sarf."""
        self.ensure_one()
        issues = []
        if not self.pcs_in:
            return issues
        if bolim.defect_max_pct and self.defect_pct > bolim.defect_max_pct + EPS:
            issues.append("brak %s%% (chegara %s%%)" % (fmt(self.defect_pct, 2), fmt(bolim.defect_max_pct, 1)))
        if (bolim.powder_tolerance and self.powder_qty > EPS and self.powder_norm_qty > EPS
                and self.powder_diff_pct > bolim.powder_tolerance + EPS):
            issues.append("kukun normadan %s%% ko'p (%s g/m², norma %s)" % (
                fmt(self.powder_diff_pct, 1), fmt(self.powder_g_m2, 0), fmt(self.powder_norm, 0)))
        return issues

    @api.depends("color_id")
    def _compute_powder_product_id(self):
        for batch in self:
            batch.powder_product_id = batch.color_id.paint_tmpl_id.product_variant_id

    @api.depends("line_ids.pcs_in", "line_ids.pcs_defect", "line_ids.area_m2", "line_ids.kg_ok",
                 "powder_norm", "powder_qty")
    def _compute_kpi(self):
        for batch in self:
            pcs_in = sum(batch.line_ids.mapped("pcs_in"))
            defect = sum(batch.line_ids.mapped("pcs_defect"))
            area = sum(batch.line_ids.mapped("area_m2"))
            norm_qty = area * batch.powder_norm / 1000.0
            batch.pcs_in = pcs_in
            batch.pcs_defect = defect
            batch.pcs_ok = pcs_in - defect
            batch.kg_ok = sum(batch.line_ids.mapped("kg_ok"))
            batch.area_total = area
            batch.defect_pct = defect / pcs_in * 100.0 if pcs_in else 0.0
            batch.powder_norm_qty = norm_qty
            batch.powder_diff_pct = (batch.powder_qty - norm_qty) / norm_qty * 100.0 if norm_qty and batch.powder_qty else 0.0

    def action_fill_norms(self):
        """Kukun va kimyo sarfini normadan to'ldiradi (keyin haqiqiysiga o'zgartirish mumkin)."""
        for batch in self:
            if batch.state != "draft":
                continue
            chem = []
            for code, per_m2 in CHEM_NORMS:
                product = batch._craf_product(code)
                if product:
                    qty = round(batch.area_total * per_m2, 2)
                    chem.append(Command.create({"product_id": product.id, "qty_norm": qty, "qty": qty}))
            batch.write({
                "powder_qty": round(batch.powder_norm_qty, 2),
                "chem_line_ids": [Command.clear()] + chem,
            })
        return True

    def _craf_action_done(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.pcs_in > 0)
        if not lines:
            raise UserError("Bo'yashga kirgan profillarni kiriting.")
        for line in lines:
            if not line.product_id:
                raise UserError("%s uchun %s rangdagi tayyor mahsulot katalogda yo'q." % (
                    line.semi_product_id.display_name, self.color_id.name))
            if line.pcs_defect > line.pcs_in:
                raise UserError("%s: brak kirgan donadan ko'p." % line.semi_product_id.display_name)
            if line.pcs_ok <= 0:
                raise UserError("%s: bo'yalgan dona 0 — qatorni o'chiring yoki brakni tekshiring." %
                                line.semi_product_id.display_name)
        if self.powder_qty > EPS and not self.powder_product_id:
            raise UserError("Kukun bo'yoq mahsulotini tanlang (rang kartochkasida ham belgilash mumkin).")
        needs = {}
        for line in lines:
            needs[line.semi_product_id] = needs.get(line.semi_product_id, 0.0) + line.pcs_in
        if self.powder_qty > EPS:
            needs[self.powder_product_id] = needs.get(self.powder_product_id, 0.0) + self.powder_qty
        for chem in self.chem_line_ids.filtered(lambda c: c.qty > EPS):
            needs[chem.product_id] = needs.get(chem.product_id, 0.0) + chem.qty
        for product, qty in self._craf_pack_materials():
            needs[product] = needs.get(product, 0.0) + qty
        self._craf_check_available(self.location_src_id, needs)

        area_total = sum(lines.mapped("area_m2"))
        pcs_total = sum(lines.mapped("pcs_in"))
        consumables = [(self.powder_product_id, self.powder_qty)] if self.powder_qty > EPS else []
        consumables += [(c.product_id, c.qty) for c in self.chem_line_ids if c.qty > EPS]
        consumables += self._craf_pack_materials()
        left = {p: q for p, q in consumables}
        names = []
        for i, line in enumerate(lines):
            last = i == len(lines) - 1
            weight = (line.area_m2 / area_total) if area_total else (line.pcs_in / pcs_total)
            components = [(line.semi_product_id, line.pcs_in)]
            for product, qty in consumables:
                share = left[product] if last else round(qty * weight, 3)
                left[product] -= share
                components.append((product, share))
            byproducts = []
            if line.pcs_defect and self.scrap_product_id:
                byproducts.append((self.scrap_product_id, line.pcs_defect * (line.kg_per_pc or 0.0),
                                   self.waste_location_id))
            mo = self._craf_produce(line.product_id, line.pcs_ok, self.location_src_id, self.location_dest_id,
                                    components, byproducts)
            names.append(mo.name)
        self._craf_post_summary([
            Markup("<b>Bo'yash tasdiqlandi</b> — %s") % ", ".join(names),
            "Rang: %s; kirdi %s dona, bo'yaldi %s dona (%s kg), brak %s dona (%s%%)" % (
                self.color_id.name, fmt(self.pcs_in), fmt(self.pcs_ok), fmt(self.kg_ok, 1),
                fmt(self.pcs_defect), fmt(self.defect_pct, 2)),
            "Maydon %s m²; kukun %s kg (normada %s kg)" % (
                fmt(self.area_total, 1), fmt(self.powder_qty, 2), fmt(self.powder_norm_qty, 2)),
        ])
        self._craf_norm_notify("boyash", "craf_paint.mail_activity_boyash_norm",
                               "Bo'yash: %s — normadan tashqari" % self.color_id.name)

    # ------------------------------------------------------------------ material prognozi
    @api.model
    def _craf_material_products(self):
        """Kukun bo'yoqlar (faol ranglar kartochkasidagi), kimyo, plyonka va lenta."""
        colors = self.env["craf.color"].search([("is_painted", "=", True), ("paint_tmpl_id", "!=", False)])
        return colors.paint_tmpl_id.product_variant_ids | self.env["product.product"].search(
            [("default_code", "in", MATERIAL_CODES)])

    @api.model
    def _craf_material_forecast(self, products=None):
        """Material: qoldiq va oxirgi N kun (Bo'yash sozlamasi) sarfi bo'yicha necha kunga yetishi.

        Sarf — ichki joydan ishlab chiqarishga ketgan bajarilgan ombor harakatlari (bo'yash, kimyoviy ishlov,
        qadoqlash). Tarix N kundan qisqa bo'lsa, N — birinchi sarf kunidan bugungacha."""
        if products is None:
            products = self._craf_material_products()
        today = fields.Date.context_today(self)
        period, warn, used = self._craf_consumption(products, "boyash", self._craf_material_products())
        sex_locs = self.env["stock.location"]
        for name in (self._craf_default_src, self._craf_default_dest, "Kimyoviy ishlov"):
            sex_locs |= self._craf_loc(name)
        on_hand, in_sex = {}, {}
        for product, location, qty in self.env["stock.quant"].sudo()._read_group(
                [("product_id", "in", products.ids), ("location_id.usage", "=", "internal")],
                ["product_id", "location_id"], ["quantity:sum"]):
            on_hand[product.id] = on_hand.get(product.id, 0.0) + qty
            if location in sex_locs:
                in_sex[product.id] = in_sex.get(product.id, 0.0) + qty
        rows = {}
        for product in products:
            qty = on_hand.get(product.id, 0.0)
            spent = used.get(product.id, 0.0)
            avg = spent / period
            min_qty = product.craf_min_qty or 0.0
            status, days_left = self._craf_forecast_status(qty, avg, min_qty, warn)
            rows[product.id] = {
                "product": product, "qty": qty, "in_sex": in_sex.get(product.id, 0.0), "min_qty": min_qty,
                "used": spent, "avg": avg, "period": period, "days_left": days_left,
                "end_date": today + timedelta(days=int(days_left)) if days_left is not None else False,
                "status": status, "uom": product.uom_id.name,
            }
        return rows

    @api.model
    def _cron_material_min_qty(self):
        self._craf_min_qty_sync(list(self._craf_material_forecast().values()), "boyash",
                                "craf_paint.mail_activity_boyash_material", "Bo'yash")

    def _craf_pack_materials(self):
        """[(mahsulot, miqdor)] — qadoqlash materiallari sarfi (plyonka, lenta)."""
        self.ensure_one()
        res = []
        for product, qty, label in ((self.film_product_id, self.film_qty, "Plyonka"),
                                    (self.tape_product_id, self.tape_qty, "Lenta")):
            if qty > EPS:
                if not product:
                    raise UserError("%s mahsuloti tanlanmagan." % label)
                res.append((product, qty))
        return res

    def _craf_pack_items(self):
        return [(l.product_id, l.pcs_ok, self.location_dest_id) for l in self.line_ids if l.pcs_ok > 0]


class CrafPaintBatchLine(models.Model):
    _name = "craf.paint.batch.line"
    _description = "Bo'yash qatori"
    _order = "id"

    batch_id = fields.Many2one("craf.paint.batch", required=True, ondelete="cascade", index=True)
    semi_product_id = fields.Many2one(
        "product.product", string="Bo'yalmagan profil", required=True,
        domain=[("craf_color_id.is_painted", "=", False), ("craf_section_id", "!=", False)])
    product_id = fields.Many2one(
        "product.product", string="Bo'yalgan profil", compute="_compute_product_id", store=True, readonly=False,
        domain=[("craf_color_id.is_painted", "=", True)])
    available_qty = fields.Float("Bor, dona", compute="_compute_available_qty", digits=(16, 0))
    pcs_in = fields.Integer("Kirdi, dona")
    pcs_defect = fields.Integer("Brak, dona")
    pcs_ok = fields.Integer("Bo'yaldi, dona", compute="_compute_values", store=True)
    kg_per_pc = fields.Float(related="semi_product_id.craf_kg_per_pc", string="1 dona, kg")
    kg_ok = fields.Float("Bo'yaldi, kg", compute="_compute_values", store=True, digits=(16, 1))
    area_m2 = fields.Float("Maydon, m²", compute="_compute_values", store=True, digits=(16, 2))
    state = fields.Selection(related="batch_id.state")

    @api.depends("semi_product_id", "batch_id.color_id")
    def _compute_product_id(self):
        Tmpl = self.env["product.template"]
        for line in self:
            semi = line.semi_product_id
            color = line.batch_id.color_id
            if not semi or not color:
                line.product_id = False
                continue
            tmpl = Tmpl.search([
                ("craf_section_id", "=", semi.craf_section_id.id),
                ("craf_length_m", "=", semi.craf_length_m),
                ("craf_color_id", "=", color.id),
            ], limit=1)
            line.product_id = tmpl.product_variant_id

    @api.depends("semi_product_id", "batch_id.location_src_id")
    def _compute_available_qty(self):
        Quant = self.env["stock.quant"]
        for line in self:
            loc = line.batch_id.location_src_id
            line.available_qty = Quant._get_available_quantity(line.semi_product_id, loc) \
                if line.semi_product_id and loc else 0.0

    @api.depends("pcs_in", "pcs_defect", "semi_product_id.craf_kg_per_pc", "semi_product_id.craf_length_m",
                 "semi_product_id.craf_section_id.perimeter_m")
    def _compute_values(self):
        for line in self:
            semi = line.semi_product_id
            ok = line.pcs_in - line.pcs_defect
            line.pcs_ok = ok
            line.kg_ok = ok * (semi.craf_kg_per_pc or 0.0)
            line.area_m2 = line.pcs_in * (semi.craf_length_m or 0.0) * (semi.craf_section_id.perimeter_m or 0.0)


class CrafPaintChemLine(models.Model):
    _name = "craf.paint.chem.line"
    _description = "Bo'yash kimyo sarfi"
    _order = "id"

    batch_id = fields.Many2one("craf.paint.batch", required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one("product.product", string="Kimyo", required=True,
                                 domain=[("is_storable", "=", True), ("craf_section_id", "=", False)])
    qty_norm = fields.Float("Normada, kg", digits=(16, 2))
    qty = fields.Float("Sarf, kg", digits=(16, 2))
    uom_id = fields.Many2one(related="product_id.uom_id", string="Birlik")
