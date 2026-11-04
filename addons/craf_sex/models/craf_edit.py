"""Xodim kiritgan ma'lumotni tahrirlash (2026-11-04 qarori).

Shaxsiy ilovali xodim (kimyo, matritsa, bo'yash) o'zi kiritgan yozuvni 24 soat ichida tahrirlaydi yoki o'chiradi;
omborchi, direktor va administrator — har doim. Har bir tahrir «Tahrirlash jurnali»ga yoziladi: kim, qachon, nima
o'zgardi (oldin → keyin); hujjatning o'z tarixida (chatter) ham ko'rinadi.

Tasdiqlangan hujjat tahriri bitta tranzaksiyada: eski ombor harakatlari teskari harakat bilan bekor qilinadi va
yangi qiymatlar bilan qayta tasdiqlanadi — biror tekshiruv o'tmasa, hech narsa o'zgarmaydi.
"""
from datetime import timedelta

from markupsafe import Markup

from odoo import fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt

EDIT_HOURS = 24
EDIT_SECTIONS = [("kimyo", "Kimyoviy ishlov"), ("matritsa", "Matritsa"), ("boyash", "Bo'yash va qadoqlash")]
EDIT_KINDS = [("edit", "Tahrirlandi"), ("cancel", "O'chirildi")]
MANAGER_GROUPS = ("craf_sex.group_craf_accountant", "craf_sex.group_craf_director", "base.group_system")


class CrafEditLog(models.Model):
    _name = "craf.edit.log"
    _description = "Tahrirlash jurnali"
    _order = "date desc, id desc"
    _rec_name = "res_name"

    date = fields.Datetime("Vaqt", required=True, default=fields.Datetime.now, readonly=True, index=True)
    user_id = fields.Many2one("res.users", "Kim", required=True, default=lambda s: s.env.user, readonly=True,
                              index=True)
    section = fields.Selection(EDIT_SECTIONS, "Bo'lim", readonly=True, index=True)
    kind = fields.Selection(EDIT_KINDS, "Amal", required=True, default="edit", readonly=True)
    what = fields.Char("Nima", readonly=True)
    res_model = fields.Char("Model", readonly=True)
    res_id = fields.Integer("Yozuv ID", readonly=True)
    res_name = fields.Char("Yozuv", readonly=True)
    changes = fields.Text("O'zgarishlar", readonly=True)
    by_manager = fields.Boolean("Rahbar tahriri", readonly=True,
                                help="24 soatlik cheklovsiz: omborchi, direktor yoki administrator tahrirlagan.")
    entered_at = fields.Datetime("Kiritilgan vaqt", readonly=True)

    def action_open_record(self):
        self.ensure_one()
        rec = self.env[self.res_model].browse(self.res_id).exists() if self.res_model in self.env else False
        if not rec:
            raise UserError("Yozuv o'chirilgan — o'zgarishlar shu jurnalda qolgan.")
        return {"type": "ir.actions.act_window", "res_model": self.res_model, "res_id": self.res_id,
                "views": [[False, "form"]]}


class CrafEditMixin(models.AbstractModel):
    _name = "craf.edit.mixin"
    _description = "Craf: xodim tahriri (24 soat) va tahrirlash jurnali"

    _craf_edit_section = False   # kimyo / matritsa / boyash
    _craf_edit_what = ""         # jurnalda «Nima» ustuni

    craf_entered_at = fields.Datetime("Kiritilgan vaqt", copy=False, readonly=True,
                                      help="Xodimning 24 soatlik tahrirlash muddati shu vaqtdan (tasdiqlangan "
                                           "vaqtdan) hisoblanadi; qayta tahrirlash muddatni uzaytirmaydi.")
    craf_edit_count = fields.Integer("Tahrirlar soni", copy=False, readonly=True)

    # ------------------------------------------------------------------ har model o'zi belgilaydi
    def _craf_edit_section_get(self):
        return self._craf_edit_section

    def _craf_edit_what_get(self):
        return self._craf_edit_what or self._description

    def _craf_edit_name(self):
        return self.display_name

    def _craf_edit_owner(self):
        """Yozuvni kim kiritgan — xodim faqat o'zi kiritganini tahrirlaydi."""
        return self.create_uid

    def _craf_edit_start(self):
        return self.craf_entered_at or self.create_date

    def _craf_edit_snapshot(self):
        """{yorliq: qiymat matni} — tahrirdan oldin va keyin solishtiriladi."""
        return {}

    # ------------------------------------------------------------------ ruxsat
    def _craf_edit_manager(self):
        user = self.env.user
        return self.env.su or any(user.has_group(g) for g in MANAGER_GROUPS)

    def _craf_edit_info(self):
        """{can, manager, left, left_short, until, reason, count} — sahifada tugma va muddat uchun."""
        self.ensure_one()
        H = self.env["craf.litey.hisobot"]
        info = {"can": False, "manager": False, "left": "", "left_short": "", "until": "", "reason": "",
                "count": self.craf_edit_count}
        if self._craf_edit_manager():
            info.update(can=True, manager=True)
            return info
        user = self.env.user
        if not user._craf_own_app():
            info["reason"] = "Tahrirlash uchun omborchi yoki direktorga murojaat qiling."
            return info
        if self._craf_edit_owner() != user:
            info["reason"] = "Bu yozuvni boshqa foydalanuvchi kiritgan — tahrirlash uchun omborchiga murojaat qiling."
            return info
        start = self._craf_edit_start() or fields.Datetime.now()
        deadline = start + timedelta(hours=EDIT_HOURS)
        info["until"] = H._local(deadline, "%d.%m %H:%M")
        seconds = (deadline - fields.Datetime.now()).total_seconds()
        if seconds <= 0:
            info["reason"] = ("Kiritilganiga 24 soatdan oshdi (%s gacha edi) — endi faqat omborchi yoki direktor "
                              "tahrirlaydi." % info["until"])
            return info
        minutes = max(int(seconds // 60), 1)
        hours, mins = divmod(minutes, 60)
        info["can"] = True
        info["left"] = ("%d soat %d daqiqa" % (hours, mins)) if hours else "%d daqiqa" % mins
        info["left_short"] = ("%d soat" % hours) if hours else "%d daq" % mins
        return info

    def _craf_check_edit(self):
        for rec in self:
            info = rec._craf_edit_info()
            if not info["can"]:
                raise UserError("%s: %s" % (rec._craf_edit_name(), info["reason"]))

    # ------------------------------------------------------------------ jurnal
    def _craf_edit_history(self, limit=20):
        self.ensure_one()
        H = self.env["craf.litey.hisobot"]
        logs = self.env["craf.edit.log"].sudo().search(
            [("res_model", "=", self._name), ("res_id", "=", self.id)], limit=limit)
        kinds = dict(EDIT_KINDS)
        return [{"date": H._local(l.date, "%d.%m.%Y %H:%M"), "who": l.user_id.name or "", "kind": kinds[l.kind],
                 "changes": l.changes or "", "manager": l.by_manager} for l in logs]

    def _craf_log_edit(self, before, kind="edit", extra=None):
        """Oldingi holat (before) bilan hozirgisini solishtirib jurnalga yozadi. O'zgarish bo'lmasa — yozmaydi."""
        self.ensure_one()
        if kind == "cancel":
            lines = ["%s: %s" % (k, v) for k, v in before.items() if v]
        else:
            after = self._craf_edit_snapshot()
            lines = []
            for key in list(before) + [k for k in after if k not in before]:
                old, new = before.get(key) or "", after.get(key) or ""
                if old != new:
                    lines.append("%s: %s → %s" % (key, old or "—", new or "—"))
        lines += extra or []
        if kind == "edit" and not lines:
            return False
        manager = self._craf_edit_manager()
        self.env["craf.edit.log"].sudo().create({
            "section": self._craf_edit_section_get(),
            "kind": kind,
            "what": self._craf_edit_what_get(),
            "res_model": self._name,
            "res_id": self.id,
            "res_name": self._craf_edit_name(),
            "changes": "\n".join(lines),
            "by_manager": manager,
            "entered_at": self._craf_edit_start(),
        })
        self.sudo().craf_edit_count = self.craf_edit_count + 1
        if hasattr(self, "message_post"):
            title = "%s%s" % (dict(EDIT_KINDS)[kind], " (rahbar)" if manager else " (24 soat ichida)")
            self.message_post(body=Markup("<br/>").join([Markup("<b>%s</b>") % title] + lines))
        return True

    # ------------------------------------------------------------------ matn yordamchilari
    def _craf_date_text(self, value):
        return value.strftime("%d.%m.%Y") if value else ""

    def _craf_qty_text(self, qty, uom="", digits=2):
        return ("%s %s" % (fmt(qty, digits) if abs(qty - round(qty)) > EPS else fmt(qty, 0), uom)).strip()


# ====================================================================== mavjud modellar
class CrafChemIssueEdit(models.Model):
    _name = "craf.chem.issue"
    _inherit = ["craf.chem.issue", "craf.edit.mixin"]

    def _craf_edit_section_get(self):
        return {"kislota": "kimyo", "soda": "matritsa", "boyash": "boyash"}.get(self.kind)

    def _craf_edit_what_get(self):
        return {"kislota": "Kislota olish", "soda": "Kaustik soda olish", "boyash": "Material olish"}.get(
            self.kind, "Material olish")

    def _craf_edit_snapshot(self):
        H = self.env["craf.litey.hisobot"]
        res = {"Sana": self._craf_date_text(self.date), "Izoh": self.note or ""}
        qty = {}
        for line in self.line_ids.filtered(lambda l: l.qty > EPS):
            qty[line.product_id] = qty.get(line.product_id, 0.0) + line.qty
        for product, q in qty.items():
            res[product.name] = self._craf_qty_text(q, H._uom(product))
        return res

    def action_done(self):
        res = super().action_done()
        self.filtered(lambda r: r.state == "done" and not r.craf_entered_at).craf_entered_at = fields.Datetime.now()
        return res


class CrafChemTreatmentEdit(models.Model):
    _name = "craf.chem.treatment"
    _inherit = ["craf.chem.treatment", "craf.edit.mixin"]

    _craf_edit_section = "kimyo"
    _craf_edit_what = "Kimyoviy ishlov"

    def _craf_edit_snapshot(self):
        res = {"Sana": self._craf_date_text(self.date), "Smena": self.shift or "", "Izoh": self.note or "",
               "Korzinkalar": ", ".join(sorted(self.load_ids.mapped("basket_id.name")))}
        kinds = {"brak": "yaroqsiz", "cut": "6 → 5 m kesildi"}
        qty = {}
        for line in self.defect_line_ids.filtered(lambda l: l.qty > 0):
            key = "%s · %s — %s" % (line.load_id.basket_id.name, line.product_id.name, kinds.get(line.kind, ""))
            qty[key] = qty.get(key, 0) + line.qty
        for key, q in qty.items():
            res[key] = "%s dona" % q
        return res

    def action_done(self):
        res = super().action_done()
        self.filtered(lambda r: r.state == "done" and not r.craf_entered_at).craf_entered_at = fields.Datetime.now()
        return res
