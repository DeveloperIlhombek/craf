import io
import logging

import xlsxwriter

from odoo import fields, http
from odoo.http import content_disposition, request

from ..models.hik import parse_body

_logger = logging.getLogger(__name__)


class CrafDavomatController(http.Controller):

    @http.route(["/craf/davomat/hik/<string:token>"], type="http", auth="none", methods=["POST", "GET", "PUT"],
                csrf=False, save_session=False)
    def craf_hik_push(self, token, **kwargs):
        """Hikvision «HTTP Listening»: qurilma har bir hodisani shu manzilga yuboradi. Javob doim 200 (kalit to'g'ri
        bo'lsa) — aks holda qurilma qayta-qayta yuboradi."""
        env = request.env(su=True)
        device = env["craf.davomat.device"].search([("token", "=", token), ("active", "=", True)], limit=1)
        if not device:
            return request.make_response("unknown device", status=403)
        req = request.httprequest
        form = {k: v for k, v in req.form.items()} if req.form else {}
        body = b"" if form else req.get_data(cache=False)
        try:
            events = parse_body(req.content_type, body, form)
        except Exception as err:  # noqa: BLE001
            _logger.warning("Craf davomat: o'qib bo'lmadi (%s): %s", device.name, err)
            events = []
        device.write({"last_seen": fields.Datetime.now(), "last_ip": req.remote_addr})
        Log = env["craf.davomat.log"]
        for event in events:
            try:
                with env.cr.savepoint():
                    Log._craf_receive(device, event)
            except Exception as err:  # noqa: BLE001 — bitta yozuv xatosi qurilmani to'xtatmasin
                _logger.exception("Craf davomat: yozuv xatosi (%s)", device.name)
                Log.create({"device_id": device.id, "event_time": event.get("time") or fields.Datetime.now(),
                            "employee_no": event.get("employee_no") or False, "result": "error",
                            "note": str(err)[:200]})
        return request.make_response("OK", headers=[("Content-Type", "text/plain")])

    @http.route("/craf/davomat/tabel", type="http", auth="user")
    def craf_tabel_xlsx(self, year=None, month=None, **kwargs):
        D = request.env["craf.davomat"]
        data = D.get_month(year or False, month or False)
        kpi = D.get_kpi(data["year"], data["month"])
        kpi_by = {r["id"]: r for r in kpi["rows"]}
        out = io.BytesIO()
        wb = xlsxwriter.Workbook(out, {"in_memory": True})
        title = wb.add_format({"bold": True, "font_size": 14})
        head = wb.add_format({"bold": True, "bg_color": "#E8E8E3", "border": 1, "align": "center", "valign": "vcenter",
                              "text_wrap": True})
        cell = wb.add_format({"border": 1})
        c = wb.add_format({"border": 1, "align": "center"})
        late = wb.add_format({"border": 1, "align": "center", "bg_color": "#FFF2CC"})
        absent = wb.add_format({"border": 1, "align": "center", "bg_color": "#FCE4D6", "font_color": "#9C0006"})
        rest = wb.add_format({"border": 1, "align": "center", "font_color": "#888888"})
        num = wb.add_format({"border": 1, "num_format": "0.0"})
        ws = wb.add_worksheet("Tabel")
        ws.write(0, 0, "Ish vaqti tabeli — %s" % data["label"], title)
        ws.write(1, 0, "Raqam — ishlagan soat; K — kelmadi; D — dam olish; sariq — kechikdi.")
        ws.set_column(0, 0, 4)
        ws.set_column(1, 1, 26)
        ws.set_column(2, 1 + len(data["days"]), 4.2)
        ws.set_column(2 + len(data["days"]), 9 + len(data["days"]), 10)
        ws.write(3, 0, "№", head)
        ws.write(3, 1, "Xodim", head)
        for i, d in enumerate(data["days"]):
            ws.write(3, 2 + i, "%s\n%s" % (d["d"], d["wd"]), head)
        tail = ["Ishladi, kun", "Soat", "Reja, kun", "Kechikdi, kun", "Kechikish, daq", "Kelmadi", "KPI ball", "Daraja"]
        base = 2 + len(data["days"])
        for j, t in enumerate(tail):
            ws.write(3, base + j, t, head)
        ws.set_row(3, 30)
        for n, r in enumerate(data["rows"], start=1):
            row = 3 + n
            ws.write(row, 0, n, c)
            ws.write(row, 1, r["name"], cell)
            for i, cl in enumerate(r["cells"]):
                fmt = late if cl["late"] else absent if cl["code"] == "K" else rest if cl["code"] == "D" else c
                ws.write(row, 2 + i, cl["code"], fmt)
            k = kpi_by.get(r["id"], {})
            vals = [r["worked"], r["hours"], r["planned"], r["late_days"], r["late_min"], r["absent"],
                    k.get("total") if k.get("total") is not None else "", k.get("grade") or ""]
            for j, v in enumerate(vals):
                ws.write(row, base + j, v, num if j == 1 or j == 6 else c)
        note_row = 5 + len(data["rows"])
        if kpi["trial"]:
            ws.write(note_row, 1, "KPI sinov rejimida — maoshga ta'sir qilmaydi.")
        ws.freeze_panes(4, 2)
        # KPI tafsiloti
        ws2 = wb.add_worksheet("KPI")
        ws2.write(0, 0, "KPI — %s%s" % (data["label"], " (sinov)" if kpi["trial"] else ""), title)
        s = kpi["settings"]
        ws2.write(1, 0, "Ulushlar: davomat %s%%, intizom %s%%, ishlab chiqarish %s%%" % (s["w_att"], s["w_punct"], s["w_prod"]))
        heads = ["Xodim", "Lavozim", "Davomat, %", "Intizom, %", "Ishlab chiqarish, ball", "Ko'rsatkich", "Jami ball", "Daraja"]
        ws2.write_row(3, 0, heads, head)
        ws2.set_column(0, 1, 24)
        ws2.set_column(2, 4, 13)
        ws2.set_column(5, 5, 48)
        ws2.set_column(6, 7, 10)
        for i, k in enumerate(kpi["rows"], start=4):
            ws2.write_row(i, 0, [k["name"], k["job"], k["att"] if k["att"] is not None else "",
                                 k["punct"] if k["punct"] is not None else "", k["prod"] if k["prod"] is not None else "",
                                 k["prod_text"], k["total"] if k["total"] is not None else "", k["grade"]], cell)
        wb.close()
        name = "Tabel-%04d-%02d.xlsx" % (data["year"], data["month"])
        return request.make_response(out.getvalue(), headers=[
            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Disposition", content_disposition(name)),
        ])
