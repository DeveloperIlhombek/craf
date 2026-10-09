from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt

# Kimyo normasi, kg / m² (namuna; haqiqiy norma bilan almashtiriladi)
CHEM_NORMS = [("XA-03", 0.012), ("XA-04", 0.008), ("XA-05", 0.006)]


class CrafPaintBatch(models.Model):
    _name = "craf.paint.batch"
    _description = "Bo'yash smenasi"
    _inherit = ["craf.production.mixin"]
    _order = "date desc, id desc"

    _craf_sequence_code = "craf.paint.batch"
    _craf_stage = "paint"
    _craf_default_src = "Bo'yash sexi"
    _craf_default_dest = "Qadoqlash"

    color_id = fields.Many2one("craf.color", string="Rang", required=True, domain=[("is_painted", "=", True)],
                               tracking=True)
    powder_product_id = fields.Many2one(
        "product.product", string="Kukun bo'yoq", compute="_compute_powder_product_id", store=True, readonly=False)
    powder_norm = fields.Float("Kukun normasi, g/m²", default=120.0)
    powder_norm_qty = fields.Float("Kukun normada, kg", compute="_compute_kpi", store=True, digits=(16, 2))
    powder_qty = fields.Float("Kukun sarfi, kg", digits=(16, 2), tracking=True, aggregator="sum")
    powder_diff_pct = fields.Float("Kukun farqi, %", compute="_compute_kpi", store=True, digits=(16, 1),
                                   aggregator="avg")
    location_dest_id = fields.Many2one(
        "stock.location", string="Bo'yalgan qayerga", required=True, domain=[("usage", "=", "internal")],
        default=lambda self: self._craf_loc(self._craf_default_dest))
    line_ids = fields.One2many("craf.paint.batch.line", "batch_id", string="Profillar", copy=True)
    chem_line_ids = fields.One2many("craf.paint.chem.line", "batch_id", string="Kimyo", copy=True)
    scrap_product_id = fields.Many2one(
        "product.product", string="Brak (mahsulot)", default=lambda self: self._craf_product("PF-07"))

    pcs_in = fields.Integer("Kirdi, dona", compute="_compute_kpi", store=True, aggregator="sum")
    pcs_defect = fields.Integer("Brak, dona", compute="_compute_kpi", store=True, aggregator="sum")
    pcs_ok = fields.Integer("Bo'yaldi, dona", compute="_compute_kpi", store=True, aggregator="sum")
    kg_ok = fields.Float("Bo'yaldi, kg", compute="_compute_kpi", store=True, digits=(16, 1), aggregator="sum")
    area_total = fields.Float("Maydon, m²", compute="_compute_kpi", store=True, digits=(16, 1), aggregator="sum")
    defect_pct = fields.Float("Brak, %", compute="_compute_kpi", store=True, digits=(16, 2), aggregator="avg")

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
        self._craf_check_available(self.location_src_id, needs)

        area_total = sum(lines.mapped("area_m2"))
        pcs_total = sum(lines.mapped("pcs_in"))
        consumables = [(self.powder_product_id, self.powder_qty)] if self.powder_qty > EPS else []
        consumables += [(c.product_id, c.qty) for c in self.chem_line_ids if c.qty > EPS]
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
