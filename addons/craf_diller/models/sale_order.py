from odoo import fields, models
from odoo.exceptions import AccessError, UserError

APPROVALS = [
    ("submitted", "Yuborildi"),
    ("credit", "Tasdiq kutilmoqda (qarz)"),
    ("approved", "Zavod tasdiqladi"),
    ("rejected", "Rad etildi"),
]


def money(value):
    return "{:,.0f}".format(value or 0.0).replace(",", " ")


class SaleOrder(models.Model):
    _inherit = "sale.order"

    craf_portal = fields.Boolean("Diller portalidan", copy=False, index=True, readonly=True)
    craf_approval = fields.Selection(APPROVALS, "Diller buyurtmasi", copy=False, index=True, tracking=True,
                                     readonly=True)
    craf_diller_user_id = fields.Many2one("res.users", "Buyurtma bergan", copy=False, readonly=True)
    craf_need_date = fields.Date("Kerakli sana", copy=False)
    craf_approved_date = fields.Datetime("Tasdiqlangan vaqt", copy=False, readonly=True)
    craf_approved_by = fields.Many2one("res.users", "Tasdiqladi", copy=False, readonly=True)
    craf_reject_note = fields.Char("Rad etish sababi", copy=False)
    craf_credit_note = fields.Char("Qarz holati", copy=False, readonly=True)
    craf_change_request = fields.Char("Diller o'zgartirish so'rovi", copy=False, tracking=True)

    # ------------------------------------------------------------------ holat
    def _craf_diller_status(self):
        """(kod, nomi) — dillerga ko'rinadigan holat."""
        self.ensure_one()
        if self.state == "cancel":
            if self.craf_approval == "rejected":
                return "rejected", "Rad etildi"
            return "cancel", "Bekor qilindi"
        if self.state in ("draft", "sent"):
            if self.craf_approval == "credit":
                return "credit", "Tasdiq kutilmoqda (qarz)"
            return "submitted", "Yuborildi"
        if self.craf_load_state == "done" or self.delivery_status == "full":
            return "done", "Berildi"
        if self.craf_load_state == "loading":
            return "loading", "Yuklanmoqda"
        if self.delivery_status == "partial":
            return "partial", "Qisman berildi"
        if self.craf_load_state == "queue":
            return "queue", "Qabul kutilmoqda"
        return "approved", "Zavod tasdiqladi"

    # ------------------------------------------------------------------ zavod tomoni
    def _craf_check_approver(self):
        self.ensure_one()
        user = self.env.user
        if not user.has_group("craf_sotuv.group_craf_seller"):
            raise AccessError("Bu amal faqat sotuvchi uchun.")
        if self.craf_approval == "credit" and not user.has_group("craf_diller.group_craf_diller_manager"):
            raise UserError("%s qarz chegarasidan oshgan — buni diller menejeri tasdiqlaydi." % self.name)

    def action_craf_approve(self):
        """Tasdiq: buyurtma tasdiqlanadi, mahsulot band qilinadi va yuklovchi navbatiga tushadi."""
        for order in self.filtered(lambda o: o.state in ("draft", "sent") and o.craf_portal):
            order._craf_check_approver()
            if not order.order_line.filtered(lambda l: not l.display_type and l.product_uom_qty > 0):
                raise UserError("%s: mahsulot qatori yo'q." % order.name)
            order._craf_approve()
        return True

    def _craf_approve(self, auto=False):
        self.ensure_one()
        self.write({"craf_approval": "approved", "craf_approved_date": fields.Datetime.now(),
                    "craf_approved_by": False if auto else self.env.user.id})
        self.action_confirm()
        self._craf_push("Zavod tasdiqladi", "%s tasdiqlandi va yuklash navbatida." % self.name)

    def action_craf_reject(self):
        for order in self.filtered(lambda o: o.state in ("draft", "sent") and o.craf_portal):
            order._craf_check_approver()
            order.write({"craf_approval": "rejected"})
            order.with_context(craf_no_push=True).action_cancel()
            order._craf_push("Buyurtma rad etildi", "%s rad etildi%s." % (
                order.name, ": %s" % order.craf_reject_note if order.craf_reject_note else ""))
        return True

    def _craf_seller_notify(self, title, message):
        """Odoo ichidagi xabar: dillerning mas'ul menejeri, u bo'lmasa barcha sotuvchilar."""
        group = self.env.ref("craf_sotuv.group_craf_seller")
        users = self.partner_id.commercial_partner_id.user_id or group.sudo().all_user_ids.filtered(
            lambda u: not u.share)
        for user in users.sudo():
            user._bus_send("simple_notification", {"title": title, "message": message, "type": "warning",
                                                   "sticky": True})

    # ------------------------------------------------------------------ bildirishnoma
    def _craf_push(self, title, body, photos=None):
        self.ensure_one()
        dealer = self.partner_id.commercial_partner_id
        if dealer.craf_is_diller:
            self.env["craf.diller.notice"].sudo()._craf_push(dealer, title, body, order=self, photos=photos)

    def write(self, vals):
        before = {o.id: o.craf_load_state for o in self} if "craf_load_state" in vals else {}
        res = super().write(vals)
        for order in self.filtered(lambda o: o.id in before and o.craf_load_state != before[o.id]):
            order._craf_load_pushed(before[order.id], bool(vals.get("craf_given_date")))
        return res

    def _craf_load_pushed(self, old, given):
        truck = ", mashina %s" % self.craf_truck if self.craf_truck else ""
        if self.craf_load_state == "loading":
            self._craf_push("Yuklanmoqda", "%s yuklanmoqda." % self.name)
        elif self.craf_load_state == "done":
            self._craf_push("Berildi", "%s berildi%s." % (self.name, truck), photos=self.sudo().craf_trip_photo_ids)
        elif self.craf_load_state == "queue" and old == "loading" and given:
            self._craf_push("Qisman berildi", "%s qisman berildi%s, qolgani navbatda." % (self.name, truck),
                            photos=self.sudo().craf_trip_photo_ids)

    def _action_cancel(self):
        open_orders = self.filtered(lambda o: o.state != "cancel")
        res = super()._action_cancel()
        if not self.env.context.get("craf_no_push"):
            for order in open_orders:
                order._craf_push("Buyurtma bekor qilindi", "%s bekor qilindi." % order.name)
        return res

    # ------------------------------------------------------------------ diller: yuborish
    def _craf_credit_review(self):
        """Qarz chegarasidan oshsa — True va izoh yoziladi."""
        self.ensure_one()
        dealer = self.partner_id.commercial_partner_id
        limit = dealer.craf_credit_limit
        total = dealer._craf_exposure(exclude=self) + self.amount_total
        if limit <= 0 or total <= limit:
            self.craf_credit_note = False
            return False
        self.craf_credit_note = "Qarz + buyurtmalar %s > chegara %s" % (money(total), money(limit))
        return True

    def _craf_after_submit(self, is_new=True):
        """Yangi yoki o'zgartirilgan diller buyurtmasi: qarz tekshiruvi, avto-tasdiq yoki sotuvchiga xabar."""
        self.ensure_one()
        dealer = self.partner_id.commercial_partner_id
        over = self._craf_credit_review()
        self.craf_approval = "credit" if over else "submitted"
        if dealer.craf_auto_confirm and not over:
            self._craf_approve(auto=True)
            return
        self._craf_seller_notify(
            "Yangi diller buyurtmasi" if is_new else "Diller buyurtmani o'zgartirdi",
            "%s · %s · %s pachka%s" % (self.name, dealer.name, self.craf_total_packs, " · QARZ" if over else ""))


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    craf_diller_qty = fields.Float("Diller so'ragan", digits=(16, 0), copy=False, readonly=True,
                                   help="Diller yuborgan miqdor. Sotuvchi o'zgartirsa diller farqni ko'radi.")
