import re
from collections import defaultdict

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

from .sale_order_line import packs_text

C1_STATES = [("new", "1C ga kiritilmagan"), ("done", "1C ga kiritildi")]
LOAD_STATES = [
    ("draft", "Qoralama"),
    ("queue", "Qabul kutilmoqda"),
    ("loading", "Yuklanmoqda"),
    ("done", "Berildi"),
    ("cancel", "Bekor"),
]


class SaleOrder(models.Model):
    _inherit = "sale.order"

    craf_location_id = fields.Many2one(
        "stock.location", "Qayerdan", domain=[("usage", "=", "internal")], tracking=True,
        default=lambda self: self.env.company.craf_sale_location_id,
        help="Mahsulot shu joydan beriladi (Zavod = Tayyor mahsulot ombori, Parnik, Rohat).")
    craf_given_date = fields.Datetime("Berilgan vaqt", copy=False, index=True, tracking=True,
                                      help="Mahsulot mijozga berilgan (ombordan chiqqan) vaqt.")
    craf_source_key = fields.Char("Matn kaliti", copy=False, index=True, readonly=True)
    craf_source_text = fields.Text("Sotuvchi yozgan matn", copy=False)
    craf_total_pcs = fields.Float("Jami dona", digits=(16, 0), compute="_compute_craf_totals", store=True)
    craf_total_packs = fields.Integer("Jami pachka", compute="_compute_craf_totals", store=True)
    craf_total_kg = fields.Float("Jami kg", digits=(16, 1), compute="_compute_craf_totals", store=True)
    c1_state = fields.Selection(C1_STATES, string="1C", default="new", required=True, copy=False, index=True,
                                tracking=True)
    c1_date = fields.Datetime("1C ga kiritilgan vaqt", readonly=True, copy=False)
    c1_user_id = fields.Many2one("res.users", "1C ga kiritgan", readonly=True, copy=False)
    craf_load_state = fields.Selection(LOAD_STATES, string="Yuklash", default="draft", required=True, copy=False,
                                       index=True, tracking=True)
    craf_loader_id = fields.Many2one("res.users", "Yuklovchi", copy=False, tracking=True)
    craf_load_start = fields.Datetime("Yuklash boshlandi", copy=False)
    craf_sent_date = fields.Datetime("Yuklashga yuborilgan", copy=False, index=True)
    craf_load_note = fields.Char("Yuklovchiga izoh", help="Vaqt va boshqa eslatma — yuklovchi ko'radi.")
    craf_truck = fields.Char("Mashina raqami", tracking=True, copy=False, index=True,
                             help="Mahsulot yuklangan mashina. Sotuvchi yoki yuklovchi yozadi; «Berildi» uchun kerak.")
    craf_truck_photo_ids = fields.Many2many(
        "ir.attachment", "craf_sale_order_truck_photo_rel", "order_id", "attachment_id",
        string="Mashina rasmlari", copy=False, help="Yuklovchi yuklab bo'lgach olgan rasmlar (har bir berishda).")
    craf_trip_photo_ids = fields.Many2many(
        "ir.attachment", "craf_sale_order_trip_photo_rel", "order_id", "attachment_id",
        string="Shu yuklash rasmlari", copy=False, help="Hali «Berildi» bosilmagan yuklashning rasmlari.")

    @api.model
    def _craf_norm_truck(self, value):
        """«01 a 777 aa » -> «01 A 777 AA»."""
        return re.sub(r"\s+", " ", (value or "").strip()).upper()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("craf_truck"):
                vals["craf_truck"] = self._craf_norm_truck(vals["craf_truck"])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("craf_truck"):
            vals["craf_truck"] = self._craf_norm_truck(vals["craf_truck"])
        return super().write(vals)

    def _craf_require_truck(self):
        if not (self.craf_truck or "").strip():
            raise UserError("%s: mashina raqamini yozing." % self.name)

    def _craf_require_photo(self):
        if not self.sudo().craf_trip_photo_ids:
            raise UserError("%s: yuklangan mashina rasmini oling." % self.name)

    @api.depends("order_line.product_uom_qty", "order_line.craf_kg", "order_line.craf_packs")
    def _compute_craf_totals(self):
        for order in self:
            lines = order.order_line.filtered(lambda l: not l.display_type and l.product_id.is_storable)
            order.craf_total_pcs = sum(lines.mapped("product_uom_qty"))
            order.craf_total_packs = sum(lines.mapped("craf_packs"))
            order.craf_total_kg = sum(lines.mapped("craf_kg"))

    # ------------------------------------------------------------------ Berildi
    def action_craf_berildi(self):
        """Tasdiqlash + yetkazib berishni darhol bajarish (mahsulot ombordan mijozga chiqadi)."""
        for order in self:
            order._craf_berildi()
        return True

    # ------------------------------------------------------------------ yuklash navbati
    def action_confirm(self):
        res = super().action_confirm()
        if not self.env.context.get("craf_no_queue"):
            self.filtered(lambda o: o.craf_load_state == "draft")._craf_to_queue()
        return res

    def _action_cancel(self):
        res = super()._action_cancel()
        cancelled = self.filtered(lambda o: o.craf_load_state in ("queue", "loading"))
        if cancelled:
            cancelled.write({"craf_load_state": "cancel"})
            cancelled._craf_notify("cancel", "Buyurtma bekor qilindi", ", ".join(
                "%s · %s" % (o.name, o.partner_id.name) for o in cancelled))
        return res

    def _craf_open_pickings(self):
        return self.picking_ids.filtered(lambda p: p.state not in ("done", "cancel")
                                         and p.picking_type_code == "outgoing")

    def _craf_to_queue(self):
        """Tasdiqlangan buyurtma yuklovchilar navbatiga tushadi (mahsulot joyda band qilinadi)."""
        for order in self:
            pickings = order._craf_open_pickings()
            if not pickings:
                continue
            if not order.craf_location_id:
                order.craf_location_id = order.company_id.craf_sale_location_id
            order._craf_fix_source(pickings)
            pickings.action_assign()
            order.write({"craf_load_state": "queue", "craf_sent_date": fields.Datetime.now()})
            order._craf_notify(
                "new", "Yangi buyurtma — yuklash",
                "%s · %s · %s pachka (%s)" % (order.name, order.partner_id.name, order.craf_total_packs,
                                             order.craf_location_id._craf_sale_label()),
                to_loaders=True)

    def action_craf_send(self):
        """Formadagi tugma: tasdiqlash va yuklashga yuborish."""
        for order in self:
            if order.state in ("draft", "sent"):
                order.action_confirm()
            elif order.craf_load_state in ("draft", "cancel"):
                order._craf_to_queue()
        return True

    def _craf_notify(self, kind, title, message, users=None, to_loaders=False, ntype="info"):
        """Bus: sahifalar yangilanadi; kerakli foydalanuvchilarga qisqa xabar."""
        group = self.env.ref("craf_sotuv.group_craf_loader", raise_if_not_found=False)
        everyone = group.sudo().all_user_ids.filtered(lambda u: not u.share) if group else self.env["res.users"]
        targets = users if users is not None else (everyone if to_loaders else self.env["res.users"])
        for user in (targets - self.env.user):
            user._bus_send("simple_notification", {"title": title, "message": message, "type": ntype,
                                                   "sticky": False})
        if everyone:
            everyone._bus_send("craf_sotuv_update", {"kind": kind, "order_ids": self.ids})

    def _craf_check_onhand(self, moves):
        """Yuklangan miqdor joydagi qoldiqdan oshmasin (manfiy qoldiqqa ruxsat bo'lmasa)."""
        if self.company_id.craf_sale_allow_negative:
            return
        need = {}
        for move in moves.filtered(lambda m: m.product_id.is_storable):
            qty = move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
            key = (move.product_id, move.location_id)
            need[key] = need.get(key, 0.0) + qty
        short = []
        for (product, loc), qty in need.items():
            have = product.with_context(location=loc.id).qty_available
            if product.uom_id.compare(qty, have) > 0:
                per = product.craf_pcs_per_pack
                short.append("• %s — yuklandi %s, omborda %s" % (
                    product.display_name, packs_text(qty, per), packs_text(max(have, 0), per)))
        if short:
            raise UserError("«%s» da qoldiq yetmaydi:\n%s\n\nQoldiqni tekshiring yoki miqdorni to'g'rilang." % (
                self.craf_location_id._craf_sale_label(), "\n".join(short)))

    def _craf_allocs(self, moves):
        """{move: {location: qty}} — yuklovchi rejasi (faqat musbat)."""
        plan = defaultdict(lambda: defaultdict(float))
        for a in self.env["craf.load.alloc"].sudo().search([("move_id", "in", moves.ids), ("qty", ">", 0)]):
            plan[a.move_id][a.location_id] += a.qty
        return plan

    def _craf_check_plan(self, plan):
        """Har joydagi qoldiq yuklangan miqdorga yetadimi (manfiy qoldiqqa ruxsat bo'lmasa)."""
        if self.company_id.craf_sale_allow_negative:
            return
        need = defaultdict(float)
        for move, amap in plan.items():
            for loc, qty in amap.items():
                need[(move.product_id, loc)] += qty
        short = []
        for (product, loc), qty in need.items():
            if not product.is_storable:
                continue
            have = product.with_context(location=loc.id).qty_available
            if product.uom_id.compare(qty, have) > 0:
                per = product.craf_pcs_per_pack
                short.append("• %s — %s: yuklandi %s, omborda %s" % (
                    product.display_name, loc._craf_sale_label(), packs_text(qty, per), packs_text(max(have, 0), per)))
        if short:
            raise UserError("Qoldiq yetmaydi:\n%s\n\nJoyni yoki miqdorni to'g'rilang." % "\n".join(short))

    def _craf_load_done(self, rest="backorder"):
        """Yuklovchi: yuklanganlari beriladi (har joydan o'z miqdori).
        rest = backorder (qolgani navbatda qoladi) | cancel (qolgani bekor)."""
        self.ensure_one()
        self._craf_require_truck()
        self._craf_require_photo()
        pickings = self._craf_open_pickings()
        if not pickings:
            raise UserError("%s: yuklanadigan narsa qolmagan." % self.name)
        moves = pickings.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        plan = self._craf_allocs(moves)
        if not plan:
            raise UserError("Hech narsa yuklanmagan — qatorlarni «Yuklandi» deb belgilang.")
        self._craf_check_plan(plan)
        Move = self.env["stock.move"]
        loaded = Move
        for move in moves:
            amap = plan.get(move)
            if not amap:
                if move.picked:
                    move.picked = False
                continue
            primary = move.location_id
            q_primary = amap.get(primary, 0.0)
            others = [(loc, q) for loc, q in amap.items() if loc != primary and q > 0]
            total = q_primary + sum(q for _loc, q in others)
            if move.product_id.uom_id.compare(move.product_qty, total) < 0:
                # buyurtmadan ko'p yuklandi
                move.product_uom_qty = move.product_id.uom_id._compute_quantity(total, move.product_uom)
            for loc, q in others:
                vals = move.with_context(source_location_id=loc.id)._split(q)
                new = Move.create(vals)
                new._action_confirm(merge=False)
                if new.location_id != loc:
                    new.location_id = loc
                new.quantity = new.product_id.uom_id._compute_quantity(q, new.product_uom)
                new.picked = True
                loaded |= new
            if q_primary > 0:
                move.quantity = move.product_id.uom_id._compute_quantity(q_primary, move.product_uom)
                move.picked = True
                loaded |= move
            elif move.picked:
                move.picked = False
        ctx = {"skip_sms": True, "skip_backorder": True}
        if rest == "cancel":
            ctx["picking_ids_not_to_backorder"] = pickings.ids
        res = pickings.with_context(**ctx).button_validate()
        if isinstance(res, dict) or any(p.state != "done" for p in pickings):
            raise UserError("%s: yetkazib berishni bajarib bo'lmadi — %s ni oching." % (
                self.name, ", ".join(pickings.mapped("name"))))
        now = fields.Datetime.now()
        packs = self.env["craf.pack"].sudo().search([("load_move_id", "in", moves.ids)])
        for pack in packs:
            pack.write({"sale_line_id": pack.load_move_id.sale_line_id.id, "sold_date": now, "location_id": False})
        self.env["craf.load.alloc"].sudo().search([("move_id", "in", moves.ids)]).unlink()
        full = self.delivery_status == "full" or not self._craf_open_pickings()
        self.write({
            "craf_given_date": now,
            "craf_loader_id": self.env.user.id,
            "craf_load_state": "done" if full else "queue",
        })
        done_moves = loaded.filtered(lambda m: m.state == "done")
        photos = self.sudo().craf_trip_photo_ids
        self.message_post(body=Markup("<b>Berildi</b> (%s, mashina %s): %s%s") % (
            self.env.user.name, self.craf_truck,
            "; ".join("%s — %s %s" % (m.product_id.display_name, m.location_id._craf_sale_label(),
                                      packs_text(m.quantity, m.product_id.craf_pcs_per_pack)) for m in done_moves),
            "" if full else Markup(" — <i>qolgani navbatda</i>")), attachment_ids=photos.ids)
        self.sudo().craf_trip_photo_ids = [(5, 0, 0)]
        self._craf_notify(
            "done", "Berildi" if full else "Qisman berildi",
            "%s · %s · %s — %s" % (self.name, self.partner_id.name, self.craf_truck, self.env.user.name),
            users=self.user_id | self.create_uid, ntype="success" if full else "warning")
        return True

    def _craf_berildi(self):
        self.ensure_one()
        if self.state == "cancel":
            raise UserError("%s bekor qilingan." % self.name)
        self._craf_require_truck()
        if not self.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty > 0):
            raise UserError("%s: mahsulot qatori yo'q." % self.name)
        if not self.craf_location_id:
            self.craf_location_id = self.company_id.craf_sale_location_id
        given = self.craf_given_date or fields.Datetime.now()
        if self.state in ("draft", "sent"):
            self.with_context(craf_no_queue=True).action_confirm()
        if self.date_order != given:
            self.date_order = given
        pickings = self.picking_ids.filtered(lambda p: p.state not in ("done", "cancel")
                                             and p.picking_type_code == "outgoing")
        if not pickings:
            if self.delivery_status == "full":
                return True
            raise UserError("%s: yetkazib berish hujjati topilmadi." % self.name)
        self._craf_fix_source(pickings)
        pickings.action_assign()
        self._craf_check_reserved(pickings)
        for move in pickings.move_ids.filtered(lambda m: m.state not in ("done", "cancel")):
            move.quantity = move.product_uom_qty
            move.picked = True
        res = pickings.with_context(
            skip_sms=True, picking_ids_not_to_backorder=pickings.ids, cancel_backorder=True,
        ).button_validate()
        if isinstance(res, dict) or any(p.state != "done" for p in pickings):
            raise UserError("%s: yetkazib berishni avtomatik bajarib bo'lmadi — %s hujjatini oching." % (
                self.name, ", ".join(pickings.mapped("name"))))
        self.write({"craf_given_date": given, "craf_load_state": "done",
                    "craf_loader_id": self.craf_loader_id.id or self.env.user.id})
        self._craf_backdate(pickings, given)
        self._craf_notify("done", "Berildi", "%s · %s" % (self.name, self.partner_id.name))
        self.message_post(body=Markup("<b>Berildi</b> — %s, %s: %s") % (
            self.craf_location_id._craf_sale_label(), ", ".join(pickings.mapped("name")),
            "; ".join("%s %s" % (l.product_id.display_name, l.craf_packs_text)
                      for l in self.order_line if not l.display_type)))
        return True

    def _craf_fix_source(self, pickings):
        """Eski / qo'lda yaratilgan buyurtma: yetkazib berish manbasi sotuv joyiga to'g'rilanadi."""
        loc = self.craf_location_id
        for picking in pickings.filtered(lambda p: p.location_id != loc and p.state != "done"):
            picking.do_unreserve()
            picking.write({"location_id": loc.id})
            picking.move_ids.filtered(lambda m: m.state not in ("done", "cancel")).write({"location_id": loc.id})

    def _craf_check_reserved(self, pickings):
        if self.company_id.craf_sale_allow_negative:
            return
        short = []
        for move in pickings.move_ids.filtered(lambda m: m.state not in ("done", "cancel")
                                               and m.product_id.is_storable):
            need = move.product_uom_qty
            have = move.quantity
            if move.product_uom.compare(have, need) < 0:
                per = move.product_id.craf_pcs_per_pack
                short.append("• %s — kerak %s, bor %s" % (
                    move.product_id.display_name, packs_text(need, per), packs_text(have, per)))
        if short:
            raise UserError("%s: «%s» da qoldiq yetmaydi:\n%s\n\nQoldiqni tekshiring (Craf → Sotuv → Qoldiq) "
                            "yoki mahsulotni boshqa joydan ko'chiring." % (
                                self.partner_id.name, self.craf_location_id._craf_sale_label(), "\n".join(short)))

    def _craf_backdate(self, pickings, when):
        """Kechikib kiritilgan sotuv: ombor harakati berilgan vaqt bilan yoziladi (kunlik hisobot to'g'ri kun)."""
        if abs((fields.Datetime.now() - when).total_seconds()) < 15 * 60:
            return
        pickings.write({"date_done": when, "scheduled_date": when})
        moves = pickings.move_ids.filtered(lambda m: m.state == "done")
        moves.write({"date": when})
        moves.move_line_ids.write({"date": when})

    # ------------------------------------------------------------------ 1C
    def action_c1_done(self):
        self.filtered(lambda o: o.state == "sale").write({
            "c1_state": "done", "c1_date": fields.Datetime.now(), "c1_user_id": self.env.user.id})
        return True

    def action_c1_reset(self):
        self.write({"c1_state": "new", "c1_date": False, "c1_user_id": False})
        return True

    def action_craf_open_sotuv(self):
        return self.env["ir.actions.act_window"]._for_xml_id("craf_sotuv.action_craf_sotuv")


