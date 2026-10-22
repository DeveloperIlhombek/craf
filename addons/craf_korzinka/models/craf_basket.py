from odoo import api, fields, models
from odoo.exceptions import ValidationError

LOAD_STATES = [
    ("press", "Kimyoga kutmoqda"),
    ("kimyo", "Bo'yashga tayyor"),
    ("boyash", "Bo'yashga berildi"),
]


class CrafBasket(models.Model):
    _name = "craf.basket"
    _description = "Korzinka"
    _order = "name"

    name = fields.Char("Kodi", required=True, copy=False, default=lambda self: self._default_name())
    tare_kg = fields.Float("O'z og'irligi, kg", digits=(16, 1), help="Bo'sh korzinkaning og'irligi")
    capacity = fields.Integer("Sig'imi, dona", default=120)
    active = fields.Boolean(default=True)
    note = fields.Char("Izoh")
    load_ids = fields.One2many("craf.basket.load", "basket_id", string="To'ldirishlar")
    current_load_id = fields.Many2one("craf.basket.load", "Hozirgi yuk", compute="_compute_current")
    state = fields.Selection([("empty", "Bo'sh")] + LOAD_STATES[:2], string="Holati", compute="_compute_current",
                             search="_search_state")
    location_id = fields.Many2one("stock.location", "Qayerda", compute="_compute_current")
    pcs = fields.Integer("Ichida, dona", compute="_compute_current")
    kg = fields.Float("Ichida, kg", compute="_compute_current", digits=(16, 1))
    content = fields.Char("Ichida", compute="_compute_current")
    load_count = fields.Integer("To'ldirishlar soni", compute="_compute_load_count")

    _name_uniq = models.Constraint("unique(name)", "Korzinka kodi takrorlanmasligi kerak.")

    @api.model
    def _default_name(self):
        return self.env["ir.sequence"].next_by_code("craf.basket") or "K-"

    def _active_loads(self):
        return self.env["craf.basket.load"].search(
            [("basket_id", "in", self.ids), ("state", "in", ("press", "kimyo"))], order="id desc")

    def _compute_current(self):
        loads = self._active_loads()
        for basket in self:
            load = loads.filtered(lambda l: l.basket_id == basket)[:1]
            basket.current_load_id = load
            basket.state = load.state if load else "empty"
            basket.location_id = load.location_id
            basket.pcs = load.pcs_total
            basket.kg = load.net_kg or load.kg_theory
            basket.content = load.content if load else False

    def _search_state(self, operator, value):
        if operator in ("!=", "not in"):
            # Odoo 19 "!=" ni "not in" ga aylantiradi: teskari to'plam
            positive = self._search_state("in", [value] if operator == "!=" else list(value))
            return [("id", "not in", positive[0][2])]
        if operator not in ("=", "in"):
            raise NotImplementedError
        values = [value] if operator == "=" else list(value)
        busy = self.env["craf.basket.load"].search([("state", "in", ("press", "kimyo"))])
        ids = set()
        for state in values:
            if state == "empty":
                ids |= set(self.search([("id", "not in", busy.basket_id.ids)]).ids)
            else:
                ids |= set(busy.filtered(lambda l: l.state == state).basket_id.ids)
        return [("id", "in", list(ids))]

    def _compute_load_count(self):
        data = self.env["craf.basket.load"]._read_group([("basket_id", "in", self.ids)], ["basket_id"], ["__count"])
        counts = {b.id: c for b, c in data}
        for basket in self:
            basket.load_count = counts.get(basket.id, 0)

    def action_view_loads(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("craf_korzinka.action_craf_basket_load")
        action["domain"] = [("basket_id", "=", self.id)]
        action["context"] = {"default_basket_id": self.id}
        return action


class CrafBasketLoad(models.Model):
    """Press varag'idagi bitta qator: qaysi korzinkaga nima va nechta yuklangan.

    Daftardagi kabi: korzinka (№ va o'z og'irligi), profil va 6 m / 5 m dona, ikkinchi profil («Профил номи +»),
    kryuchok va palka og'irligi, brutto. Netto = brutto − korzinka − kryuchok − palka.
    Bo'yash bo'limida ajratilgan brak va 6 m → 5 m kesilganlar (craf.paint.sort) yuk tarkibidan chiqariladi."""
    _name = "craf.basket.load"
    _description = "Korzinka yuki (press smenasidan)"
    _order = "date desc, id desc"
    _rec_name = "display_name"

    basket_id = fields.Many2one("craf.basket", "Korzinka", required=True, index=True,
                                domain="[('state', '=', 'empty')]")
    shift_id = fields.Many2one("craf.extrusion.shift", "Press smenasi", required=True, ondelete="cascade", index=True)
    date = fields.Date(related="shift_id.date", store=True, string="Sana")
    section_id = fields.Many2one("craf.profile.section", "Profil", required=True, index=True)
    qty_6 = fields.Integer("6 m, dona")
    qty_5 = fields.Integer("5 m, dona")
    section2_id = fields.Many2one("craf.profile.section", "Profil 2", help="Shu korzinkadagi ikkinchi profil")
    qty2_6 = fields.Integer("Profil 2: 6 m")
    qty2_5 = fields.Integer("Profil 2: 5 m")
    product_6_id = fields.Many2one("product.product", "6 m mahsulot", compute="_compute_products", store=True)
    product_5_id = fields.Many2one("product.product", "5 m mahsulot", compute="_compute_products", store=True)
    product2_6_id = fields.Many2one("product.product", "Profil 2: 6 m mahsulot", compute="_compute_products",
                                    store=True)
    product2_5_id = fields.Many2one("product.product", "Profil 2: 5 m mahsulot", compute="_compute_products",
                                    store=True)
    pcs_total = fields.Integer("Jami, dona", compute="_compute_totals", store=True, aggregator="sum")
    kg_theory = fields.Float("Nazariy kg", compute="_compute_totals", store=True, digits=(16, 1), aggregator="sum")
    area_m2 = fields.Float("Maydon, m²", compute="_compute_totals", store=True, digits=(16, 1), aggregator="sum")
    tare_kg = fields.Float("Korzinka, kg", compute="_compute_tare_kg", store=True, readonly=False, digits=(16, 1),
                           aggregator="sum", help="Korzinka kartochkasidan olinadi; boshqa bo'lsa, shu yerda o'zgartiring.")
    hook_kg = fields.Float("Kryuchok, kg", default=28.0, digits=(16, 1), aggregator="sum")
    stick_kg = fields.Float("Palka, kg", default=6.0, digits=(16, 1), aggregator="sum")
    gross_kg = fields.Float("Brutto, kg", digits=(16, 1), aggregator="sum")
    net_kg = fields.Float("Netto, kg", compute="_compute_net", store=True, digits=(16, 1), aggregator="sum")
    kg_diff = fields.Float("Farq (netto − nazariy), kg", compute="_compute_net", store=True, digits=(16, 1))
    content = fields.Char("Ichida", compute="_compute_totals", store=True)
    sort_line_ids = fields.One2many("craf.paint.sort.line", "load_id", string="Bo'yashda ajratilgan")
    defect_pcs = fields.Integer("Brak, dona", compute="_compute_left", store=True, aggregator="sum")
    cut_pcs = fields.Integer("6 → 5 m kesildi, dona", compute="_compute_left", store=True, aggregator="sum")
    defect_kg = fields.Float("Brak, kg", compute="_compute_left", store=True, digits=(16, 1), aggregator="sum")
    left_text = fields.Char("Hozir ichida", compute="_compute_left")
    state = fields.Selection(LOAD_STATES, string="Holati", default="press", required=True, index=True)
    location_id = fields.Many2one("stock.location", "Qayerda", compute="_compute_location", store=True)
    treatment_id = fields.Many2one("craf.chem.treatment", "Kimyoviy ishlov", copy=False, index=True)
    paint_batch_id = fields.Many2one("craf.paint.batch", "Bo'yash smenasi", copy=False, index=True)
    shift_state = fields.Selection(related="shift_id.state", string="Smena holati")

    @api.depends("basket_id.name", "content")
    def _compute_display_name(self):
        for load in self:
            load.display_name = "%s · %s" % (load.basket_id.name or "?", load.content or "")

    @api.depends("basket_id")
    def _compute_tare_kg(self):
        for load in self:
            load.tare_kg = load.basket_id.tare_kg

    @api.onchange("shift_id")
    def _onchange_shift_id(self):
        if self.shift_id.section_id and not self.section_id:
            self.section_id = self.shift_id.section_id

    def _slots(self):
        """[(dona, mahsulot)] — yuk tarkibi (yuklangan holatda)."""
        self.ensure_one()
        return [(self.qty_6, self.product_6_id), (self.qty_5, self.product_5_id),
                (self.qty2_6, self.product2_6_id), (self.qty2_5, self.product2_5_id)]

    @api.depends("section_id", "section2_id")
    def _compute_products(self):
        Tmpl = self.env["product.template"]
        for load in self:
            for sec, f6, f5 in ((load.section_id, "product_6_id", "product_5_id"),
                                (load.section2_id, "product2_6_id", "product2_5_id")):
                load[f6] = Tmpl._craf_semi_for(sec, 6.0) if sec else False
                load[f5] = Tmpl._craf_semi_for(sec, 5.0, create=False) if sec else False

    @api.depends("qty_6", "qty_5", "qty2_6", "qty2_5", "product_6_id", "product_5_id", "product2_6_id",
                 "product2_5_id", "section_id.perimeter_m", "section2_id.perimeter_m")
    def _compute_totals(self):
        for load in self:
            kg = area = 0.0
            pcs = 0
            parts = []
            for sec, slots in ((load.section_id, ((load.qty_6, load.product_6_id), (load.qty_5, load.product_5_id))),
                               (load.section2_id, ((load.qty2_6, load.product2_6_id),
                                                   (load.qty2_5, load.product2_5_id)))):
                sub = []
                for qty, product in slots:
                    if qty and product:
                        kg += qty * product.craf_kg_per_pc
                        area += qty * product.craf_length_m * (sec.perimeter_m or 0.0)
                        pcs += qty
                        sub.append("%s×%gm" % (qty, product.craf_length_m))
                if sec and sub:
                    parts.append("%s: %s" % (sec.name, " + ".join(sub)))
            load.pcs_total = pcs
            load.kg_theory = kg
            load.area_m2 = area
            load.content = "; ".join(parts) or load.section_id.name

    @api.depends("gross_kg", "tare_kg", "hook_kg", "stick_kg", "kg_theory")
    def _compute_net(self):
        for load in self:
            net = load.gross_kg - load.tare_kg - load.hook_kg - load.stick_kg if load.gross_kg else 0.0
            load.net_kg = net
            load.kg_diff = net - load.kg_theory if net else 0.0

    @api.depends("sort_line_ids.qty", "sort_line_ids.kind", "sort_line_ids.kg", "sort_line_ids.state")
    def _compute_left(self):
        for load in self:
            lines = load.sort_line_ids.filtered(lambda l: l.state == "done")
            load.defect_pcs = sum(lines.filtered(lambda l: l.kind == "brak").mapped("qty"))
            load.cut_pcs = sum(lines.filtered(lambda l: l.kind == "cut").mapped("qty"))
            load.defect_kg = sum(lines.mapped("kg"))
            left = load._product_quantities()
            load.left_text = ", ".join("%s %s" % (p.display_name, q) for p, q in left.items()) if lines else False

    @api.depends("state", "shift_id.state")
    def _compute_location(self):
        Mixin = self.env["craf.production.mixin"]
        kimyo, press, boyash = (Mixin._craf_loc("Kimyoviy ishlov"), Mixin._craf_loc("Press sexi"),
                                Mixin._craf_loc("Bo'yash sexi"))
        for load in self:
            if load.state == "press":
                load.location_id = (kimyo or press) if load.shift_id.state == "done" else press
            elif load.state == "kimyo":
                load.location_id = boyash
            else:
                load.location_id = False

    @api.constrains("qty_6", "qty_5", "qty2_6", "qty2_5", "basket_id", "section2_id")
    def _check_capacity(self):
        for load in self:
            if min(load.qty_6, load.qty_5, load.qty2_6, load.qty2_5) < 0:
                raise ValidationError("Dona soni manfiy bo'lishi mumkin emas.")
            cap = load.basket_id.capacity
            if cap and load.pcs_total > cap:
                raise ValidationError("%s korzinkaga ko'pi bilan %s dona sig'adi (kiritildi: %s)." % (
                    load.basket_id.name, cap, load.pcs_total))
            if load.qty_5 and not load.product_5_id:
                raise ValidationError("%s profilining 5 m varianti katalogda yo'q." % load.section_id.name)
            if load.qty2_5 and not load.product2_5_id:
                raise ValidationError("%s profilining 5 m varianti katalogda yo'q." % load.section2_id.name)
            if (load.qty2_6 or load.qty2_5) and not load.section2_id:
                raise ValidationError("%s: ikkinchi profil donasi bor, lekin profili tanlanmagan." % load.basket_id.name)

    @api.constrains("basket_id", "state")
    def _check_basket_free(self):
        for load in self.filtered(lambda l: l.state in ("press", "kimyo")):
            other = self.search_count([("basket_id", "=", load.basket_id.id), ("id", "!=", load.id),
                                       ("state", "in", ("press", "kimyo"))])
            if other:
                raise ValidationError("%s korzinka band: u hali bo'shatilmagan." % load.basket_id.name)

    @api.model_create_multi
    def create(self, vals_list):
        loads = super().create(vals_list)
        loads._craf_remember_tare()
        return loads

    def write(self, vals):
        res = super().write(vals)
        if "tare_kg" in vals:
            self._craf_remember_tare()
        return res

    def _craf_remember_tare(self):
        """Korzinka kartochkasida og'irlik yo'q bo'lsa, birinchi yozilgani saqlanadi."""
        for load in self:
            if load.tare_kg and not load.basket_id.tare_kg:
                load.basket_id.tare_kg = load.tare_kg

    def _loaded_quantities(self):
        """{product: dona} — yuklangan holatda (bo'yashda ajratilganlarsiz)."""
        result = {}
        for load in self:
            for qty, product in load._slots():
                if qty and product:
                    result[product] = result.get(product, 0) + qty
        return result

    def _product_quantities(self):
        """{product: dona} — hozir ichida: yuklangan − brak − kesilgan (6 m) + kesilgandan chiqqan (5 m)."""
        result = {}
        for load in self:
            for product, qty in load._loaded_quantities().items():
                result[product] = result.get(product, 0) + qty
            for line in load.sort_line_ids.filtered(lambda l: l.state == "done"):
                result[line.product_id] = result.get(line.product_id, 0) - line.qty
                if line.kind == "cut" and line.target_product_id:
                    result[line.target_product_id] = result.get(line.target_product_id, 0) + line.qty
        return {p: q for p, q in result.items() if q}


class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.model
    def _craf_semi_for(self, section, length, create=True):
        """Kesim va uzunlik bo'yicha bo'yalmagan profil (yo'q bo'lsa yaratadi)."""
        raw = self._craf_raw_color()
        tmpl = self.search([("craf_section_id", "=", section.id), ("craf_length_m", "=", length),
                            ("craf_color_id", "=", raw.id)], limit=1)
        if tmpl:
            return tmpl.product_variant_id
        sample = self.search([("craf_section_id", "=", section.id), ("craf_length_m", "=", length)], limit=1)
        if sample and create:
            return sample._craf_semi_product()
        return self.env["product.product"]
