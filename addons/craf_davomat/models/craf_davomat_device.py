import json
import logging
import secrets
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from .hik import ACCEPT_SUB, REJECT_SUB

_logger = logging.getLogger(__name__)

PLACES = [("zavod", "Zavod"), ("parnik", "Parnik"), ("rohat", "Rohat")]
METHODS = [("face", "Yuz"), ("finger", "Barmoq izi"), ("card", "Karta"), ("manual", "Qo'lda"), ("other", "Boshqa")]
RESULTS = [
    ("done", "Yozildi"),
    ("unknown", "Xodim topilmadi"),
    ("duplicate", "Takror"),
    ("rejected", "Rad etildi"),
    ("ignored", "E'tiborsiz"),
    ("error", "Xato"),
]
REPEAT_SECONDS = 120          # 2 daqiqa ichidagi takror tanish e'tiborsiz
MAX_SHIFT = timedelta(hours=16)  # ochiq yozuv shundan uzoq bo'lsa — «chiqish unutilgan»


class CrafDavomatDevice(models.Model):
    _name = "craf.davomat.device"
    _description = "Davomat terminali (Hikvision)"
    _order = "place, name"

    name = fields.Char("Nomi", required=True)
    place = fields.Selection(PLACES, string="Joy", required=True, default="zavod")
    serial = fields.Char("Seriya / MAC")
    token = fields.Char("Maxfiy kalit", required=True, copy=False, readonly=True,
                        default=lambda self: secrets.token_urlsafe(18))
    push_url = fields.Char("Qurilma yuboradigan manzil", compute="_compute_push_url")
    last_seen = fields.Datetime("Oxirgi aloqa", readonly=True)
    last_ip = fields.Char("Oxirgi IP", readonly=True)
    active = fields.Boolean(default=True)
    note = fields.Char("Izoh")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    log_ids = fields.One2many("craf.davomat.log", "device_id", string="Yozuvlar")

    _token_uniq = models.Constraint("unique(token)", "Kalit takrorlanmasligi kerak.")

    def _compute_push_url(self):
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "").rstrip("/")
        for dev in self:
            dev.push_url = "%s/craf/davomat/hik/%s" % (base, dev.token) if dev.token else ""

    def action_new_token(self):
        for dev in self:
            dev.token = secrets.token_urlsafe(18)
        return True


class CrafDavomatSchedule(models.Model):
    _name = "craf.davomat.schedule"
    _description = "Ish jadvali (davomat)"
    _order = "sequence, id"

    name = fields.Char("Nomi", required=True)
    sequence = fields.Integer(default=10)
    start = fields.Float("Boshlanishi", default=8.0, help="Soat, masalan 8.0 = 08:00")
    end = fields.Float("Tugashi", default=17.0, help="Tungi smena uchun ertasi kun soati (masalan 8.0)")
    break_hours = fields.Float("Tanaffus, soat", default=1.0)
    grace = fields.Integer("Kechikish chegarasi, daqiqa", default=10)
    night = fields.Boolean("Tungi smena", help="Ish ertasi kuni tugaydi")
    days = fields.Char("Ish kunlari", default="123456", help="1 = Dushanba … 7 = Yakshanba")
    active = fields.Boolean(default=True)

    def _hours(self):
        """Rejadagi ish soati (tanaffussiz)."""
        self.ensure_one()
        span = (self.end - self.start) % 24 or 24.0
        return max(span - (self.break_hours or 0.0), 0.0)

    def _is_workday(self, day):
        self.ensure_one()
        return str(day.isoweekday()) in (self.days or "")


class CrafDavomatLog(models.Model):
    _name = "craf.davomat.log"
    _description = "Terminal yozuvi"
    _order = "event_time desc, id desc"

    device_id = fields.Many2one("craf.davomat.device", "Qurilma", index=True, ondelete="cascade")
    employee_no = fields.Char("Terminal ID", index=True)
    name = fields.Char("Qurilmadagi ism")
    employee_id = fields.Many2one("hr.employee", "Xodim", index=True)
    event_time = fields.Datetime("Vaqt", required=True, index=True)
    method = fields.Selection(METHODS, string="Usul", default="face")
    status = fields.Char("Qurilma holati", help="checkIn / checkOut — qurilmada davomat rejimi yoqilgan bo'lsa")
    serial_no = fields.Char("Seriya raqami", help="Qurilmadagi yozuv raqami (serialNo) — takrorni aniqlash uchun")
    current = fields.Boolean("Jonli", default=True, help="O'chiq — qurilma keyinroq qayta yuborgan yozuv")
    result = fields.Selection(RESULTS, string="Natija", default="done", index=True)
    action = fields.Selection([("in", "Kirish"), ("out", "Chiqish")], string="Amal")
    attendance_id = fields.Many2one("hr.attendance", "Davomat", ondelete="set null")
    note = fields.Char("Izoh")
    raw = fields.Text("Xom ma'lumot")

    _serial_uniq = models.Constraint("unique(device_id, serial_no)", "Bu yozuv allaqachon qabul qilingan.")

    # ------------------------------------------------------------------ qabul
    @api.model
    def _craf_receive(self, device, event):
        """Qurilmadan kelgan bitta hodisa (hik.normalize natijasi). Qaytaradi: log yoki False."""
        if event.get("kind") != "event":
            return False
        serial = str(event["serial"]) if event.get("serial") is not None else False
        if serial and self.search_count([("device_id", "=", device.id), ("serial_no", "=", serial)]):
            return False  # qurilma qayta yubordi
        sub = event.get("sub")
        vals = {
            "device_id": device.id,
            "employee_no": event.get("employee_no") or False,
            "name": event.get("name") or False,
            "event_time": event.get("time") or fields.Datetime.now(),
            "method": ACCEPT_SUB.get(sub, "other"),
            "status": event.get("status") or False,
            "serial_no": serial,
            "current": event.get("current", True),
            "raw": json.dumps({k: (str(v) if k == "time" else v) for k, v in event.items()}, ensure_ascii=False)[:2000],
        }
        if event.get("major") != 5 or (sub not in ACCEPT_SUB and sub not in REJECT_SUB):
            vals.update(result="ignored", note="Davomat hodisasi emas (%s/%s)" % (event.get("major"), sub))
            return self.create(vals)
        if sub in REJECT_SUB:
            vals.update(result="rejected", note=REJECT_SUB[sub])
            return self.create(vals)
        log = self.create(vals)
        log._craf_process()
        return log

    def _craf_employee(self):
        self.ensure_one()
        if not self.employee_no:
            return self.env["hr.employee"]
        company = self.device_id.company_id or self.env.company
        return self.env["hr.employee"].search([("craf_terminal_id", "=", self.employee_no),
                                               ("company_id", "in", [company.id, False])], limit=1)

    def _craf_process(self):
        """Yozuvdan davomat: ochiq yozuv bo'lsa — chiqish, bo'lmasa — kirish (qurilma holati bo'lsa — shunga)."""
        Att = self.env["hr.attendance"].sudo()
        for log in self.sorted(lambda l: (l.event_time, l.id)):
            emp = log.employee_id or log._craf_employee()
            if not emp:
                log.write({"result": "unknown", "note": "Terminal ID %s hech bir xodimga biriktirilmagan" % (log.employee_no or "?")})
                continue
            log.employee_id = emp
            t = log.event_time
            prev = self.search([("employee_id", "=", emp.id), ("result", "=", "done"), ("id", "!=", log.id)],
                               order="event_time desc, id desc", limit=1)
            if prev and abs((t - prev.event_time).total_seconds()) < REPEAT_SECONDS:
                log.write({"result": "duplicate", "note": "%s soniya ichida takror tanildi" % REPEAT_SECONDS})
                continue
            last = Att.search([("employee_id", "=", emp.id)], order="check_in desc", limit=1)
            if last and t < (last.check_out or last.check_in):
                log.write({"result": "ignored", "note": "Oxirgi davomatdan oldingi vaqt — qo'lda tekshiring"})
                continue
            open_att = last if last and not last.check_out else Att
            status = (log.status or "").lower()
            if open_att and t - open_att.check_in > MAX_SHIFT:
                hours = emp.craf_schedule_id._hours() if emp.craf_schedule_id else 8.0
                open_att.write({"check_out": open_att.check_in + timedelta(hours=hours or 8.0),
                                "craf_forgot_out": True, "out_mode": "technical"})
                open_att = Att
            if open_att:
                if status == "checkin":
                    log.write({"result": "duplicate", "note": "Xodim allaqachon ishda (kirish takrori)"})
                    continue
                open_att.write({"check_out": t, "out_mode": "kiosk"})
                log.write({"result": "done", "action": "out", "attendance_id": open_att.id})
            else:
                if status == "checkout":
                    log.write({"result": "ignored", "note": "Kirishsiz chiqish — qo'lda tekshiring"})
                    continue
                att = Att.create({"employee_id": emp.id, "check_in": t, "in_mode": "kiosk", "craf_source": "terminal"})
                log.write({"result": "done", "action": "in", "attendance_id": att.id})

    def action_reprocess(self):
        todo = self.filtered(lambda l: l.result in ("unknown", "error"))
        todo.write({"employee_id": False})
        todo._craf_process()
        return True

    def _craf_label(self):
        self.ensure_one()
        return dict(RESULTS).get(self.result, self.result)


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    craf_terminal_id = fields.Char("Terminal ID", index=True, copy=False,
                                   help="Hikvision qurilmasidagi xodim raqami (employeeNo)")
    craf_schedule_id = fields.Many2one("craf.davomat.schedule", "Ish jadvali (davomat)")
    craf_place = fields.Selection(PLACES, string="Ish joyi (davomat)")

    @api.constrains("craf_terminal_id", "company_id")
    def _check_craf_terminal_id(self):
        for emp in self.filtered("craf_terminal_id"):
            other = self.sudo().search([("craf_terminal_id", "=", emp.craf_terminal_id), ("id", "!=", emp.id),
                                        ("company_id", "=", emp.company_id.id)], limit=1)
            if other:
                raise UserError("Terminal ID %s allaqachon %s ga berilgan." % (emp.craf_terminal_id, other.name))


class HrAttendance(models.Model):
    _inherit = "hr.attendance"

    craf_source = fields.Selection([("terminal", "Terminal"), ("manual", "Qo'lda")], string="Manba",
                                   default="manual")
    craf_forgot_out = fields.Boolean("Chiqish unutilgan", help="Chiqish qayd etilmagan — jadval bo'yicha yopildi")
    craf_log_ids = fields.One2many("craf.davomat.log", "attendance_id", string="Terminal yozuvlari")
