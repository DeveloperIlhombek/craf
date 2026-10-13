import re
from collections import defaultdict

from markupsafe import Markup, escape

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt

UGAR_OK = 3.0       # % gacha — yashil
UGAR_MAX = 5.0      # % dan yuqori yoki manfiy — izoh talab qilinadi

BALANCE_STATES = [
    ("none", "—"),
    ("ok", "Me'yorda"),
    ("warn", "Yuqori"),
    ("bad", "Me'yordan tashqari"),
]

_SUM_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?(?:[+-]\d+(?:\.\d+)?)*$")
_TERM_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")


def parse_sum(text):
    """Daftardagi yozuvni songa aylantiradi: '993+600+351' -> 1944.0, '27,5 + 31' -> 58.5.

    Bo'sh matn -> None. Noto'g'ri yozuv -> UserError.
    """
    if text is None or text is False:
        return None
    s = str(text).strip()
    if not s:
        return None
    s = s.replace(" ", "").replace(" ", "").replace(",", ".").lstrip("=")
    if not _SUM_RE.match(s):
        raise UserError("'%s' — tortishlarni faqat raqam va + bilan yozing, masalan: 993+600+351" % text)
    return round(sum(float(t) for t in _TERM_RE.findall(s)), 3)


class CrafFoundryMeltLine(models.Model):
    _inherit = "craf.foundry.melt.line"

    qty_text = fields.Char("Tortishlar", help="Bir necha tortishni + bilan yozing: 993+600+351 → 1 944")
    qty = fields.Float(string="Jami")
    uom_name = fields.Char("Birligi", compute="_compute_uom_name")
    available_all = fields.Float("Zavodda bor", compute="_compute_available_all", digits=(16, 1),
                                 help="Barcha ichki joylardagi qoldiq. Литейка da yetmasa, tasdiqlashda "
                                      "boshqa joydan avtomatik ko'chiriladi.")

    @api.depends("product_id")
    def _compute_uom_name(self):
        unit = self.env.ref("uom.product_uom_unit", raise_if_not_found=False)
        for line in self:
            uom = line.product_id.uom_id
            line.uom_name = "dona" if uom and uom == unit else (uom.name or "")

    @api.depends("product_id")
    def _compute_available_all(self):
        for line in self:
            line.available_all = line.product_id.qty_available if line.product_id else 0.0

    @api.onchange("qty_text")
    def _onchange_qty_text(self):
        if not self.qty_text:
            return
        try:
            value = parse_sum(self.qty_text)
        except UserError as err:
            return {"warning": {"title": "Tortishlar", "message": str(err)}}
        if value is not None:
            self.qty = value

    @api.onchange("qty")
    def _onchange_qty_keep_text(self):
        # Jami qo'lda o'zgartirilsa, eski "tortishlar" yozuvi o'chadi (chalkashmasin)
        if self.qty_text:
            try:
                value = parse_sum(self.qty_text)
            except UserError:
                value = None
            if value is None or abs(value - (self.qty or 0.0)) > 1e-6:
                self.qty_text = False

    @api.model
    def _craf_vals_from_text(self, vals):
        if vals.get("qty_text") and "qty" not in vals:
            vals["qty"] = parse_sum(vals["qty_text"]) or 0.0
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._craf_vals_from_text(dict(v)) for v in vals_list])

    def write(self, vals):
        return super().write(self._craf_vals_from_text(dict(vals)))


class CrafFoundryMelt(models.Model):
    _inherit = "craf.foundry.melt"

    charge_line_ids = fields.One2many(
        "craf.foundry.melt.line", "melt_id", string="Shixta (metall)", domain=[("is_metal", "=", True)])
    aux_line_ids = fields.One2many(
        "craf.foundry.melt.line", "melt_id", string="Sarf buyumlari", domain=[("is_metal", "=", False)])
    day_no = fields.Integer("Kun ichida №", copy=False, tracking=True,
                            help="Shu kuni shu pechdagi nechanchi plavka (daftardagi ①, ②)")

    billet_length = fields.Float("Stalba uzunligi, m", digits=(16, 2), help="Daftarda: Ст-узун")
    billet_count = fields.Integer("Stalba soni, dona")
    billet_kg_per_m = fields.Float("1 m stalba, kg", compute="_compute_billet_kg_per_m", digits=(16, 2))
    foundry_waste_qty = fields.Float("Литейка отход, kg", digits=(16, 1), aggregator="sum",
                                     help="Daftarda: Лит-от. Qayta eritiladi.")
    foundry_waste_product_id = fields.Many2one(
        "product.product", string="Литейка отход (mahsulot)", default=lambda self: self._craf_product("PF-11"))
    reuse_location_id = fields.Many2one(
        "stock.location", string="Qayta eritiladigan otxod qayerga", domain=[("usage", "=", "internal")],
        default=lambda self: self._craf_loc(self._craf_default_src),
        help="Сталба отход va Литейка отход shu joyga kiradi (keyingi plavkalarda ishlatiladi). Шлак — "
             "'Chiqindi qayerga' joyiga.")
    picking_ids = fields.Many2many(
        "stock.picking", "craf_foundry_melt_picking_rel", "melt_id", "picking_id",
        string="Avto ko'chirishlar", copy=False, readonly=True,
        help="Литейка da yetmagan material boshqa ichki joydan avtomatik ko'chirilgan hujjatlar")

    output_total = fields.Float("Chiqdi jami, kg", compute="_compute_kpi", store=True, digits=(16, 1),
                                aggregator="sum")
    waste_total = fields.Float("Otxod (ст + лит), kg", compute="_compute_kpi", store=True, digits=(16, 1),
                               aggregator="sum")
    balance_state = fields.Selection(BALANCE_STATES, string="Balans holati", compute="_compute_kpi", store=True)
    balance_html = fields.Html("Balans paneli", compute="_compute_balance_html", sanitize=False)
    balance_note = fields.Text("Balans izohi",
                               help="Угар manfiy yoki 5% dan yuqori bo'lsa sababini yozing: pechda oldingi "
                                    "plavkadan metall qolgan, tortish xatosi va h.k.")
    aux_summary = fields.Char("Sarf buyumlari (qisqa)", compute="_compute_aux_summary")
    craf_title = fields.Char("Sarlavha", compute="_compute_craf_title")

    @api.depends("equipment_id", "day_no", "date")
    def _compute_craf_title(self):
        for melt in self:
            parts = [melt.equipment_id.name or "Pech tanlanmagan"]
            if melt.day_no:
                parts.append("%s-plavka" % melt.day_no)
            if melt.date:
                parts.append(melt.date.strftime("%d.%m.%Y"))
            melt.craf_title = " · ".join(parts)

    # ---------------------------------------------------------------- shablon va raqam
    @api.model
    def _craf_template_products(self):
        products = self.env["product.product"].search([("craf_melt_seq", ">", 0)])
        return products.sorted(lambda p: (p.craf_melt_seq, p.default_code or ""))

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get("craf_litey_no_template"):
            return res
        products = None
        for fname, metal in (("charge_line_ids", True), ("aux_line_ids", False)):
            if fname not in fields_list or res.get(fname):
                continue
            if products is None:
                products = self._craf_template_products()
            res[fname] = [Command.create({
                "sequence": p.craf_melt_seq,
                "product_id": p.id,
                "is_metal": metal,
            }) for p in products if bool(p.craf_not_metal) != metal]
        return res

    @api.model
    def _craf_next_day_no(self, date, equipment_id, exclude_id=None):
        domain = [("date", "=", date), ("state", "!=", "cancel")]
        if equipment_id:
            domain.append(("equipment_id", "=", equipment_id))
        if exclude_id:
            domain.append(("id", "!=", exclude_id))
        return self.search_count(domain) + 1

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("day_no"):
                date = vals.get("date") or fields.Date.context_today(self)
                equipment = vals.get("equipment_id") or self._craf_default_equipment().id
                vals["day_no"] = self._craf_next_day_no(date, equipment)
        rec = self
        if any("line_ids" in v for v in vals_list):
            rec = self.with_context(craf_litey_no_template=True)
        return super(CrafFoundryMelt, rec).create(vals_list)

    @api.onchange("date", "equipment_id")
    def _onchange_day_no(self):
        if self.state == "draft" and self.date:
            self.day_no = self._craf_next_day_no(self.date, self.equipment_id.id, self._origin.id or None)

    # ---------------------------------------------------------------- hisob-kitob
    @api.depends("line_ids.qty", "line_ids.is_metal", "charge_line_ids.qty", "aux_line_ids.qty",
                 "billet_qty", "slag_qty", "cut_waste_qty", "foundry_waste_qty")
    def _compute_kpi(self):
        for melt in self:
            lines = melt.charge_line_ids | melt.aux_line_ids
            metal = sum(lines.filtered("is_metal").mapped("qty"))
            waste = melt.cut_waste_qty + melt.foundry_waste_qty
            out = melt.billet_qty + waste + melt.slag_qty
            loss = metal - out if melt.billet_qty else 0.0
            pct = loss / metal * 100.0 if metal and melt.billet_qty else 0.0
            if not metal or not melt.billet_qty:
                state = "none"
            elif 0.0 <= pct <= UGAR_OK + 1e-9:
                state = "ok"
            elif UGAR_OK < pct <= UGAR_MAX + 1e-9:
                state = "warn"
            else:
                state = "bad"
            melt.charge_total = sum(lines.mapped("qty"))
            melt.charge_metal = metal
            melt.waste_total = waste
            melt.output_total = out
            melt.burn_loss_qty = loss
            melt.burn_loss_pct = pct
            melt.yield_pct = melt.billet_qty / metal * 100.0 if metal else 0.0
            melt.balance_state = state

    @api.depends("billet_qty", "billet_length", "billet_count")
    def _compute_billet_kg_per_m(self):
        for melt in self:
            length = melt.billet_length * (melt.billet_count or 0)
            melt.billet_kg_per_m = melt.billet_qty / length if length > EPS else 0.0

    @api.depends("charge_metal", "billet_qty", "slag_qty", "burn_loss_qty", "cut_waste_qty", "foundry_waste_qty")
    def _compute_balance_text(self):
        for melt in self:
            if melt.charge_metal:
                melt.balance_text = "%s kg metall = %s stalba + %s ст-отход + %s лит-отход + %s шлак + %s угар" % (
                    fmt(melt.charge_metal), fmt(melt.billet_qty), fmt(melt.cut_waste_qty),
                    fmt(melt.foundry_waste_qty), fmt(melt.slag_qty), fmt(melt.burn_loss_qty, 1))
            else:
                melt.balance_text = False

    @api.depends("aux_line_ids.qty", "aux_line_ids.product_id")
    def _compute_aux_summary(self):
        for melt in self:
            unit = self.env.ref("uom.product_uom_unit", raise_if_not_found=False)
            parts = ["%s %s %s" % (l.product_id.name, fmt(l.qty, 2 if l.qty % 1 else 0),
                                   "dona" if l.product_id.uom_id == unit else (l.uom_name or ""))
                     for l in melt.aux_line_ids if l.qty > EPS]
            melt.aux_summary = ", ".join(parts) or False

    @api.depends("charge_metal", "billet_qty", "cut_waste_qty", "foundry_waste_qty", "slag_qty",
                 "burn_loss_qty", "burn_loss_pct", "balance_state")
    def _compute_balance_html(self):
        css = {"none": "secondary", "ok": "success", "warn": "warning", "bad": "danger"}
        for melt in self:
            if not melt.charge_metal and not melt.billet_qty:
                melt.balance_html = Markup(
                    '<div class="alert alert-secondary mb-0 py-2">Shixta va stalba kiritilgach, bu yerda balans '
                    'chiqadi: kirdi = stalba + otxod + шлак + угар.</div>')
                continue
            parts = [("Stalba", melt.billet_qty), ("Ст-отход", melt.cut_waste_qty),
                     ("Лит-отход", melt.foundry_waste_qty), ("Шлак", melt.slag_qty)]
            out_txt = " + ".join("%s %s" % (escape(n), fmt(q, 1 if q % 1 else 0)) for n, q in parts if q > EPS)
            if melt.balance_state == "none":
                verdict = "Stalba og'irligi kiritilmagan."
            elif melt.burn_loss_qty < 0:
                verdict = ("Chiqim kirimdan %s kg ko'p. Sabab: pechda oldingi plavkadan metall qolgan, "
                           "tortishda xato yoki shixta to'liq yozilmagan. Izoh yozing." % fmt(-melt.burn_loss_qty, 1))
            elif melt.balance_state == "ok":
                verdict = "Me'yorda (≤ %s%%)." % fmt(UGAR_OK)
            elif melt.balance_state == "warn":
                verdict = "Угар yuqori (%s–%s%%)." % (fmt(UGAR_OK), fmt(UGAR_MAX))
            else:
                verdict = "Угар %s%% dan yuqori — izoh yozing." % fmt(UGAR_MAX)
            melt.balance_html = Markup(
                '<div class="alert alert-{css} mb-0 py-2 o_craf_melt_balance">'
                '<div class="d-flex flex-wrap gap-3 align-items-baseline">'
                '<div><span class="text-muted small">Kirdi (metall)</span><br/><b class="fs-5">{metal}</b> kg</div>'
                '<div class="fs-5">→</div>'
                '<div><span class="text-muted small">Chiqdi: {out_txt}</span><br/><b class="fs-5">{out}</b> kg</div>'
                '<div class="ms-sm-auto text-sm-end"><span class="text-muted small">Угар</span><br/>'
                '<b class="fs-5">{loss}</b> kg · <b class="fs-5">{pct}%</b></div>'
                '</div><div class="small mt-1">{verdict}</div></div>'
            ).format(
                css=css[melt.balance_state], metal=fmt(melt.charge_metal, 1), out_txt=Markup(out_txt or "—"),
                out=fmt(melt.output_total, 1), loss=fmt(melt.burn_loss_qty, 1), pct=fmt(melt.burn_loss_pct, 2),
                verdict=verdict)

    def action_view_litey_pickings(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("stock.action_picking_tree_all")
        action["domain"] = [("id", "in", self.picking_ids.ids)]
        action["context"] = {"create": False}
        if len(self.picking_ids) == 1:
            action.update({"view_mode": "form", "views": [(False, "form")], "res_id": self.picking_ids.id})
        return action

    # ---------------------------------------------------------------- tasdiqlash
    def _craf_litey_pull(self, needs):
        """Литейка da yetmagan materialni boshqa ichki joylardan (avval Chiqindi) ko'chirib keladi."""
        self.ensure_one()
        src = self.location_src_id
        Quant = self.env["stock.quant"]
        plan = defaultdict(list)  # location -> [(product, qty)]
        inside = self.env["stock.location"].search([("id", "child_of", src.id)]).ids
        for product, qty in needs.items():
            if qty <= EPS or not product.is_storable:
                continue
            short = qty - product.with_context(location=src.id).qty_available
            if short <= EPS:
                continue
            by_loc = defaultdict(float)
            for quant in Quant.search([("product_id", "=", product.id), ("location_id.usage", "=", "internal"),
                                       ("location_id", "not in", inside), ("quantity", ">", 0),
                                       ("company_id", "in", [self.company_id.id, False])]):
                by_loc[quant.location_id] += quant.quantity
            for loc, avail in sorted(by_loc.items(), key=lambda kv: (kv[0] != self.waste_location_id, -kv[1])):
                take = min(short, avail)
                if take <= EPS:
                    continue
                plan[loc].append((product, take))
                short -= take
                if short <= EPS:
                    break
        pickings = self.env["stock.picking"]
        for loc, items in plan.items():
            warehouse = src.warehouse_id or loc.warehouse_id or self.env["stock.warehouse"].search(
                [("company_id", "=", self.company_id.id)], limit=1)
            picking = self.env["stock.picking"].create({
                "picking_type_id": warehouse.int_type_id.id,
                "location_id": loc.id,
                "location_dest_id": src.id,
                "origin": self.name,
                "move_ids": [Command.create({
                    "product_id": product.id,
                    "product_uom_qty": qty,
                    "product_uom": product.uom_id.id,
                    "location_id": loc.id,
                    "location_dest_id": src.id,
                    "origin": self.name,
                }) for product, qty in items],
            })
            picking.action_confirm()
            picking.action_assign()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True
            picking.with_context(skip_backorder=True, picking_ids_not_to_backorder=picking.ids).button_validate()
            if picking.state != "done":
                raise UserError("Avto ko'chirish bajarilmadi (%s): %s" % (picking.state, picking.name))
            pickings |= picking
        if pickings:
            self.picking_ids = [Command.link(p.id) for p in pickings]
        return pickings

    def _craf_check_total(self, needs):
        """Butun zavodda ham yetmasa — aniq xabar."""
        missing = []
        for product, qty in needs.items():
            if qty <= EPS or not product.is_storable:
                continue
            have = product.qty_available
            if qty - have > EPS:
                missing.append("• %s: kerak %s, zavodda bor %s %s" % (
                    product.display_name, fmt(qty, 2 if qty % 1 else 0), fmt(have, 2 if have % 1 else 0),
                    product.uom_id.name))
        if missing:
            raise UserError(
                "Qoldiq yetarli emas:\n%s\n\nAvval kirimni yozing yoki qoldiqni tuzating "
                "(Craf → Литейка hisoboti → Kirim / Excel qoldig'i)." % "\n".join(missing))

    def _craf_action_done(self):
        """Daftar bo'yicha plavka: korzinka/asosiy moduldagi qattiq tekshiruv o'rniga yumshoq nazorat."""
        self.ensure_one()
        zero = self.line_ids.filtered(lambda l: l.qty <= EPS)
        lines = self.line_ids - zero
        if not lines.filtered("is_metal"):
            raise UserError("Shixta (metall) miqdorlarini kiriting.")
        if self.billet_qty <= EPS:
            raise UserError("Chiqqan stalba og'irligini (kg) kiriting.")
        if self.balance_state == "bad" and not (self.balance_note or "").strip():
            raise UserError(
                "Угар %s kg (%s%%) — me'yordan tashqarida (0–%s%%).\n\n"
                "Sababini 'Balans izohi' maydoniga yozing (masalan: pechda oldingi plavkadan metall qolgan, "
                "tortishda xato) yoki raqamlarni tekshiring." % (
                    fmt(self.burn_loss_qty, 1), fmt(self.burn_loss_pct, 2), fmt(UGAR_MAX)))
        outputs = [
            (self.slag_product_id, self.slag_qty, self.waste_location_id, "Шлак"),
            (self.cut_waste_product_id, self.cut_waste_qty, self.reuse_location_id or self.location_src_id,
             "Сталба отход"),
            (self.foundry_waste_product_id, self.foundry_waste_qty, self.reuse_location_id or self.location_src_id,
             "Литейка отход"),
        ]
        for product, qty, _loc, label in outputs:
            if qty > EPS and not product:
                raise UserError("%s mahsulotini tanlang." % label)
        needs = defaultdict(float)
        for line in lines:
            needs[line.product_id] += line.qty
        self._craf_check_total(needs)
        self._craf_litey_pull(needs)
        self._craf_check_available(self.location_src_id, needs)
        zero.unlink()
        byproducts = [(p, q, loc) for p, q, loc, _label in outputs if q > EPS]
        mo = self.with_context(craf_melt_cut_waste=False)._craf_produce(
            self.billet_product_id, self.billet_qty, self.location_src_id, self.location_dest_id,
            list(needs.items()), byproducts)
        summary = [
            Markup("<b>Plavka tasdiqlandi</b> — %s") % mo.name,
            "Shixta: metall %s kg (jami %s kg)" % (fmt(self.charge_metal, 1), fmt(self.charge_total, 1)),
            "Stalba: %s kg%s → %s" % (
                fmt(self.billet_qty, 1),
                " (%s m)" % fmt(self.billet_length, 2) if self.billet_length else "",
                self.location_dest_id.name),
            "Otxod: Сталба %s kg, Литейка %s kg → %s; Шлак %s kg → %s" % (
                fmt(self.cut_waste_qty, 1), fmt(self.foundry_waste_qty, 1),
                (self.reuse_location_id or self.location_src_id).name, fmt(self.slag_qty, 1),
                self.waste_location_id.name),
            "Угар: %s kg (%s%%)" % (fmt(self.burn_loss_qty, 1), fmt(self.burn_loss_pct, 2)),
        ]
        if self.aux_summary:
            summary.append("Sarf buyumlari: %s" % self.aux_summary)
        if self.picking_ids:
            summary.append("Avto ko'chirildi: %s" % ", ".join(self.picking_ids.mapped("name")))
        if self.balance_note:
            summary.append("Izoh: %s" % self.balance_note)
        self._craf_post_summary(summary)
