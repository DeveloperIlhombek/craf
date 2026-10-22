from collections import defaultdict
from datetime import datetime, time, timedelta

from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL

EPS = 1e-6

FORECAST_STATUS = [
    ("neg", "Manfiy qoldiq"), ("out", "Tugagan"), ("low", "Minimaldan kam"),
    ("soon", "Tez orada tugaydi"), ("ok", "Yetarli"), ("idle", "Sarflanmayapti"),
]
NORM_STATUS = [("ok", "Normada"), ("low", "Normadan past")]

SHIFTS = [("1", "1-smena"), ("2", "2-smena"), ("3", "3-smena")]
STATES = [("draft", "Qoralama"), ("done", "Bajarildi"), ("cancel", "Bekor qilingan")]


def fmt(value, digits=0):
    """1234.5 -> '1 234,5' (o'zbekcha ko'rinish)."""
    text = f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")
    return text


class CrafProductionMixin(models.AbstractModel):
    _name = "craf.production.mixin"
    _description = "Craf ishlab chiqarish hujjati (umumiy)"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    # Har bir hujjat turi o'zini belgilaydi
    _craf_sequence_code = None
    _craf_stage = None
    _craf_default_src = None      # joylashuv nomi
    _craf_default_dest = None
    _craf_default_waste = "Chiqindi"
    # Guruh va jami qatorida oddiy o'rtacha emas, og'irlik bo'yicha:
    # {maydon: (surat, maxraj, koeffitsient, qo'shimcha)} → Σ surat / Σ maxraj × koeffitsient + qo'shimcha.
    # Masalan, 200 kg quymada 90% va 2000 kg quymada 70% → 80% emas, 71,8%.
    _craf_weighted_avg = {}

    name = fields.Char("Raqam", required=True, copy=False, readonly=True, default="Yangi", index=True)
    date = fields.Date("Sana", required=True, default=fields.Date.context_today, tracking=True, index=True)
    shift = fields.Selection(SHIFTS, string="Smena", required=True, default="1", tracking=True)
    equipment_id = fields.Many2one(
        "maintenance.equipment", string="Uskuna", tracking=True,
        domain=lambda self: [("craf_stage", "=", self._craf_stage)] if self._craf_stage else [],
        default=lambda self: self._craf_default_equipment())
    employee_id = fields.Many2one("hr.employee", string="Mas'ul", tracking=True)
    duration = fields.Float("Ish vaqti, soat", default=12.0, aggregator="sum")
    state = fields.Selection(STATES, string="Holat", required=True, default="draft", tracking=True,
                             copy=False, index=True)
    location_src_id = fields.Many2one(
        "stock.location", string="Sarf qayerdan", required=True, domain=[("usage", "=", "internal")],
        default=lambda self: self._craf_loc(self._craf_default_src))
    waste_location_id = fields.Many2one(
        "stock.location", string="Chiqindi qayerga", required=True, domain=[("usage", "=", "internal")],
        default=lambda self: self._craf_loc(self._craf_default_waste))
    production_ids = fields.Many2many("mrp.production", string="Ishlab chiqarish buyurtmalari", copy=False,
                                      readonly=True)
    production_count = fields.Integer("Buyurtmalar", compute="_compute_production_count")
    pack_count = fields.Integer("Pachkalar", compute="_compute_pack_count")
    has_pack_items = fields.Boolean("Pachkalanadigan chiqish bor", compute="_compute_has_pack_items")
    note = fields.Text("Izoh")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)

    @api.model
    def _read_group_select(self, aggregate_spec, query):
        fname, _sep, func = aggregate_spec.partition(":")
        if func == "avg" and fname in self._craf_weighted_avg:
            num, den, factor, *offset = self._craf_weighted_avg[fname]
            return SQL("SUM(%s) * %s / NULLIF(SUM(%s), 0) + %s", self._field_to_sql(self._table, num, query),
                       factor, self._field_to_sql(self._table, den, query), offset[0] if offset else 0.0)
        return super()._read_group_select(aggregate_spec, query)

    # ---------------------------------------------------------------- prognoz va eslatma
    @api.model
    def _craf_forecast_status(self, qty, avg, min_qty, warn):
        """Material holati: qoldiq, o'rtacha kunlik sarf, minimal qoldiq va ogohlantirish kunlari bo'yicha."""
        days_left = qty / avg if avg > EPS and qty > 0 else None
        days_to_min = (qty - min_qty) / avg if avg > EPS and min_qty and qty > min_qty else None
        if qty < -EPS:
            status = "neg"
        elif qty < EPS and avg > EPS:
            status = "out"  # tugagan, lekin sarflanadi
        elif min_qty and qty < min_qty:
            status = "low"
        elif (days_to_min is not None and days_to_min <= warn) or (
                not min_qty and days_left is not None and days_left <= warn):
            status = "soon"
        elif avg <= EPS:
            status = "idle"
        else:
            status = "ok"
        return status, days_left

    @api.model
    def _craf_consumption(self, products, bolim_code, history_products=None):
        """Oxirgi N kun (bo'lim sozlamasi) sarfi: ichki joydan ishlab chiqarishga ketgan bajarilgan harakatlar
        (smena/plavka hujjatlari va Excel'dan kiritilgan kunlik sarf ham shu yerga tushadi).

        Tarix N kundan qisqa bo'lsa, N — birinchi sarf kunidan bugungacha; tarix uzunligi history_products
        (berilmasa products) bo'yicha olinadi, shunda bitta material so'ralsa ham davr bir xil bo'ladi.
        Qaytaradi: (davr, ogohlantirish kunlari, {product_id: sarf})."""
        bolim = self.env["craf.bolim"]._get(bolim_code)
        period = max(bolim.forecast_days or 30, 1)
        warn = max(bolim.warn_days or 0, 0)
        today = fields.Date.context_today(self)
        Move = self.env["stock.move"].sudo()
        spend = [("state", "=", "done"), ("location_id.usage", "=", "internal"),
                 ("location_dest_id.usage", "=", "production")]
        first = Move.search(spend + [("product_id", "in", (history_products or products).ids)], order="date", limit=1)
        if first:
            first_day = fields.Date.context_today(self, first.date)
            period = max(min(period, (today - first_day).days + 1), 1)
        start = today - timedelta(days=period - 1)
        start_local = fields.Datetime.context_timestamp(self, datetime.combine(start, time.min))
        start_utc = datetime.combine(start, time.min) - (start_local.utcoffset() or timedelta())
        used = {p.id: q for p, q in Move._read_group(
            spend + [("product_id", "in", products.ids), ("date", ">=", start_utc)],
            ["product_id"], ["product_qty:sum"])}
        return period, warn, used

    @api.model
    def _craf_days_text(self, days_left):
        """Ko'rsatish uchun: «~12 kun», «1 yildan ortiq» yoki False (sarf yo'q)."""
        if days_left is None:
            return False
        if days_left > 365:
            return "1 yildan ortiq"
        return "~%s kun" % fmt(days_left, 0 if days_left >= 10 else 1)

    @api.model
    def _craf_min_qty_sync(self, rows, bolim_code, act_xmlid, label):
        """Minimaldan kam materiallar uchun bo'lim mas'ullariga eslatma; qoldiq tiklansa — eslatma yopiladi.

        rows: [{product, qty, min_qty, days_left, status, uom}]. Shu mahsulot bo'yicha Liteyka eslatmasi bor
        foydalanuvchiga ikkinchisi qo'yilmaydi."""
        act_type = self.env.ref(act_xmlid, raise_if_not_found=False)
        if not act_type:
            return
        bolim = self.env["craf.bolim"]._get(bolim_code)
        users = self.env["res.users"]
        if bolim.notify_app:
            users = bolim.contact_ids.filtered(lambda c: c.active and c.notify_min_qty and c.user_id).user_id
        low = {r["product"].product_tmpl_id.id: r for r in rows
               if r["status"] in ("low", "neg", "out") and r["min_qty"]}
        Activity = self.env["mail.activity"].sudo()
        litey_type = self.env.ref("craf_litey.mail_activity_min_qty", raise_if_not_found=False)
        litey_have = set()
        if litey_type and litey_type != act_type:
            litey_have = {(a.res_id, a.user_id.id) for a in Activity.search([
                ("activity_type_id", "=", litey_type.id), ("res_model", "=", "product.template")])}
        have = set()
        for act in Activity.search([("activity_type_id", "=", act_type.id), ("res_model", "=", "product.template")]):
            if act.res_id in low and act.user_id in users:
                have.add((act.res_id, act.user_id.id))
                note = self._craf_min_qty_note(low[act.res_id])
                if str(act.note or "") != note:
                    act.note = note
            else:
                act.action_feedback(feedback="Qoldiq tiklandi yoki eslatma o'chirildi.")
        for tmpl_id, r in low.items():
            for user in users:
                if (tmpl_id, user.id) in have or (tmpl_id, user.id) in litey_have:
                    continue
                r["product"].product_tmpl_id.sudo().activity_schedule(
                    act_xmlid, user_id=user.id, summary="%s: %s minimal qoldiqdan kam" % (label, r["product"].name),
                    note=self._craf_min_qty_note(r))

    @api.model
    def _craf_min_qty_note(self, r):
        uom = r.get("uom") or "kg"
        text = "Qoldiq: %s %s, minimal: %s %s." % (fmt(r["qty"], 1), uom, fmt(r["min_qty"], 1), uom)
        if r["days_left"] is not None:
            text += " O'rtacha sarf bilan ~%s kunga yetadi." % fmt(r["days_left"], 1)
        return "<p>%s</p>" % text

    def _craf_norm_notify(self, bolim_code, act_xmlid, summary):
        """Normadan past hujjat: chatterga yozuv va bo'lim mas'ullariga eslatma (tasdiqlagan odamdan tashqari).
        Modelda norm_status va norm_warning maydonlari, mail.activity.mixin bo'lishi kerak."""
        self.ensure_one()
        if self.norm_status != "low":
            return
        self.message_post(body=Markup("<b>⚠ %s</b>") % self.norm_warning, subtype_xmlid="mail.mt_note")
        bolim = self.env["craf.bolim"]._get(bolim_code)
        if not bolim.notify_app:
            return
        for user in bolim._notify_users() - self.env.user:
            self.sudo().activity_schedule(act_xmlid, user_id=user.id, summary=summary,
                                          note=Markup("<p>%s: %s</p>") % (self.name, self.norm_warning))

    # ---------------------------------------------------------------- yordamchi
    @api.model
    def _craf_loc(self, name):
        if not name:
            return self.env["stock.location"]
        return self.env["stock.location"].search([
            ("name", "=", name), ("usage", "=", "internal"),
            ("company_id", "in", [self.env.company.id, False])], limit=1)

    @api.model
    def _craf_product(self, code):
        return self.env["product.product"].search([("default_code", "=", code)], limit=1)

    @api.model
    def _craf_default_equipment(self):
        if not self._craf_stage:
            return self.env["maintenance.equipment"]
        return self.env["maintenance.equipment"].search([("craf_stage", "=", self._craf_stage)], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if (not vals.get("name") or vals["name"] == "Yangi") and self._craf_sequence_code:
                vals["name"] = self.env["ir.sequence"].next_by_code(self._craf_sequence_code) or "Yangi"
        return super().create(vals_list)

    def _compute_production_count(self):
        for rec in self:
            rec.production_count = len(rec.production_ids)

    def _compute_pack_count(self):
        Pack = self.env["craf.pack"]
        for rec in self:
            rec.pack_count = Pack.search_count([("origin", "=", rec.name)]) if rec.name else 0

    def _compute_has_pack_items(self):
        for rec in self:
            rec.has_pack_items = rec.state == "done" and bool(rec._craf_pack_items())

    def _craf_check_available(self, location, needs):
        """needs: {product: qty (mahsulot birligida)} — yetmasa aniq xabar bilan to'xtatadi."""
        Quant = self.env["stock.quant"]
        missing = []
        for product, qty in needs.items():
            if qty <= EPS or not product.is_storable:
                continue
            available = Quant._get_available_quantity(product, location)
            if qty - available > EPS:
                missing.append("• %s: kerak %s, bor %s %s" % (
                    product.display_name, fmt(qty, 2 if qty % 1 else 0),
                    fmt(available, 2 if available % 1 else 0), product.uom_id.name))
        if missing:
            raise UserError("%s da qoldiq yetarli emas:\n%s\n\nAvval xaritadan ko'chirib keling." % (
                location.display_name, "\n".join(missing)))

    def _craf_produce(self, product, qty, src, dest, components, byproducts=None):
        """Bitta MRP buyurtmasini yaratib darhol bajaradi.

        components: [(product, qty)] — src dan sarflanadi
        byproducts: [(product, qty, location)] — qo'shimcha chiqish (chiqindi, шлак)
        """
        self.ensure_one()
        if qty <= EPS:
            raise UserError("%s: chiqish miqdori 0." % product.display_name)
        production_loc = product.with_company(self.company_id).property_stock_production
        merged = defaultdict(float)
        for comp, comp_qty in components:
            if comp_qty > EPS:
                merged[comp] += comp_qty
        mo = self.env["mrp.production"].create({
            "product_id": product.id,
            "product_qty": qty,
            "product_uom_id": product.uom_id.id,
            "bom_id": False,  # haqiqiy sarf hujjatdan olinadi, BoM faqat namuna
            "location_src_id": src.id,
            "location_dest_id": dest.id,
            "origin": self.name,
            "company_id": self.company_id.id,
            "move_raw_ids": [Command.create({
                "product_id": comp.id,
                "product_uom_qty": comp_qty,
                "product_uom": comp.uom_id.id,
                "location_id": src.id,
                "location_dest_id": production_loc.id,
            }) for comp, comp_qty in merged.items()],
        })
        extra = [(p, q, loc) for p, q, loc in (byproducts or []) if q > EPS]
        if extra:
            mo.write({"move_byproduct_ids": [Command.create({
                "product_id": p.id,
                "product_uom_qty": q,
                "product_uom": p.uom_id.id,
                "location_dest_id": loc.id,
            }) for p, q, loc in extra]})
        mo.action_confirm()
        mo.qty_producing = qty
        for move in mo.move_raw_ids | mo.move_byproduct_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        mo.with_context(skip_redirection=True, skip_consumption=True).button_mark_done()
        if mo.state != "done":
            raise UserError("Ishlab chiqarish buyurtmasi %s bajarilmadi (holati: %s)." % (mo.name, mo.state))
        self.production_ids = [Command.link(mo.id)]
        return mo

    def _craf_post_summary(self, lines):
        self.message_post(body=Markup("<br/>").join(lines))

    # ---------------------------------------------------------------- tugmalar
    def _craf_action_done(self):
        """Har bir hujjat turi o'zi yozadi."""
        raise NotImplementedError

    def action_done(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError("%s allaqachon %s." % (rec.name, dict(STATES)[rec.state].lower()))
            rec._craf_action_done()
            rec.state = "done"
        return True

    def action_cancel(self):
        if any(rec.state == "done" for rec in self):
            raise UserError("Bajarilgan hujjatni bekor qilib bo'lmaydi: ombor harakatlari allaqachon yozilgan.")
        self.state = "cancel"

    def action_draft(self):
        self.filtered(lambda r: r.state == "cancel").state = "draft"

    def unlink(self):
        if any(rec.state == "done" for rec in self):
            raise UserError("Bajarilgan hujjatni o'chirib bo'lmaydi.")
        return super().unlink()

    def action_view_productions(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("mrp.mrp_production_action")
        action["domain"] = [("id", "in", self.production_ids.ids)]
        action["context"] = {"create": False}
        if len(self.production_ids) == 1:
            action.update({"view_mode": "form", "views": [(False, "form")], "res_id": self.production_ids.id})
        return action

    def action_view_packs(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("craf_label.action_craf_pack")
        action["domain"] = [("origin", "=", self.name)]
        action["context"] = {"create": False}
        return action

    def _craf_pack_items(self):
        """[(product, pcs, location)] — pachkalanadigan chiqishlar. Hujjat turi o'zi beradi."""
        return []

    def action_make_packs(self):
        self.ensure_one()
        if self.state != "done":
            raise UserError("Pachka yorliqlari hujjat tasdiqlangandan keyin chiqariladi.")
        Pack = self.env["craf.pack"]
        packs = Pack.search([("origin", "=", self.name)])
        if not packs:
            vals = []
            for product, pcs, location in self._craf_pack_items():
                for part in Pack._craf_split(product, pcs):
                    vals.append({"product_id": product.id, "pcs": part, "location_id": location.id,
                                 "origin": self.name})
            if not vals:
                raise UserError("Pachkalanadigan mahsulot yo'q.")
            packs = Pack.create(vals)
            self.message_post(body="%s ta pachka yaratildi: %s … %s" % (len(packs), packs[-1].name, packs[0].name))
        return packs.sorted("id").action_print()
