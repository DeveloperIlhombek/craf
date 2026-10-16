"""Craf → Davomat: kunlik davomat, oylik tabel, KPI, terminallar (telefon sahifasi uchun API)."""
import calendar
from collections import defaultdict
from datetime import date, datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from .craf_davomat_device import PLACES, RESULTS

PLACE_LABEL = dict(PLACES)
WEEKDAYS = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]
STATUS_LABEL = {
    "ishda": "Ishda", "ketdi": "Ketdi", "kelmadi": "Kelmadi", "dam": "Dam olish", "kutilmoqda": "Hali kelmagan", "": "",
}


def _hm(value):
    """8.5 → '08:30'."""
    value = value or 0.0
    h = int(value) % 24
    m = int(round((value - int(value)) * 60))
    if m == 60:
        h, m = (h + 1) % 24, 0
    return "%02d:%02d" % (h, m)


def _parse_hm(text, label):
    text = (text or "").strip().replace(".", ":").replace(",", ":")
    if not text:
        return None
    try:
        if ":" in text:
            h, m = text.split(":", 1)
            h, m = int(h), int(m)
        else:
            h, m = int(text), 0
    except ValueError:
        raise UserError("%s: vaqtni 08:05 ko'rinishida yozing." % label) from None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise UserError("%s: vaqt noto'g'ri." % label)
    return time(h, m)


class CrafDavomat(models.AbstractModel):
    _name = "craf.davomat"
    _description = "Craf: davomat, tabel, KPI"

    # ================================================================== rollar
    def _roles(self):
        user = self.env.user
        system = user.has_group("base.group_system")
        return {
            "accountant": system or user.has_group("craf_sex.group_craf_accountant"),
            "manager": system or user.has_group("craf_sex.group_craf_director"),
        }

    def _need(self, role="accountant"):
        if not self._roles()[role]:
            raise AccessError("Bu amal faqat %s uchun." % ("omborchi va direktor" if role == "accountant" else "direktor"))

    # ================================================================== vaqt
    def _tz(self):
        return pytz.timezone(self.env.user.tz or self.env.context.get("tz") or "Asia/Tashkent")

    def _bounds(self, day_from, day_to=None):
        tz = self._tz()
        start = tz.localize(datetime.combine(day_from, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        end = tz.localize(datetime.combine(day_to or day_from, time.min)).astimezone(pytz.utc).replace(tzinfo=None) \
            + timedelta(days=1)
        return start, end

    def _local(self, dt):
        return pytz.utc.localize(dt).astimezone(self._tz()).replace(tzinfo=None) if dt else None

    def _utc(self, day, t):
        return self._tz().localize(datetime.combine(day, t)).astimezone(pytz.utc).replace(tzinfo=None)

    def _today(self):
        return fields.Date.context_today(self)

    # ================================================================== asosiy ma'lumot
    def _employees(self):
        return self.env["hr.employee"].sudo().search([("company_id", "in", [self.env.company.id, False])],
                                                     order="name")

    def _default_schedule(self):
        return self.env["craf.davomat.schedule"].sudo().search([], limit=1)

    def _schedule(self, emp, default=None):
        return emp.craf_schedule_id or default or self._default_schedule()

    def _attendances(self, start, end, employees=None):
        domain = [("check_in", "<", end), ("check_in", ">=", start - timedelta(hours=16))]
        if employees is not None:
            domain.append(("employee_id", "in", employees.ids))
        return self.env["hr.attendance"].sudo().search(domain, order="check_in")

    def _by_day(self, atts):
        """{(employee_id, mahalliy kun): [davomatlar]} — davomat kirgan kuniga yoziladi."""
        out = defaultdict(list)
        for a in atts:
            out[(a.employee_id.id, self._local(a.check_in).date())].append(a)
        return out

    def _day_info(self, emp, day, items, sched, now_local):
        """Bitta xodimning bitta kuni."""
        workday = sched._is_workday(day) if sched else day.isoweekday() != 7
        first_in = self._local(min(a.check_in for a in items)) if items else None
        open_items = [a for a in items if not a.check_out]
        last_out = self._local(max(a.check_out for a in items if a.check_out)) if items and not open_items else None
        hours = 0.0
        for a in items:
            # yopilgan — Odoo hisobi (ish kalendaridagi tushlik chiqarilgan), ochiq — hozirgacha
            hours += a.worked_hours if a.check_out else max((fields.Datetime.now() - a.check_in).total_seconds() / 3600.0, 0.0)
        late = 0
        if first_in and workday and sched:
            planned = datetime.combine(day, time.min) + timedelta(hours=sched.start)
            diff = int((first_in - planned).total_seconds() // 60)
            if diff > (sched.grace or 0):
                late = diff
        if open_items:
            status = "ishda"
        elif items:
            status = "ketdi"
        elif not workday:
            status = "dam"
        elif day > now_local.date():
            status = ""
        elif day == now_local.date() and sched and now_local.hour + now_local.minute / 60.0 < sched.start + (sched.grace or 0) / 60.0:
            status = "kutilmoqda"
        else:
            status = "kelmadi"
        return {
            "in": first_in.strftime("%H:%M") if first_in else "",
            "out": last_out.strftime("%H:%M") if last_out else "",
            "hours": round(hours, 2), "late": late, "status": status, "workday": workday,
            "forgot": any(a.craf_forgot_out for a in items),
            "manual": any(a.craf_source != "terminal" for a in items),
            "count": len(items),
        }

    # ================================================================== kun
    @api.model
    def get_day(self, day=False):
        self._need()
        day = fields.Date.to_date(day) if day else self._today()
        start, end = self._bounds(day)
        employees = self._employees()
        default = self._default_schedule()
        by_day = self._by_day(self._attendances(start, end, employees))
        now_local = self._local(fields.Datetime.now())
        rows = []
        for emp in employees:
            sched = self._schedule(emp, default)
            info = self._day_info(emp, day, by_day.get((emp.id, day), []), sched, now_local)
            rows.append({
                "id": emp.id, "name": emp.name, "job": emp.job_title or "", "terminal": emp.craf_terminal_id or "",
                "place": PLACE_LABEL.get(emp.craf_place, ""), "schedule": sched.name if sched else "",
                "start": _hm(sched.start) if sched else "", **info,
                "status_label": STATUS_LABEL.get(info["status"], ""),
            })
        order = {"ishda": 0, "kelmadi": 1, "kutilmoqda": 2, "ketdi": 3, "dam": 4, "": 5}
        rows.sort(key=lambda r: (order.get(r["status"], 9), -r["late"], r["name"]))
        planned = [r for r in rows if r["workday"]]
        came = [r for r in rows if r["count"]]
        Log = self.env["craf.davomat.log"].sudo()
        week_ago = fields.Datetime.now() - timedelta(days=7)
        devices = self.env["craf.davomat.device"].sudo().search([])
        return {
            "day": fields.Date.to_string(day), "today": fields.Date.to_string(self._today()),
            "weekday": WEEKDAYS[day.weekday()],
            "kpi": [
                {"label": "Keldi", "value": len(came), "unit": "/ %s" % len(planned), "tone": ""},
                {"label": "Hozir ishda", "value": sum(1 for r in rows if r["status"] == "ishda"), "unit": "", "tone": "ok"},
                {"label": "Kechikdi", "value": sum(1 for r in rows if r["late"]), "unit": "",
                 "tone": "warn" if any(r["late"] for r in rows) else ""},
                {"label": "Kelmadi", "value": sum(1 for r in rows if r["status"] == "kelmadi"), "unit": "",
                 "tone": "bad" if any(r["status"] == "kelmadi" for r in rows) else ""},
            ],
            "rows": rows,
            "unknown": Log.search_count([("result", "=", "unknown"), ("event_time", ">=", week_ago)]),
            "devices_offline": sum(1 for d in devices if not self._online(d)),
            "devices": len(devices),
            "roles": self._roles(),
        }

    def _online(self, device):
        return bool(device.last_seen) and fields.Datetime.now() - device.last_seen < timedelta(minutes=30)

    # ================================================================== oy (tabel)
    def _month(self, year, month):
        today = self._today()
        year, month = int(year or today.year), int(month or today.month)
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        return first, last

    @api.model
    def get_month(self, year=False, month=False):
        self._need()
        first, last = self._month(year, month)
        today = self._today()
        start, end = self._bounds(first, last)
        employees = self._employees()
        default = self._default_schedule()
        by_day = self._by_day(self._attendances(start, end, employees))
        now_local = self._local(fields.Datetime.now())
        days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
        rows = []
        for emp in employees:
            sched = self._schedule(emp, default)
            cells, tot = [], {"worked": 0, "hours": 0.0, "late_days": 0, "late_min": 0, "absent": 0, "planned": 0,
                              "planned_hours": 0.0, "forgot": 0}
            for d in days:
                info = self._day_info(emp, d, by_day.get((emp.id, d), []), sched, now_local)
                if info["workday"] and d <= today:
                    tot["planned"] += 1
                    tot["planned_hours"] += sched._hours() if sched else 8.0
                if info["count"]:
                    tot["worked"] += 1
                    tot["hours"] += info["hours"]
                if info["late"]:
                    tot["late_days"] += 1
                    tot["late_min"] += info["late"]
                if info["status"] == "kelmadi":
                    tot["absent"] += 1
                if info["forgot"]:
                    tot["forgot"] += 1
                code = ("%g" % round(info["hours"], 1)) if info["count"] else (
                    "D" if info["status"] == "dam" else ("K" if info["status"] == "kelmadi" else ""))
                cells.append({"code": code, "late": bool(info["late"]), "status": info["status"],
                              "forgot": info["forgot"]})
            tot["hours"] = round(tot["hours"], 1)
            tot["planned_hours"] = round(tot["planned_hours"], 1)
            rows.append({"id": emp.id, "name": emp.name, "job": emp.job_title or "", "cells": cells, **tot})
        return {
            "year": first.year, "month": first.month,
            "label": "%s %s" % (["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul", "Avgust", "Sentyabr",
                                 "Oktyabr", "Noyabr", "Dekabr"][first.month - 1], first.year),
            "days": [{"d": d.day, "wd": WEEKDAYS[d.weekday()], "iso": fields.Date.to_string(d),
                      "weekend": d.isoweekday() == 7} for d in days],
            "rows": rows, "today": fields.Date.to_string(today), "roles": self._roles(),
        }

    # ================================================================== KPI
    def _prod_metrics(self, employees, first, last):
        """{employee_id: [(nomi, qiymat, me'yor, ball, hujjatlar soni, matn)]} — ishlab chiqarish ko'rsatkichi."""
        company = self.env.company
        out = defaultdict(list)
        specs = [
            ("craf.foundry.melt", "Литейка угар", "burn_loss_qty", "charge_metal", company.craf_kpi_litey_loss, "max", 25),
            ("craf.extrusion.shift", "Press chiqishi", "output_kg", "billet_qty", company.craf_kpi_press_yield, "min", 5),
            ("craf.paint.batch", "Bo'yash braki", "pcs_defect", "pcs_in", company.craf_kpi_paint_defect, "max", 20),
        ]
        for model, label, num, den, target, kind, slope in specs:
            if model not in self.env:
                continue
            docs = self.env[model].sudo().search([("state", "=", "done"), ("date", ">=", first), ("date", "<=", last),
                                                  ("employee_id", "in", employees.ids)])
            groups = defaultdict(lambda: self.env[model])
            for d in docs:
                groups[d.employee_id.id] |= d
            for emp_id, recs in groups.items():
                total = sum(recs.mapped(den))
                if not total:
                    continue
                value = sum(recs.mapped(num)) / total * 100.0
                if kind == "max":
                    score = 100.0 if value <= target else max(0.0, 100.0 - (value - target) * slope)
                    text = "%s %.1f%% (me'yor ≤%g%%)" % (label, value, target)
                else:
                    score = 100.0 if value >= target else max(0.0, 100.0 - (target - value) * slope)
                    text = "%s %.1f%% (me'yor ≥%g%%)" % (label, value, target)
                out[emp_id].append((label, round(value, 2), target, round(score, 1), len(recs), text))
        return out

    @api.model
    def get_kpi(self, year=False, month=False):
        self._need()
        month_data = self.get_month(year, month)
        first, last = self._month(month_data["year"], month_data["month"])
        employees = self._employees()
        prod = self._prod_metrics(employees, first, last)
        company = self.env.company
        w_att, w_punct, w_prod = company.craf_kpi_w_att, company.craf_kpi_w_punct, company.craf_kpi_w_prod
        rows = []
        for r in month_data["rows"]:
            att = round(min(100.0, r["worked"] / r["planned"] * 100.0), 1) if r["planned"] else None
            punct = round(max(0.0, 100.0 * (1 - r["late_days"] / r["worked"])), 1) if r["worked"] else None
            metrics = prod.get(r["id"], [])
            prod_score = round(sum(m[3] * m[4] for m in metrics) / sum(m[4] for m in metrics), 1) if metrics else None
            parts = [(att, w_att), (punct, w_punct), (prod_score, w_prod)]
            used = [(v, w) for v, w in parts if v is not None and w]
            total = round(sum(v * w for v, w in used) / sum(w for _v, w in used), 1) if used else None
            grade = "" if total is None else ("A" if total >= 90 else "B" if total >= 75 else "C" if total >= 60 else "D")
            rows.append({
                "id": r["id"], "name": r["name"], "job": r["job"],
                "worked": r["worked"], "planned": r["planned"], "hours": r["hours"], "late_days": r["late_days"],
                "late_min": r["late_min"], "absent": r["absent"],
                "att": att, "punct": punct, "prod": prod_score, "prod_text": " · ".join(m[5] for m in metrics),
                "prod_docs": sum(m[4] for m in metrics), "total": total, "grade": grade,
            })
        rows.sort(key=lambda r: (r["total"] is None, -(r["total"] or 0), r["name"]))
        return {
            "year": month_data["year"], "month": month_data["month"], "label": month_data["label"],
            "rows": rows, "trial": company.craf_kpi_trial,
            "settings": {
                "w_att": w_att, "w_punct": w_punct, "w_prod": w_prod,
                "litey_loss": company.craf_kpi_litey_loss, "press_yield": company.craf_kpi_press_yield,
                "paint_defect": company.craf_kpi_paint_defect, "trial": company.craf_kpi_trial,
            },
            "roles": self._roles(),
        }

    @api.model
    def kpi_settings_save(self, vals):
        self._need("manager")
        mapping = {"w_att": "craf_kpi_w_att", "w_punct": "craf_kpi_w_punct", "w_prod": "craf_kpi_w_prod",
                   "litey_loss": "craf_kpi_litey_loss", "press_yield": "craf_kpi_press_yield",
                   "paint_defect": "craf_kpi_paint_defect"}
        write = {}
        for key, field in mapping.items():
            if key in vals and vals[key] not in (None, ""):
                try:
                    value = float(str(vals[key]).replace(",", "."))
                except ValueError:
                    raise UserError("%s: raqam kiriting." % key) from None
                if value < 0:
                    raise UserError("Manfiy qiymat bo'lmaydi.")
                write[field] = int(value) if key.startswith("w_") else value
        if "trial" in vals:
            write["craf_kpi_trial"] = bool(vals["trial"])
        weights = [write.get("craf_kpi_w_att", self.env.company.craf_kpi_w_att),
                   write.get("craf_kpi_w_punct", self.env.company.craf_kpi_w_punct),
                   write.get("craf_kpi_w_prod", self.env.company.craf_kpi_w_prod)]
        if not sum(weights):
            raise UserError("Ulushlardan kamida bittasi 0 dan katta bo'lsin.")
        self.env.company.sudo().write(write)
        return True

    # ================================================================== xodim
    @api.model
    def employee_detail(self, employee_id, year=False, month=False):
        self._need()
        emp = self.env["hr.employee"].sudo().browse(int(employee_id)).exists()
        if not emp:
            raise UserError("Xodim topilmadi.")
        first, last = self._month(year, month)
        start, end = self._bounds(first, last)
        atts = self.env["hr.attendance"].sudo().search([("employee_id", "=", emp.id), ("check_in", ">=", start),
                                                        ("check_in", "<", end)], order="check_in desc")
        sched = self._schedule(emp)
        rows = []
        for a in atts:
            cin, cout = self._local(a.check_in), self._local(a.check_out)
            rows.append({
                "id": a.id, "date": fields.Date.to_string(cin.date()), "wd": WEEKDAYS[cin.weekday()],
                "in": cin.strftime("%H:%M"), "out": cout.strftime("%H:%M") if cout else "",
                "out_date": fields.Date.to_string(cout.date()) if cout else "",
                "hours": round(a.worked_hours or 0.0, 2), "source": a.craf_source or "manual",
                "forgot": a.craf_forgot_out,
            })
        return {
            "id": emp.id, "name": emp.name, "job": emp.job_title or "", "terminal": emp.craf_terminal_id or "",
            "schedule_id": emp.craf_schedule_id.id or False, "place": emp.craf_place or "",
            "schedule": sched.name if sched else "", "rows": rows,
            "schedules": [{"id": s.id, "name": s.name} for s in self.env["craf.davomat.schedule"].sudo().search([])],
            "places": [{"key": k, "label": v} for k, v in PLACES],
            "year": first.year, "month": first.month, "roles": self._roles(),
        }

    @api.model
    def employee_save(self, employee_id, vals):
        self._need()
        emp = self.env["hr.employee"].sudo().browse(int(employee_id)).exists()
        if not emp:
            raise UserError("Xodim topilmadi.")
        write = {}
        if "terminal" in vals:
            write["craf_terminal_id"] = (vals.get("terminal") or "").strip() or False
        if "schedule_id" in vals:
            write["craf_schedule_id"] = int(vals["schedule_id"]) if vals.get("schedule_id") else False
        if "place" in vals:
            write["craf_place"] = vals.get("place") or False
        emp.write(write)
        if write.get("craf_terminal_id"):
            logs = self.env["craf.davomat.log"].sudo().search([("result", "=", "unknown"),
                                                                ("employee_no", "=", write["craf_terminal_id"])])
            logs.action_reprocess()
        return True

    @api.model
    def attendance_save(self, vals):
        """vals: id?, employee_id, date, time_in, time_out (bo'sh — hali ishda), out_next_day."""
        self._need()
        Att = self.env["hr.attendance"].sudo()
        att = Att.browse(int(vals["id"])).exists() if vals.get("id") else Att
        emp = att.employee_id or self.env["hr.employee"].sudo().browse(int(vals.get("employee_id") or 0)).exists()
        if not emp:
            raise UserError("Xodim topilmadi.")
        day = fields.Date.to_date(vals.get("date")) if vals.get("date") else self._today()
        if day > self._today():
            raise UserError("Kelajak sanasiga davomat yozilmaydi.")
        tin = _parse_hm(vals.get("time_in"), "Keldi")
        if not tin:
            raise UserError("Kelgan vaqtni yozing.")
        tout = _parse_hm(vals.get("time_out"), "Ketdi")
        check_in = self._utc(day, tin)
        check_out = False
        if tout:
            out_day = day + timedelta(days=1) if (vals.get("out_next_day") or tout <= tin) else day
            check_out = self._utc(out_day, tout)
        if check_out and check_out > fields.Datetime.now() + timedelta(minutes=5):
            raise UserError("Ketgan vaqt hali kelmagan.")
        write = {"employee_id": emp.id, "check_in": check_in, "check_out": check_out, "craf_forgot_out": False}
        try:
            if att:
                att.write(write)
                att.message_post(body="Qo'lda tuzatildi (%s): %s — %s" % (
                    self.env.user.name, tin.strftime("%H:%M"), tout.strftime("%H:%M") if tout else "…"))
            else:
                att = Att.create({**write, "craf_source": "manual", "in_mode": "manual"})
        except Exception as err:
            raise UserError(str(err).splitlines()[0]) from None
        return {"id": att.id}

    @api.model
    def attendance_delete(self, attendance_id):
        self._need()
        att = self.env["hr.attendance"].sudo().browse(int(attendance_id)).exists()
        if att:
            att.craf_log_ids.write({"result": "ignored", "note": "Davomat o'chirildi"})
            att.unlink()
        return True

    # ================================================================== terminallar
    @api.model
    def devices(self):
        self._need()
        Log = self.env["craf.davomat.log"].sudo()
        start, _end = self._bounds(self._today())
        rows = []
        for d in self.env["craf.davomat.device"].sudo().with_context(active_test=False).search([]):
            rows.append({
                "id": d.id, "name": d.name, "place": d.place, "place_label": PLACE_LABEL.get(d.place, ""),
                "serial": d.serial or "", "note": d.note or "", "active": d.active, "url": d.push_url,
                "last_seen": self._local(d.last_seen).strftime("%d.%m %H:%M") if d.last_seen else "",
                "online": self._online(d), "today": Log.search_count([("device_id", "=", d.id), ("event_time", ">=", start)]),
            })
        logs = Log.search([], limit=60)
        employees = self._employees()
        return {
            "devices": rows,
            "logs": [{
                "id": l.id, "time": self._local(l.event_time).strftime("%d.%m %H:%M:%S"), "device": l.device_id.name or "",
                "employee_no": l.employee_no or "", "name": l.name or "", "employee": l.employee_id.name or "",
                "result": l.result, "result_label": dict(RESULTS).get(l.result, ""), "action": l.action or "",
                "note": l.note or "", "method": l.method or "",
            } for l in logs],
            "unknown": [{"no": no, "name": name, "count": cnt} for no, name, cnt in self._unknown_groups()],
            "employees": [{"id": e.id, "name": e.name, "terminal": e.craf_terminal_id or ""} for e in employees],
            "places": [{"key": k, "label": v} for k, v in PLACES],
            "roles": self._roles(),
        }

    def _unknown_groups(self):
        rows = self.env["craf.davomat.log"].sudo()._read_group(
            [("result", "=", "unknown")], ["employee_no", "name"], ["__count"])
        return [(no or "", name or "", cnt) for no, name, cnt in rows]

    @api.model
    def device_save(self, vals):
        self._need()
        Dev = self.env["craf.davomat.device"].sudo().with_context(active_test=False)
        dev = Dev.browse(int(vals["id"])).exists() if vals.get("id") else Dev
        name = (vals.get("name") or "").strip()
        if not name:
            raise UserError("Qurilma nomini yozing.")
        write = {"name": name, "place": vals.get("place") or "zavod", "serial": (vals.get("serial") or "").strip() or False,
                 "note": (vals.get("note") or "").strip() or False}
        if "active" in vals:
            write["active"] = bool(vals["active"])
        if dev:
            dev.write(write)
        else:
            dev = Dev.create(write)
        return {"id": dev.id, "url": dev.push_url}

    @api.model
    def device_test(self, device_id, employee_id):
        """Sinov: qurilmadan kelgandek yuz tanish yozuvi (hozirgi vaqt) — butun yo'l tekshiriladi."""
        self._need()
        dev = self.env["craf.davomat.device"].sudo().browse(int(device_id)).exists()
        emp = self.env["hr.employee"].sudo().browse(int(employee_id)).exists()
        if not dev or not emp:
            raise UserError("Qurilma va xodimni tanlang.")
        if not emp.craf_terminal_id:
            raise UserError("%s ga Terminal ID berilmagan." % emp.name)
        log = self.env["craf.davomat.log"].sudo()._craf_receive(dev, {
            "kind": "event", "major": 5, "sub": 75, "employee_no": emp.craf_terminal_id, "name": emp.name,
            "time": fields.Datetime.now(), "serial": None, "status": "", "current": True,
        })
        dev.last_seen = fields.Datetime.now()
        return {"result": log.result, "label": log._craf_label(), "action": log.action or "", "note": log.note or ""}

    @api.model
    def log_assign(self, employee_no, employee_id):
        """Noma'lum terminal ID ni xodimga biriktirish va uning yozuvlarini qayta ishlash."""
        self._need()
        emp = self.env["hr.employee"].sudo().browse(int(employee_id)).exists()
        if not emp or not employee_no:
            raise UserError("Xodimni tanlang.")
        if emp.craf_terminal_id and emp.craf_terminal_id != employee_no:
            raise UserError("%s da boshqa Terminal ID bor: %s." % (emp.name, emp.craf_terminal_id))
        emp.craf_terminal_id = employee_no
        logs = self.env["craf.davomat.log"].sudo().search([("result", "=", "unknown"), ("employee_no", "=", employee_no)])
        logs.action_reprocess()
        return {"count": len(logs), "done": len(logs.filtered(lambda l: l.result == "done"))}

    @api.model
    def schedules(self):
        self._need()
        return [{"id": s.id, "name": s.name, "start": _hm(s.start), "end": _hm(s.end), "break": s.break_hours,
                 "grace": s.grace, "night": s.night, "days": s.days or "", "hours": round(s._hours(), 2),
                 "count": self.env["hr.employee"].sudo().search_count([("craf_schedule_id", "=", s.id)])}
                for s in self.env["craf.davomat.schedule"].sudo().search([])]

    @api.model
    def schedule_save(self, vals):
        self._need("manager")
        Sched = self.env["craf.davomat.schedule"].sudo()
        sched = Sched.browse(int(vals["id"])).exists() if vals.get("id") else Sched
        start, end = _parse_hm(vals.get("start"), "Boshlanishi"), _parse_hm(vals.get("end"), "Tugashi")
        if not start or not end:
            raise UserError("Boshlanish va tugash vaqtini yozing.")
        days = "".join(sorted(set(c for c in str(vals.get("days") or "") if c in "1234567")))
        if not days:
            raise UserError("Kamida bitta ish kunini belgilang.")
        write = {
            "name": (vals.get("name") or "").strip() or "%s–%s" % (start.strftime("%H:%M"), end.strftime("%H:%M")),
            "start": start.hour + start.minute / 60.0, "end": end.hour + end.minute / 60.0,
            "break_hours": float(str(vals.get("break") or 0).replace(",", ".")),
            "grace": int(vals.get("grace") or 0), "night": end <= start, "days": days,
        }
        if sched:
            sched.write(write)
        else:
            sched = Sched.create(write)
        return {"id": sched.id}
