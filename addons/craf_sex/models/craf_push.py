"""Ishlab chiqarish zanjiri bo'yicha telefonga bildirishnoma (veb-push) — keyingi bosqich xodimlariga:

Liteyka quyma → Press xodimlari, Press smenasi (korzinkalar) → Kimyo xodimlari,
Kimyoviy ishlov → Bo'yash xodimlari, Kunlik bo'yash (omborga) → Sotuvchilar va omborchilar.
Bildirishnoma bosilganda xodimning bosh sahifasi ochiladi. Tasdiqlagan odamning o'ziga bormaydi.
"""
from odoo import models


def _num(value, digits=0):
    text = "{:,.{d}f}".format(float(value or 0), d=digits)
    return text.replace(",", " ").replace(".", ",")


def _short(items, top=4):
    items = [i for i in items if i]
    text = ", ".join(items[:top])
    return text + (" +%s ta" % (len(items) - top) if len(items) > top else "")


class ResUsers(models.Model):
    _inherit = "res.users"

    def _craf_push_home(self):
        """Shaxsiy ilovali xodim (kimyo, bo'yash, matritsa) — o'z sahifasi."""
        self.ensure_one()
        own = self._craf_own_app()
        action = own and self._craf_own_apps().get(own, {}).get("action")
        return "action-%s" % action if action else super()._craf_push_home()


class CrafPushMixin(models.AbstractModel):
    _name = "craf.push.mixin"
    _description = "Craf: zanjir bo'yicha bildirishnoma"

    def _craf_push_users(self, stages=(), groups=()):
        Users = self.env["res.users"].sudo()
        users = Users.search([("craf_work_stage", "in", list(stages)), ("share", "=", False)]) if stages else Users
        for xmlid in groups:
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if group:
                users |= group.sudo().all_user_ids.filtered(lambda u: not u.share and u.active)
        return users - self.env.user

    def _craf_push_send(self, users, title, body, tag):
        for user in users:
            user._craf_web_push(title, body, tag=tag, model=user._craf_push_home())


class CrafFoundryMelt(models.Model):
    _name = "craf.foundry.melt"
    _inherit = ["craf.foundry.melt", "craf.push.mixin"]

    def action_done(self):
        res = super().action_done()
        for rec in self.filtered(lambda r: r.state == "done" and r.billet_qty):
            rec._craf_push_send(rec._craf_push_users(stages=["press"]), "Liteyka: yangi quyma",
                                "%s — %s kg quyma Pressga tayyor" % (rec.name, _num(rec.billet_qty)),
                                "craf-melt-%s" % rec.id)
        return res


class CrafExtrusionShift(models.Model):
    _name = "craf.extrusion.shift"
    _inherit = ["craf.extrusion.shift", "craf.push.mixin"]

    def action_done(self):
        res = super().action_done()
        for rec in self.filtered(lambda r: r.state == "done"):
            loads = rec.basket_load_ids
            if not loads:
                continue
            rec._craf_push_send(
                rec._craf_push_users(stages=["kimyo"]), "Press: %s korzinka kimyoga" % len(loads),
                "%s — %s" % (rec.name, _short(loads.mapped("display_name"))), "craf-shift-%s" % rec.id)
        return res


class CrafChemTreatment(models.Model):
    _name = "craf.chem.treatment"
    _inherit = ["craf.chem.treatment", "craf.push.mixin"]

    def action_done(self):
        res = super().action_done()
        for rec in self.filtered(lambda r: r.state == "done" and r.pcs_total):
            rec._craf_push_send(
                rec._craf_push_users(stages=["boyash"]), "Kimyodan chiqdi — bo'yashga tayyor",
                "%s — %s korzinka, %s dona, %s kg" % (rec.name, rec.basket_count, _num(rec.pcs_total),
                                                     _num(rec.kg_total)), "craf-chem-%s" % rec.id)
        return res


class CrafPaintDay(models.Model):
    _name = "craf.paint.day"
    _inherit = ["craf.paint.day", "craf.push.mixin"]

    def action_confirm(self):
        res = super().action_confirm()
        for rec in self.filtered(lambda r: r.state == "done"):
            lines = rec.line_ids.filtered(lambda l: l.pcs > 0 and l.product_id)
            items = ["%s %s pachka" % (l.product_id.name, l.packs) if l.packs else
                     "%s %s dona" % (l.product_id.name, l.pcs) for l in lines]
            rec._craf_push_send(
                rec._craf_push_users(groups=["craf_sotuv.group_craf_seller", "stock.group_stock_manager"]),
                "Omborga keldi: %s pachka" % _num(rec.packs_total),
                "%s — %s" % (rec.name, _short(items)), "craf-paintday-%s" % rec.id)
        return res
