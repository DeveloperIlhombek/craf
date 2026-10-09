import io

import xlsxwriter

from odoo import http
from odoo.http import content_disposition, request


class CrafKunlikController(http.Controller):

    @http.route("/craf/kunlik/xlsx", type="http", auth="user")
    def craf_kunlik_xlsx(self, date=None, **kwargs):
        data = request.env["craf.kunlik.hisobot"].get_data(date)
        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {"in_memory": True})
        bold = wb.add_format({"bold": True})
        title = wb.add_format({"bold": True, "font_size": 14})
        head = wb.add_format({"bold": True, "bg_color": "#E8E8E3", "border": 1, "text_wrap": True, "valign": "top"})
        cell = wb.add_format({"border": 1})
        num = wb.add_format({"border": 1, "num_format": "# ##0.00"})
        num0 = wb.add_format({"border": 1, "num_format": "# ##0"})
        low = wb.add_format({"border": 1, "num_format": "# ##0.00", "bg_color": "#FCE4D6"})

        # 1) Bo'limlar
        ws = wb.add_worksheet("Bo'limlar")
        ws.set_column(0, 0, 12)
        ws.set_column(1, 1, 46)
        ws.set_column(2, 4, 14)
        ws.write(0, 0, "Kunlik hisobot (1C uchun) — %s" % data["date_label"], title)
        row = 2
        for dep in data["departments"]:
            ws.write(row, 0, dep["title"], bold)
            row += 1
            docs = ", ".join("%s (%s)" % (d["name"], d["state_label"]) for d in dep["docs"]) or "hujjat yo'q"
            ws.write(row, 0, "Hujjatlar: " + docs)
            row += 1
            for extra in dep.get("extra") or []:
                ws.write(row, 0, extra)
                row += 1
            for label, rows in (("Sarf", dep.get("used")), ("Chiqish", dep.get("made")), ("Chiqindi / brak", dep.get("waste"))):
                if not rows:
                    continue
                ws.write_row(row, 0, [label + ": kod", "Nomi", "Miqdor", "Birlik", "kg"], head)
                row += 1
                for r in rows:
                    ws.write(row, 0, r["code"], cell)
                    ws.write(row, 1, r["name"], cell)
                    ws.write_number(row, 2, r["qty"], num)
                    ws.write(row, 3, r["uom"], cell)
                    ws.write_number(row, 4, r["kg"], num)
                    row += 1
            row += 1

        # 2) Xom-ashyo harakati
        ws = wb.add_worksheet("Xom-ashyo")
        ws.set_column(0, 0, 10)
        ws.set_column(1, 1, 36)
        ws.set_column(2, 9, 13)
        ws.write(0, 0, "Xom-ashyo harakati — %s" % data["date_label"], title)
        headers = ["Kod", "Nomi", "Birlik", "Boshlang'ich qoldiq", "Kirim (xarid, inventarizatsiya)",
                   "Ishlab chiqarishdan", "Sarf (ishlab chiqarishga)", "Boshqa chiqim", "Oxirgi qoldiq", "Minimal"]
        ws.write_row(2, 0, headers, head)
        for i, r in enumerate(data["raw"], start=3):
            ws.write(i, 0, r["code"], cell)
            ws.write(i, 1, r["name"], cell)
            ws.write(i, 2, r["uom"], cell)
            for j, key in enumerate(("opening", "in_supply", "in_prod", "out_prod", "out_other"), start=3):
                ws.write_number(i, j, r[key], num)
            ws.write_number(i, 8, r["closing"], low if r["low"] else num)
            ws.write_number(i, 9, r["min_qty"] or 0, num)

        # 3) Tayyor mahsulot
        ws = wb.add_worksheet("Tayyor mahsulot")
        ws.set_column(0, 0, 16)
        ws.set_column(1, 1, 36)
        ws.set_column(2, 8, 13)
        ws.write(0, 0, "Tayyor mahsulot harakati — %s" % data["date_label"], title)
        ws.write_row(2, 0, ["Kod", "Nomi", "Birlik", "Boshlang'ich", "Ishlab chiqarildi / kirim", "Jo'natildi / chiqim",
                            "Oxirgi qoldiq", "Oxirgi, kg"], head)
        for i, r in enumerate(data["finished"], start=3):
            ws.write(i, 0, r["code"], cell)
            ws.write(i, 1, r["name"], cell)
            ws.write(i, 2, r["uom"], cell)
            ws.write_number(i, 3, r["opening"], num0)
            ws.write_number(i, 4, r["in_supply"] + r["in_prod"], num0)
            ws.write_number(i, 5, r["out_prod"] + r["out_other"], num0)
            ws.write_number(i, 6, r["closing"], num0)
            ws.write_number(i, 7, r["closing"] * (r["kg_per_pc"] or 0), num)
        wb.close()
        filename = "Craf_kunlik_%s.xlsx" % data["date"]
        return request.make_response(output.getvalue(), headers=[
            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Disposition", content_disposition(filename)),
        ])
