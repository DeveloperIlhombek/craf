import io

import xlsxwriter

from odoo import http
from odoo.http import content_disposition, request


def _dmy(iso):
    return "%s.%s.%s" % (iso[8:10], iso[5:7], iso[0:4]) if iso else ""


class CrafPulController(http.Controller):

    @http.route("/craf/pul/akt", type="http", auth="user")
    def craf_pul_akt(self, partner_id, kind="customer", date_from=None, date_to=None, **kwargs):
        """Akt sverka (Excel): boshlang'ich qoldiq, hujjatlar va to'lovlar, oxirgi qoldiq."""
        Pul = request.env["craf.pul"]
        Pul._need()
        d = Pul.partner_detail(int(partner_id), kind, date_from or False, date_to or False)
        cur = d["currency"]["symbol"]
        company = request.env.company
        out = io.BytesIO()
        wb = xlsxwriter.Workbook(out, {"in_memory": True})
        title = wb.add_format({"bold": True, "font_size": 14})
        bold = wb.add_format({"bold": True})
        head = wb.add_format({"bold": True, "bg_color": "#E8E8E3", "border": 1, "text_wrap": True, "valign": "top"})
        cell = wb.add_format({"border": 1, "valign": "top", "text_wrap": True})
        num = wb.add_format({"border": 1, "num_format": "# ##0", "valign": "top"})
        numb = wb.add_format({"border": 1, "num_format": "# ##0", "bold": True})
        ws = wb.add_worksheet("Akt sverka")
        ws.set_column(0, 0, 11)
        ws.set_column(1, 1, 18)
        ws.set_column(2, 2, 48)
        ws.set_column(3, 5, 16)
        ws.write(0, 0, "Akt sverka (o'zaro hisob-kitob dalolatnomasi)", title)
        ws.write(1, 0, "%s — %s" % (company.name, d["partner"]["name"]), bold)
        ws.write(2, 0, "Davr: %s — %s" % (_dmy(d["date_from"]), _dmy(d["date_to"])))
        if d["kind"] == "customer":
            plus_label, minus_label = "Berildi (qarz oshdi)", "To'landi"
            note = "Musbat qoldiq — %s %s ga qarz." % (d["partner"]["name"], company.name)
        else:
            plus_label, minus_label = "Olindi (qarz oshdi)", "To'landi"
            note = "Musbat qoldiq — %s %s ga qarz." % (company.name, d["partner"]["name"])
        ws.write_row(4, 0, ["Sana", "Hujjat", "Mazmuni", plus_label + ", " + cur, minus_label + ", " + cur,
                            "Qoldiq, " + cur], head)
        row = 5
        ws.write(row, 0, _dmy(d["date_from"]), cell)
        ws.write(row, 1, "", cell)
        ws.write(row, 2, "Boshlang'ich qoldiq", cell)
        ws.write(row, 3, "", cell)
        ws.write(row, 4, "", cell)
        ws.write_number(row, 5, d["opening"], numb)
        row += 1
        for r in reversed(d["rows"]):
            ws.write(row, 0, _dmy(r["date"]), cell)
            ws.write(row, 1, r["name"], cell)
            ws.write(row, 2, r["label"], cell)
            if r["amount"] >= 0:
                ws.write_number(row, 3, r["amount"], num)
                ws.write(row, 4, "", cell)
            else:
                ws.write(row, 3, "", cell)
                ws.write_number(row, 4, -r["amount"], num)
            ws.write_number(row, 5, r["balance"], num)
            row += 1
        ws.write(row, 2, "Jami aylanma", bold)
        ws.write_number(row, 3, d["plus"], numb)
        ws.write_number(row, 4, d["minus"], numb)
        row += 1
        ws.write(row, 2, "Oxirgi qoldiq (%s)" % _dmy(d["date_to"]), bold)
        ws.write_number(row, 5, d["closing"], numb)
        row += 2
        ws.write(row, 0, note)
        row += 3
        ws.write(row, 0, company.name, bold)
        ws.write(row, 3, d["partner"]["name"], bold)
        ws.write(row + 2, 0, "_____________________ (imzo)")
        ws.write(row + 2, 3, "_____________________ (imzo)")
        wb.close()
        name = "Akt-sverka-%s-%s.xlsx" % (d["partner"]["name"].replace(" ", "_")[:40], d["date_to"])
        return request.make_response(out.getvalue(), headers=[
            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Disposition", content_disposition(name)),
        ])
