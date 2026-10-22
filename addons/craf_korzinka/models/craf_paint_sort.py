"""Bo'yash va qadoqlash: korzinkalardan yaroqsiz profillarni ajratish (bo'yashdan oldin).

Bo'yash bo'limiga kelgan korzinkalar (bir yoki bir necha kun ichida) ko'rib chiqiladi:
- brak — profil butunlay yaroqsiz: dona → kg, Liteykaga (brak profil + briket otxod);
- 6 m → 5 m kesildi — zararlangan uchlari olib tashlangan: mahsulot 5 m variantiga almashadi,
  kesilgan uchlarning kg i Liteykaga.
Korzinka tarkibi shunga ko'ra kamayadi; bo'yash smenasi korzinkadan to'ldirilganda qolgani tushadi.
"""
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt

SORT_KINDS = [("brak", "Brak"), ("cut", "6 m → 5 m kesildi")]


class CrafPaintSort(models.Model):
    _name = "craf.paint.sort"
    _description = "Brak ajratish (bo'yashdan oldin)"
    _inherit = ["craf.production.mixin"]
    _order = "date desc, id desc"

    _craf_sequence_code = "craf.paint.sort"
    _craf_stage = "paint"
    _craf_default_src = "Bo'yash sexi"
    _craf_default_waste = "Литейка"

    line_ids = fields.One2many("craf.paint.sort.line", "sort_id", string="Ajratilganlar", copy=True)
    scrap_product_id = fields.Many2one(
        "product.product", string="Brak (mahsulot)", required=True,
        default=lambda self: self._craf_product("PF-07"))
    brak_pcs = fields.Integer("Brak, dona", compute="_compute_totals", store=True, aggregator="sum")
    cut_pcs = fields.Integer("Kesildi, dona", compute="_compute_totals", store=True, aggregator="sum")
    kg_total = fields.Float("Liteykaga, kg", compute="_compute_totals", store=True, digits=(16, 1), aggregator="sum")
    basket_count = fields.Integer("Korzinkalar", compute="_compute_totals", store=True)

    @api.depends("line_ids.qty", "line_ids.kind", "line_ids.kg", "line_ids.load_id")
    def _compute_totals(self):
        for rec in self:
            rec.brak_pcs = sum(rec.line_ids.filtered(lambda l: l.kind == "brak").mapped("qty"))
            rec.cut_pcs = sum(rec.line_ids.filtered(lambda l: l.kind == "cut").mapped("qty"))
            rec.kg_total = sum(rec.line_ids.mapped("kg"))
            rec.basket_count = len(rec.line_ids.load_id)

    def _craf_action_done(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.qty > 0)
        if not lines:
            raise UserError("Ajratilgan profillarni kiriting (korzinka, profil, dona).")
        for line in lines:
            line._check_available_in_load()
            if line.kind == "cut" and not line.target_product_id:
                raise UserError("%s: 5 m varianti katalogda yo'q." % line.product_id.display_name)
            if line.kg <= EPS:
                raise UserError("%s: brak kg 0 — profil og'irligini tekshiring." % line.product_id.display_name)
        needs = {}
        for line in lines:
            loc = line.load_id.location_id
            needs.setdefault(loc, {})
            needs[loc][line.product_id] = needs[loc].get(line.product_id, 0) + line.qty
        for loc, need in needs.items():
            self._craf_check_available(loc, need)
        names = []
        for line in lines:
            loc = line.load_id.location_id
            if line.kind == "brak":
                mo = self._craf_produce(self.scrap_product_id, line.kg, loc, self.waste_location_id,
                                        [(line.product_id, line.qty)])
            else:
                mo = self._craf_produce(line.target_product_id, line.qty, loc, loc, [(line.product_id, line.qty)],
                                        [(self.scrap_product_id, line.kg, self.waste_location_id)])
            line.production_id = mo
            names.append(mo.name)
        self._craf_post_summary([
            Markup("<b>Brak ajratish tasdiqlandi</b> — %s") % ", ".join(names),
            "Korzinkalar: %s; brak %s dona, 6 → 5 m kesildi %s dona" % (
                ", ".join(lines.load_id.basket_id.mapped("name")), fmt(self.brak_pcs), fmt(self.cut_pcs)),
            "%s: %s kg → %s" % (self.scrap_product_id.name, fmt(self.kg_total, 1), self.waste_location_id.name),
        ])


class CrafPaintSortLine(models.Model):
    _name = "craf.paint.sort.line"
    _description = "Brak ajratish qatori"
    _order = "id"

    sort_id = fields.Many2one("craf.paint.sort", required=True, ondelete="cascade", index=True)
    state = fields.Selection(related="sort_id.state", store=True)
    load_id = fields.Many2one(
        "craf.basket.load", "Korzinka", required=True, index=True,
        domain="[('state', 'in', ('press', 'kimyo')), ('shift_state', '=', 'done')]")
    allowed_product_ids = fields.Many2many("product.product", compute="_compute_allowed_product_ids")
    product_id = fields.Many2one("product.product", "Profil", required=True,
                                 domain="[('id', 'in', allowed_product_ids)]")
    length_m = fields.Float(related="product_id.craf_length_m", string="Uzunlik, m")
    kind = fields.Selection(SORT_KINDS, "Nima bo'ldi", required=True, default="brak")
    qty = fields.Integer("Dona")
    target_product_id = fields.Many2one("product.product", "Kesilgandan keyin", compute="_compute_target", store=True)
    kg = fields.Float("Liteykaga, kg", compute="_compute_kg", store=True, readonly=False, digits=(16, 1),
                      help="Brak: dona × 1 dona og'irligi; kesildi: dona × (6 m − 5 m og'irligi). Tortilgan bo'lsa, "
                           "tortilganini yozing.")
    note = fields.Char("Sababi")
    production_id = fields.Many2one("mrp.production", "Buyurtma", readonly=True, copy=False)

    @api.depends("load_id")
    def _compute_allowed_product_ids(self):
        for line in self:
            line.allowed_product_ids = [(6, 0, [p.id for p in line.load_id._product_quantities()])]

    @api.onchange("load_id")
    def _onchange_load_id(self):
        allowed = list(self.load_id._product_quantities())
        if len(allowed) == 1 or (allowed and self.product_id not in allowed):
            self.product_id = allowed[0]

    @api.depends("product_id", "kind")
    def _compute_target(self):
        Tmpl = self.env["product.template"]
        for line in self:
            p = line.product_id
            line.target_product_id = (Tmpl._craf_semi_for(p.craf_section_id, 5.0, create=False)
                                      if line.kind == "cut" and p and abs(p.craf_length_m - 6.0) < EPS else False)

    @api.depends("qty", "kind", "product_id.craf_kg_per_pc", "target_product_id.craf_kg_per_pc")
    def _compute_kg(self):
        for line in self:
            per = line.product_id.craf_kg_per_pc or 0.0
            if line.kind == "cut":
                per -= line.target_product_id.craf_kg_per_pc or 0.0
            line.kg = round(line.qty * per, 1)

    @api.constrains("qty", "kind", "product_id")
    def _check_qty(self):
        for line in self:
            if line.qty < 0:
                raise ValidationError("Dona manfiy bo'lishi mumkin emas.")
            if line.kind == "cut" and line.product_id and abs(line.product_id.craf_length_m - 6.0) > EPS:
                raise ValidationError("«6 m → 5 m kesildi» faqat 6 metrlik profil uchun.")

    def _check_available_in_load(self):
        """Korzinkada shu profildan yetarli dona bormi (shu hujjatdagi boshqa qatorlar bilan birga)."""
        for line in self:
            have = line.load_id._product_quantities().get(line.product_id, 0)
            taken = sum(line.sort_id.line_ids.filtered(
                lambda l, line=line: l.load_id == line.load_id and l.product_id == line.product_id).mapped("qty"))
            if taken > have:
                raise UserError("%s korzinkada %s dan %s dona bor, ajratildi %s." % (
                    line.load_id.basket_id.name, line.product_id.display_name, have, taken))
