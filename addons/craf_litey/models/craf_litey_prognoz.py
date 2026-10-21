"""Liteyka xom-ashyosi: qoldiq, minimal qoldiq va necha kunga yetishi (prognoz).

O'rtacha kunlik sarf — oxirgi N kun (bo'lim sozlamasi, standart 30) ichida ichki joylardan ishlab chiqarishga
ketgan miqdor (plavkaga va boshqa sarf) / N. Qoldiq — zavod bo'yicha (barcha ichki joylar), Qoldiq varag'i bilan bir xil.

Minimal qoldiqdan kamaygan material uchun bo'lim mas'ullariga Odoo eslatmasi (mail.activity) qo'yiladi;
qoldiq tiklanganda eslatma o'zi yopiladi. Telegram xabari keyingi bosqichda shu ro'yxatdan oladi.
"""
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

ACTIVITY_XMLID = "craf_litey.mail_activity_min_qty"


class CrafLiteyHisobot(models.AbstractModel):
    _inherit = "craf.litey.hisobot"

    # ------------------------------------------------------------------ hisob
    def _forecast_rows(self):
        bolim = self.env["craf.bolim"]._get("litey")
        period = max(bolim.forecast_days or 30, 1)
        warn = max(bolim.warn_days or 0, 0)
        today = fields.Date.context_today(self)
        start_day = today - timedelta(days=period - 1)
        products = self._products()
        on_hand = self._on_hand(products)
        flows = self._flows(products, self._utc(start_day))

        rows = []
        for product in products:
            pid = product.id
            used, active_days = 0.0, 0
            for day, per_product in flows.items():
                if day < start_day:
                    continue
                kinds = per_product.get(pid, {})
                spent = -(kinds.get("sarf_plavka", 0.0) + kinds.get("sarf_boshqa", 0.0))
                if spent > 1e-6:
                    used += spent
                    active_days += 1
            qty = on_hand.get(pid, 0.0)
            min_qty = product.craf_min_qty or 0.0
            avg = used / period
            days_left = qty / avg if avg > 1e-9 and qty > 0 else None
            days_to_min = (qty - min_qty) / avg if avg > 1e-9 and min_qty and qty > min_qty else None
            if qty < -1e-6:
                status = "neg"
            elif min_qty and qty < min_qty:
                status = "low"
            elif (days_to_min is not None and days_to_min <= warn) or (
                    not min_qty and days_left is not None and days_left <= warn):
                status = "soon"
            elif avg <= 1e-9:
                status = "idle"
            else:
                status = "ok"
            rows.append({
                "product_id": pid, "tmpl_id": product.product_tmpl_id.id,
                "code": product.default_code or "", "name": product.craf_litey_name or product.name,
                "full_name": product.name, "uom": self._uom(product),
                "kind": "aux" if product.craf_not_metal else "metal",
                "qty": round(qty, 3), "min_qty": min_qty,
                "used": round(used, 2), "avg": round(avg, 3), "active_days": active_days,
                "days_left": round(days_left, 1) if days_left is not None else None,
                "days_to_min": round(days_to_min, 1) if days_to_min is not None else None,
                "end_date": fields.Date.to_string(today + timedelta(days=int(days_left)))
                if days_left is not None else False,
                "min_date": fields.Date.to_string(today + timedelta(days=int(days_to_min)))
                if days_to_min is not None else False,
                "status": status,
            })
        return bolim, period, warn, rows

    # ------------------------------------------------------------------ sahifa
    @api.model
    def get_forecast(self):
        bolim, period, warn, rows = self._forecast_rows()
        self.sudo()._craf_min_qty_sync(rows)
        order = {"neg": 0, "low": 1, "soon": 2, "ok": 3, "idle": 4}
        rows.sort(key=lambda r: (order[r["status"]], r["days_to_min"] if r["days_to_min"] is not None
                                 else (r["days_left"] if r["days_left"] is not None else 1e9)))
        counts = {k: sum(1 for r in rows if r["status"] == k) for k in order}
        today = fields.Date.context_today(self)
        return {
            "rows": rows, "counts": counts, "period": period, "warn_days": warn,
            "date_from": fields.Date.to_string(today - timedelta(days=period - 1)),
            "today": fields.Date.to_string(today),
            "bolim_id": bolim.id or False,
            "contacts": [{"name": c.name, "role": c.role or "", "user": c.user_id.name or "",
                          "telegram": bool(c.telegram_id)}
                         for c in bolim.contact_ids.filtered(lambda c: c.active and c.notify_min_qty)],
            "is_manager": self._is_editor(),
            "can_settings": self.env.user.has_group("mrp.group_mrp_manager"),
        }

    @api.model
    def set_min_qty(self, product_id, value):
        self._check_editor()
        product = self.env["product.product"].browse(int(product_id)).exists()
        if not product or product.craf_litey_seq <= 0:
            raise UserError("Material topilmadi.")
        try:
            qty = float(str(value or 0).replace(",", ".").replace(" ", ""))
        except ValueError as err:
            raise UserError("Minimal qoldiqni raqam bilan yozing: %s" % value) from err
        if qty < 0:
            raise UserError("Minimal qoldiq manfiy bo'lishi mumkin emas.")
        product.product_tmpl_id.sudo().craf_min_qty = qty  # huquq _check_editor da tekshirildi
        return self.get_forecast()

    # ------------------------------------------------------------------ eslatma
    @api.model
    def _craf_min_qty_sync(self, rows=None):
        """Minimaldan kam materiallar uchun mas'ullarga eslatma qo'yadi, tiklanganlarinikini yopadi."""
        act_type = self.env.ref(ACTIVITY_XMLID, raise_if_not_found=False)
        if not act_type:
            return
        bolim = self.env["craf.bolim"]._get("litey")
        if rows is None:
            rows = self._forecast_rows()[3]
        users = self.env["res.users"]
        if bolim and bolim.notify_app:
            users = bolim.contact_ids.filtered(lambda c: c.active and c.notify_min_qty and c.user_id).user_id
        low = {r["tmpl_id"]: r for r in rows if r["status"] in ("low", "neg") and r["min_qty"]}

        Activity = self.env["mail.activity"].sudo()
        existing = Activity.search([("activity_type_id", "=", act_type.id), ("res_model", "=", "product.template")])
        have = set()
        for act in existing:
            if act.res_id in low and act.user_id in users:
                have.add((act.res_id, act.user_id.id))
                r = low[act.res_id]
                note = self._min_qty_note(r)
                if str(act.note or "") != note:
                    act.note = note
            else:
                act.action_feedback(feedback="Qoldiq tiklandi yoki eslatma o'chirildi.")
        Template = self.env["product.template"].sudo()
        for tmpl_id, r in low.items():
            for user in users:
                if (tmpl_id, user.id) in have:
                    continue
                Template.browse(tmpl_id).activity_schedule(
                    ACTIVITY_XMLID, user_id=user.id,
                    summary="Liteyka: %s minimal qoldiqdan kam" % r["name"],
                    note=self._min_qty_note(r))

    def _min_qty_note(self, r):
        text = "Qoldiq: %s %s, minimal: %s %s." % (
            self._fmt_num(r["qty"]), r["uom"], self._fmt_num(r["min_qty"]), r["uom"])
        if r["days_left"] is not None:
            text += " O'rtacha sarf bilan ~%s kunga yetadi." % self._fmt_num(r["days_left"])
        return "<p>%s</p>" % text

    @staticmethod
    def _fmt_num(value):
        value = float(value or 0)
        text = ("%.0f" if abs(value - round(value)) < 1e-6 else "%.1f") % value
        return text

    @api.model
    def _cron_min_qty(self):
        self.sudo()._craf_min_qty_sync()
