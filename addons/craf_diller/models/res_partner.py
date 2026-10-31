import re
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


def norm_phone(value):
    """«+998 90 123-45-67» yoki «90 123 45 67» -> «998901234567»."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 9:
        digits = "998" + digits
    return digits


class ResPartner(models.Model):
    _inherit = "res.partner"

    craf_is_diller = fields.Boolean("Diller", index=True, copy=False,
                                    help="Kompaniya diller portaliga kira oladi.")
    craf_diller_blocked = fields.Boolean("Bloklangan", copy=False,
                                         help="Loginlar portalga kira olmaydi, yangi buyurtma berib bo'lmaydi.")
    craf_credit_limit = fields.Float("Qarz chegarasi", digits=(16, 0),
                                     help="0 — chegara yo'q. Oshsa buyurtma bloklanmaydi, «Tasdiq kutilmoqda (qarz)» "
                                          "holatiga tushadi.")
    craf_auto_confirm = fields.Boolean("Avto-tasdiq",
                                       help="Ishonchli diller: qarz chegarasidan oshmagan buyurtma sotuvchisiz "
                                            "yuklovchi navbatiga tushadi.")
    craf_telegram_id = fields.Char("Telegram ID", copy=False)
    craf_telegram_token = fields.Char("Telegram ulash kaliti", copy=False, groups="base.group_system")
    craf_favorite_ids = fields.Many2many("product.product", "craf_diller_favorite_rel", "partner_id", "product_id",
                                         string="Sevimlilar")
    craf_diller_login = fields.Char("Login", compute="_compute_craf_diller_stats")
    craf_last_order = fields.Datetime("Oxirgi buyurtma", compute="_compute_craf_last_order", store=True)
    craf_sale_30 = fields.Float("30 kunlik sotuv", digits=(16, 0), compute="_compute_craf_diller_stats")
    craf_debt = fields.Float("Joriy qarz", digits=(16, 0), compute="_compute_craf_diller_stats")

    @api.depends("sale_order_ids.state", "sale_order_ids.date_order")
    def _compute_craf_last_order(self):
        for partner in self:
            dates = partner.sale_order_ids.filtered(lambda o: o.state == "sale").mapped("date_order")
            partner.craf_last_order = max(dates) if dates else False

    def _compute_craf_diller_stats(self):
        debts = self.env["craf.sotuv"].sudo()._craf_debt(set(self._origin.ids))
        since = fields.Datetime.now() - timedelta(days=30)
        rows = self.env["sale.order"].sudo()._read_group(
            [("partner_id", "in", self._origin.ids), ("state", "=", "sale"), ("date_order", ">=", since)],
            ["partner_id"], ["amount_total:sum"])
        sums = {p.id: total for p, total in rows}
        for partner in self:
            partner.craf_debt = debts.get(partner._origin.id, 0.0)
            partner.craf_sale_30 = sums.get(partner._origin.id, 0.0)
            partner.craf_diller_login = partner._origin._craf_diller_user().login if partner._origin else False

    def _craf_diller_user(self):
        """Dillerning yagona portal logini."""
        self.ensure_one()
        return self.env["res.users"].sudo().with_context(active_test=False).search(
            [("partner_id", "child_of", self.id), ("share", "=", True)], limit=1)

    def _craf_exposure(self, exclude=None):
        """Joriy qarz + tasdiqlangan, hali berilmagan buyurtmalar + javob kutayotgan diller buyurtmalari."""
        self.ensure_one()
        partner = self.commercial_partner_id
        total = self.env["craf.sotuv"].sudo()._craf_debt({partner.id}).get(partner.id, 0.0)
        Order = self.env["sale.order"].sudo()
        waiting = Order.search([("partner_id", "=", partner.id), ("state", "=", "draft"), ("craf_portal", "=", True),
                                ("craf_approval", "in", ("submitted", "credit"))])
        confirmed = Order.search([("partner_id", "=", partner.id), ("state", "=", "sale"),
                                  ("craf_load_state", "in", ("queue", "loading"))])
        if exclude:
            waiting -= exclude
            confirmed -= exclude
        total += sum(waiting.mapped("amount_total"))
        for line in confirmed.order_line.filtered(lambda l: not l.display_type):
            total += max(line.product_uom_qty - line.qty_delivered, 0.0) * line.price_unit
        return total

    def _craf_diller_add_login(self, name, phone):
        """Dillerning yagona logini: kontakt + foydalanuvchi; qaytaradi (foydalanuvchi, taklif havolasi)."""
        self.ensure_one()
        dealer = self.commercial_partner_id
        name = (name or "").strip()
        phone = norm_phone(phone)
        if not name:
            raise UserError("Ism yozilmagan.")
        if len(phone) != 12 or not phone.startswith("998"):
            raise UserError("Telefon raqamini to'liq yozing: +998 90 123 45 67.")
        if dealer._craf_diller_user():
            raise UserError("%s da login bor: har dillerga bitta login." % dealer.name)
        Users = self.env["res.users"].sudo().with_context(active_test=False)
        if Users.search_count([("login", "=", phone)]):
            raise UserError("%s raqami bilan login allaqachon bor." % phone)
        contact = self.sudo().create({"name": name, "parent_id": dealer.id, "phone": "+" + phone, "type": "contact"})
        user = Users.with_context(no_reset_password=True).create({
            "name": name, "login": phone, "partner_id": contact.id,
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        return user, user._craf_invite_url()

    def action_craf_login_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": "Yangi login", "res_model": "craf.diller.login.wizard",
            "view_mode": "form", "target": "new", "context": {"default_partner_id": self.id},
        }

    def action_craf_login_link(self):
        """Yangi taklif havolasi (parol unutilganda ham)."""
        self.ensure_one()
        user = self._craf_diller_user()
        if not user:
            raise UserError("Bu dillerning logini yo'q.")
        wizard = self.env["craf.diller.login.wizard"].create({
            "partner_id": self.id, "name": user.name, "done": True, "url": user._craf_invite_url()})
        return {"type": "ir.actions.act_window", "name": "Taklif havolasi", "res_model": wizard._name,
                "res_id": wizard.id, "view_mode": "form", "target": "new"}
