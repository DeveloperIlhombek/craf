from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

# Korzinka aylanishi: press yuklaydi → bo'yash va qadoqlash bo'limida («press»/«kimyo» — eski kimyoviy ishlov holati)
# → korzinka press varag'ida qayta yozilganda oldingi yuk «Qaytdi» bo'ladi (profillar bo'yashdan o'tgan).
LOAD_STATES = [
    ("press", "Bo'yashda"),
    ("kimyo", "Bo'yashda"),
    ("boyash", "Qaytdi"),
]
ACTIVE = ("press", "kimyo")
STALE_DAYS = 3  # shundan ko'p kun to'la turgan korzinka «uzoq turgan»


class CrafBasket(models.Model):
    _name = "craf.basket"
    _description = "Korzinka"
    _order = "name"

    name = fields.Char("Kodi", required=True, copy=False, default=lambda self: self._default_name())
    tare_kg = fields.Float("O'z og'irligi, kg", digits=(16, 1), help="Bo'sh korzinkaning og'irligi")
    capacity = fields.Integer("Sig'imi, dona", default=120)
    active = fields.Boolean(default=True)
    note = fields.Char("Izoh")
    broken = fields.Boolean("Yaroqsiz", copy=False, index=True, tracking=False,
                            help="Yaroqsiz korzinka press varag'ida tanlanmaydi; tuzatilgach «Yaroqli» qilinadi.")
    broken_date = fields.Date("Yaroqsiz bo'lgan sana", copy=False)
    broken_note = fields.Char("Yaroqsizlik sababi", copy=False)
    load_ids = fields.One2many("craf.basket.load", "basket_id", string="To'ldirishlar")
    current_load_id = fields.Many2one("craf.basket.load", "Hozirgi yuk", compute="_compute_current")
    state = fields.Selection([("empty", "Bo'sh"), ("press", "To'la"), ("kimyo", "To'la"), ("broken", "Yaroqsiz")],
                             string="Holati", compute="_compute_current", search="_search_state")
    location_id = fields.Many2one("stock.location", "Qayerda", compute="_compute_current")
    pcs = fields.Integer("Ichida, dona", compute="_compute_current")
    kg = fields.Float("Ichida, kg", compute="_compute_current", digits=(16, 1))
    content = fields.Char("Ichida", compute="_compute_current")
    loaded_date = fields.Date("To'ldirilgan sana", compute="_compute_current")
    days_full = fields.Integer("To'la turibdi, kun", compute="_compute_current")
    load_count = fields.Integer("Aylanishlar soni", compute="_compute_cycle")
    cycle_days = fields.Float("O'rtacha aylanish, kun", compute="_compute_cycle", digits=(16, 1),
                              help="Ketma-ket ikki to'ldirish orasidagi o'rtacha kun (press → bo'yash → press)")
    is_stale = fields.Boolean("Uzoq turgan", compute="_compute_current", search="_search_stale",
                              help="%s kundan ko'p to'la turgan" % STALE_DAYS)

    _name_uniq = models.Constraint("unique(name)", "Korzinka kodi takrorlanmasligi kerak.")

    @api.model
    def _default_name(self):
        return self.env["ir.sequence"].next_by_code("craf.basket") or "K-"

    def _active_loads(self):
        return self.env["craf.basket.load"].search(
            [("basket_id", "in", self.ids), ("state", "in", ACTIVE)], order="id desc")

    def _compute_current(self):
        loads = self._active_loads()
        today = fields.Date.context_today(self)
        for basket in self:
            load = loads.filtered(lambda l: l.basket_id == basket)[:1]
            basket.current_load_id = load
            basket.state = "broken" if basket.broken else (load.state if load else "empty")
            basket.location_id = load.location_id
            basket.pcs = load.pcs_total
            basket.kg = load.net_kg or load.kg_theory
            basket.content = load.content if load else False
            basket.loaded_date = load.date
            basket.days_full = (today - load.date).days if load.date else 0
            basket.is_stale = bool(load) and basket.days_full > STALE_DAYS

    def _compute_cycle(self):
        Load = self.env["craf.basket.load"]
        dates = {}
        for basket, date in Load._read_group([("basket_id", "in", self.ids), ("date", "!=", False)],
                                             ["basket_id", "date:day"]):
            dates.setdefault(basket.id, []).append(date)
        for basket in self:
            days = sorted(set(dates.get(basket.id, [])))
            basket.load_count = len(days)
            gaps = [(b - a).days for a, b in zip(days, days[1:])]
            basket.cycle_days = sum(gaps) / len(gaps) if gaps else 0.0

    def _search_state(self, operator, value):
        if operator in ("!=", "not in"):
            # Odoo 19 "!=" ni "not in" ga aylantiradi: teskari to'plam
            positive = self._search_state("in", [value] if operator == "!=" else list(value))
            return [("id", "not in", positive[0][2])]
        if operator not in ("=", "in"):
            raise NotImplementedError
        values = [value] if operator == "=" else list(value)
        busy = self.env["craf.basket.load"].search([("state", "in", ACTIVE)])
        broken = self.search([("broken", "=", True)]).ids
        ids = set()
        for state in values:
            if state == "broken":
                ids |= set(broken)
            elif state == "empty":
                ids |= set(self.search([("id", "not in", busy.basket_id.ids), ("broken", "=", False)]).ids)
            else:
                ids |= set(busy.filtered(lambda l: l.state == state).basket_id.ids) - set(broken)
        return [("id", "in", list(ids))]

    def _search_stale(self, operator, value):
        if operator not in ("=", "in", "!=", "not in"):
            raise NotImplementedError
        limit = fields.Date.context_today(self) - timedelta(days=STALE_DAYS)
        ids = self.env["craf.basket.load"].search([("state", "in", ACTIVE), ("date", "<", limit)]).basket_id.ids
        positive = operator in ("=", "in")
        return [("id", "in" if positive else "not in", ids)]

    # ------------------------------------------------------------------ tugmalar
    def action_mark_broken(self):
        for basket in self:
            if basket.current_load_id:
                raise UserError("%s to'la (%s) — avval bo'shating." % (basket.name, basket.content))
        self.write({"broken": True, "broken_date": fields.Date.context_today(self)})
        return True

    def action_mark_ok(self):
        self.write({"broken": False, "broken_date": False, "broken_note": False})
        return True

    def action_release(self):
        """Korzinka bo'yash va qadoqlashdan bo'sh qaytdi (press varag'ida qayta yozilmasdan)."""
        self._active_loads().write({"state": "boyash", "returned_date": fields.Date.context_today(self)})
        return True

    def action_view_loads(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("craf_korzinka.action_craf_basket_load")
        action["domain"] = [("basket_id", "=", self.id)]
        action["context"] = {"default_basket_id": self.id}
        return action

    @api.model
    def get_dashboard(self):
        """Korzinkalar sahifasi tepasidagi kichik dashboard."""
        baskets = self.search([])
        filled = baskets.filtered(lambda b: b.state in ACTIVE)
        cycles = [b.cycle_days for b in baskets if b.cycle_days]
        stale = filled.filtered("is_stale")
        return {
            "total": len(baskets),
            "empty": len(baskets.filtered(lambda b: b.state == "empty")),
            "filled": len(filled),
            "broken": len(baskets.filtered("broken")),
            "kg": round(sum(filled.mapped("kg")), 1),
            "pcs": sum(filled.mapped("pcs")),
            "cycle_days": round(sum(cycles) / len(cycles), 1) if cycles else 0,
            "stale": len(stale),
            "stale_days": STALE_DAYS,
            "oldest": [{"name": b.name, "days": b.days_full, "content": b.content or ""}
                       for b in stale.sorted(lambda b: -b.days_full)[:3]],
        }


class CrafBasketLoad(models.Model):
    """Press varag'idagi bitta qator: qaysi korzinkaga nima va nechta yuklangan.

    Daftardagi kabi: korzinka (№ va o'z og'irligi), asosiy profil va 6 m / 5 m dona, kerak bo'lsa qo'shimcha
    profillar (bitta korzinkada 2-3 xil), kryuchok va palka og'irligi, brutto. Netto = brutto − korzinka − kryuchok − palka.
    Bo'yash bo'limida ajratilgan brak va 6 m → 5 m kesilganlar (craf.paint.sort) yuk tarkibidan chiqariladi."""
    _name = "craf.basket.load"
    _description = "Korzinka yuki (press smenasidan)"
    _order = "date desc, id"  # varaq ichida — kiritilgan tartibda
    _rec_name = "display_name"

    basket_id = fields.Many2one("craf.basket", "Korzinka", required=True, index=True,
                                domain="[('broken', '=', False)]",
                                help="To'la korzinka ham tanlanadi: press varag'ida qayta yozilgani — oldingi yuki "
                                     "bo'yash va qadoqlashdan o'tgan degani, u «Qaytdi» bo'ladi.")
    shift_id = fields.Many2one("craf.extrusion.shift", "Press varag'i", required=True, ondelete="cascade", index=True)
    date = fields.Date(related="shift_id.date", store=True, string="Sana")
    section_id = fields.Many2one("craf.profile.section", "Profil", required=True, index=True)
    qty_6 = fields.Integer("6 m, dona")
    qty_5 = fields.Integer("5 m, dona")
    extra_line_ids = fields.One2many("craf.basket.load.line", "load_id", string="Qo'shimcha profillar", copy=True,
                                     help="Shu korzinkadagi boshqa profillar (2-, 3-profil)")
    product_6_id = fields.Many2one("product.product", "6 m mahsulot", compute="_compute_products", store=True)
    product_5_id = fields.Many2one("product.product", "5 m mahsulot", compute="_compute_products", store=True)
    piece_kg = fields.Float("1 dona, kg", compute="_compute_piece_kg", store=True, readonly=False, digits=(16, 3),
                            help="6 metrlik 1 dona profilning tortilgan og'irligi (daftardagi «КГ 1шт»). Katalogdagi "
                                 "og'irlikdan olinadi; boshqa bo'lsa yozing. 5 m — shuning 5/6 qismi.")
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
    returned_date = fields.Date("Qaytgan sana", copy=False,
                                help="Korzinka bo'yash va qadoqlashdan qaytgan (qayta to'ldirilgan yoki bo'shatilgan) kun")
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

    @api.onchange("shift_id", "basket_id")
    def _onchange_defaults_from_last(self):
        """Yangi korzinka: profil, 1 dona kg, kryuchok va palka shu varaqdagi oxirgi korzinkadan
        (daftarda odatda bir xil). Formadagi hali saqlanmagan korzinkalar ham hisobga olinadi."""
        if self.section_id or not self.shift_id:
            return
        last = (self.shift_id.basket_load_ids - self).filtered("section_id")[-1:]
        if last:
            self.update({"section_id": last.section_id, "piece_kg": last.piece_kg,
                         "hook_kg": last.hook_kg, "stick_kg": last.stick_kg})
        elif self.shift_id.section_id:
            self.section_id = self.shift_id.section_id

    def _slots(self):
        """[(dona, mahsulot)] — yuk tarkibi (yuklangan holatda): asosiy profil va qo'shimchalari."""
        self.ensure_one()
        slots = [(self.qty_6, self.product_6_id), (self.qty_5, self.product_5_id)]
        for line in self.extra_line_ids:
            slots += [(line.qty_6, line.product_6_id), (line.qty_5, line.product_5_id)]
        return slots

    @api.depends("section_id")
    def _compute_products(self):
        Tmpl = self.env["product.template"]
        for load in self:
            sec = load.section_id
            load.product_6_id = Tmpl._craf_semi_for(sec, 6.0) if sec else False
            load.product_5_id = Tmpl._craf_semi_for(sec, 5.0, create=False) if sec else False

    @api.depends("product_6_id")
    def _compute_piece_kg(self):
        for load in self:
            load.piece_kg = load.product_6_id.craf_kg_per_pc

    @api.depends("qty_6", "qty_5", "product_6_id", "product_5_id", "piece_kg", "section_id.perimeter_m",
                 "extra_line_ids.pcs", "extra_line_ids.kg_theory", "extra_line_ids.area_m2", "extra_line_ids.content")
    def _compute_totals(self):
        for load in self:
            kg, area, pcs, text = _profile_totals(load.section_id, load.piece_kg, (
                (load.qty_6, load.product_6_id), (load.qty_5, load.product_5_id)))
            parts = [text] if text else []
            for line in load.extra_line_ids:
                kg += line.kg_theory
                area += line.area_m2
                pcs += line.pcs
                if line.content:
                    parts.append(line.content)
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
                # kimyoviy ishlov alohida yuritilmaydi: tasdiqlangan press chiqishi to'g'ri bo'yash sexida
                load.location_id = boyash if load.shift_id.state == "done" else press
            elif load.state == "kimyo":
                load.location_id = boyash
            else:
                load.location_id = False

    @api.constrains("qty_6", "qty_5", "basket_id", "extra_line_ids")
    def _check_capacity(self):
        for load in self:
            if min(load.qty_6, load.qty_5) < 0:
                raise ValidationError("Dona soni manfiy bo'lishi mumkin emas.")
            cap = load.basket_id.capacity
            if cap and load.pcs_total > cap:
                raise ValidationError("%s korzinkaga ko'pi bilan %s dona sig'adi (kiritildi: %s)." % (
                    load.basket_id.name, cap, load.pcs_total))
            if load.qty_5 and not load.product_5_id:
                raise ValidationError("%s profilining 5 m varianti katalogda yo'q." % load.section_id.name)

    @api.constrains("basket_id", "state")
    def _check_basket_free(self):
        for load in self.filtered(lambda l: l.state in ACTIVE):
            if load.basket_id.broken:
                raise ValidationError("%s korzinka yaroqsiz deb belgilangan." % load.basket_id.name)
            other = self.search_count([("basket_id", "=", load.basket_id.id), ("id", "!=", load.id),
                                       ("state", "in", ACTIVE)])
            if other:
                raise ValidationError("%s korzinka band: u hali bo'shatilmagan." % load.basket_id.name)

    def _craf_release_previous(self, basket_ids, shift_ids):
        """Korzinka press varag'ida qayta yozildi — oldingi yuki bo'yash va qadoqlashdan o'tgan: «Qaytdi».
        Shu varaqning o'zida (yoki hali tasdiqlanmagan boshqa varaqda) bo'lsa — xato."""
        prev = self.search([("basket_id", "in", basket_ids), ("state", "in", ACTIVE)])
        for load in prev:
            if load.shift_id.id in shift_ids:
                raise ValidationError("%s korzinka shu varaqda allaqachon yozilgan." % load.basket_id.name)
            if load.shift_id.state != "done":
                raise ValidationError("%s korzinka hali tasdiqlanmagan %s varag'ida turibdi." % (
                    load.basket_id.name, load.shift_id.name))
        prev.write({"state": "boyash", "returned_date": fields.Date.context_today(self)})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("section_id") and vals.get("shift_id"):
                # «Press sahifasi» profilni yubormaydi — varaq matritsasi yoki oxirgi korzinka profili
                shift = self.env["craf.extrusion.shift"].browse(vals["shift_id"])
                section = shift.section_id or shift.basket_load_ids.filtered("section_id")[-1:].section_id
                if section:
                    vals["section_id"] = section.id
        for vals in vals_list:
            if vals.get("basket_id"):
                self._craf_release_previous([vals["basket_id"]], [vals.get("shift_id")])
        loads = super().create(vals_list)
        loads._craf_remember_tare()
        return loads

    def write(self, vals):
        if vals.get("basket_id"):
            for load in self.filtered(lambda l: l.basket_id.id != vals["basket_id"] and l.state in ACTIVE):
                self._craf_release_previous([vals["basket_id"]], [load.shift_id.id])
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


def _profile_totals(section, piece_kg, slots):
    """(kg, maydon, dona, matn) — bitta profilning 6 m / 5 m donasi bo'yicha. piece_kg — tortilgan 1 dona (6 m) kg."""
    kg = area = 0.0
    pcs = 0
    sub = []
    for qty, product in slots:
        if qty and product:
            per = piece_kg * product.craf_length_m / 6.0 if piece_kg else product.craf_kg_per_pc
            kg += qty * per
            area += qty * product.craf_length_m * (section.perimeter_m or 0.0)
            pcs += qty
            sub.append("%s×%gm" % (qty, product.craf_length_m))
    return kg, area, pcs, ("%s: %s" % (section.name, " + ".join(sub)) if section and sub else "")


class CrafBasketLoadLine(models.Model):
    """Korzinkadagi qo'shimcha profil (bitta korzinkaga 2-3 xil profil solinganda)."""
    _name = "craf.basket.load.line"
    _description = "Korzinkadagi qo'shimcha profil"
    _order = "id"

    load_id = fields.Many2one("craf.basket.load", required=True, ondelete="cascade", index=True)
    section_id = fields.Many2one("craf.profile.section", "Profil", required=True)
    piece_kg = fields.Float("1 dona, kg", compute="_compute_piece_kg", store=True, readonly=False, digits=(16, 3),
                            help="6 metrlik 1 dona og'irligi; 5 m — shuning 5/6 qismi.")
    qty_6 = fields.Integer("6 m, dona")
    qty_5 = fields.Integer("5 m, dona")
    product_6_id = fields.Many2one("product.product", "6 m mahsulot", compute="_compute_products", store=True)
    product_5_id = fields.Many2one("product.product", "5 m mahsulot", compute="_compute_products", store=True)
    pcs = fields.Integer("Dona", compute="_compute_totals", store=True)
    kg_theory = fields.Float("Nazariy kg", compute="_compute_totals", store=True, digits=(16, 1))
    area_m2 = fields.Float("Maydon, m²", compute="_compute_totals", store=True, digits=(16, 1))
    content = fields.Char("Ichida", compute="_compute_totals", store=True)

    @api.depends("section_id")
    def _compute_products(self):
        Tmpl = self.env["product.template"]
        for line in self:
            sec = line.section_id
            line.product_6_id = Tmpl._craf_semi_for(sec, 6.0) if sec else False
            line.product_5_id = Tmpl._craf_semi_for(sec, 5.0, create=False) if sec else False

    @api.depends("product_6_id")
    def _compute_piece_kg(self):
        for line in self:
            line.piece_kg = line.product_6_id.craf_kg_per_pc

    @api.depends("qty_6", "qty_5", "product_6_id", "product_5_id", "piece_kg", "section_id.perimeter_m")
    def _compute_totals(self):
        for line in self:
            line.kg_theory, line.area_m2, line.pcs, line.content = _profile_totals(
                line.section_id, line.piece_kg, ((line.qty_6, line.product_6_id), (line.qty_5, line.product_5_id)))

    @api.constrains("qty_6", "qty_5", "section_id")
    def _check_qty(self):
        for line in self:
            if min(line.qty_6, line.qty_5) < 0:
                raise ValidationError("Dona soni manfiy bo'lishi mumkin emas.")
            if line.qty_5 and not line.product_5_id:
                raise ValidationError("%s profilining 5 m varianti katalogda yo'q." % line.section_id.name)


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
