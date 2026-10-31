import hashlib
import secrets
from datetime import timedelta

from odoo import fields, models

INVITE_DAYS = 7


def invite_hash(token):
    return hashlib.sha256((token or "").encode()).hexdigest()


class ResUsers(models.Model):
    _inherit = "res.users"

    craf_invite_hash = fields.Char("Taklif kaliti", copy=False, groups="base.group_system", index=True)
    craf_invite_expiry = fields.Datetime("Taklif muddati", copy=False, groups="base.group_system")
    craf_notice_seen_id = fields.Integer("Ko'rilgan oxirgi xabar", copy=False, default=0)

    def _craf_invite_url(self):
        """Yangi taklif havolasi (oldingisi bekor bo'ladi). Kalit bazada faqat xesh ko'rinishida turadi."""
        self.ensure_one()
        token = secrets.token_urlsafe(24)
        self.sudo().write({"craf_invite_hash": invite_hash(token),
                           "craf_invite_expiry": fields.Datetime.now() + timedelta(days=INVITE_DAYS)})
        return "%s/diller/taklif/%s" % (self.get_base_url(), token)

    def _craf_invite_user(self, token):
        """Kalit bo'yicha foydalanuvchi; yaroqsiz yoki muddati o'tgan bo'lsa — bo'sh."""
        if not token:
            return self.browse()
        user = self.sudo().with_context(active_test=False).search(
            [("craf_invite_hash", "=", invite_hash(token))], limit=1)
        if not user or not user.active or not user.craf_invite_expiry \
                or user.craf_invite_expiry < fields.Datetime.now():
            return self.browse()
        return user
