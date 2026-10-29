import io
from datetime import date

import xlsxwriter

from odoo import http
from odoo.http import content_disposition, request

STATE_LABELS = {"draft": "Qoralama", "done": "Bajarildi", "cancel": "Bekor"}
BALANCE_LABELS = {"none": "", "ok": "Me'yorda", "warn": "Yuqori", "bad": "Me'yordan tashqari"}


class CrafLiteyController(http.Controller):

    @http.route("/craf/litey/xlsx", type="http", auth="user")
    def craf_litey_xlsx(self, date_from=None, date_to=None, **kwargs):
        data = request.env["craf.litey.hisobot"].get_data(date_from, date_to)
        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {"in_memory": True})
        title = wb.add_format({"bold": True, "font_size": 14})
        head = wb.add_format({"bold": True, "bg_color": "#E8E8E3", "border": 1, "text_wrap": True,
                              "valign": "vcenter", "align": "center"})
        head_date = wb.add_format({"bold": True, "bg_color": "#E8E8E3", "border": 1, "num_format": "dd.mm.yyyy",
                                   "align": "center"})
        cell = wb.add_format({"border": 1})
        num = wb.add_format({"border": 1, "num_format": "# ##0.0#"})
        num0 = wb.add_format({"border": 1, "num_format": "# ##0"})
        num_prod = wb.add_format({"border": 1, "num_format": "# ##0.0#", "bg_color": "#EEF5FF", "italic": True})
        cell_prod = wb.add_format({"border": 1, "bg_color": "#EEF5FF", "italic": True})
        num_neg = wb.add_format({"border": 1, "num_format": "# ##0.0#", "font_color": "#B3261E"})
        bold_num = wb.add_format({"border": 1, "num_format": "# ##0.0#", "bold": True})
        pct = wb.add_format({"border": 1, "num_format": "0.00"})
        pct_bad = wb.add_format({"border": 1, "num_format": "0.00", "bg_color": "#FDE8E8"})
        dfmt = wb.add_format({"border": 1, "num_format": "dd.mm.yyyy"})

        def val(ws, r, c, v, fmt=num):
            if v is None or v == "" or abs(v) < 1e-9:
                ws.write_blank(r, c, None, fmt)
            else:
                ws.write_number(r, c, v, fmt)

        # 1) Kunlik qoldiq — Excel Лист1 ko'rinishida
        ws = wb.add_worksheet("Литейка (kunlik)")
        ws.freeze_panes(1, 2)
        ws.set_column(0, 0, 30)
        ws.set_column(1, 1, 8)
        ws.set_column(2, 2 + len(data["days"]), 11)
        ws.write(0, 0, "Наимнование", head)
        ws.write(0, 1, "Ед.Изм", head)
        for j, day in enumerate(data["days"], start=2):
            ws.write_datetime(0, j, date.fromisoformat(day["date"]), head_date)
        for i, row in enumerate(data["matrix"], start=1):
            produced = row["kind"] == "produced"
            ws.write(i, 0, row["label"], cell_prod if produced else cell)
            ws.write(i, 1, row["uom"], cell_prod if produced else cell)
            for j, v in enumerate(row["values"], start=2):
                val(ws, i, j, v, num_prod if produced else (num_neg if v < -1e-6 else num))

        # 2) Davr harakati
        ws = wb.add_worksheet("Harakat")
        ws.set_column(0, 0, 30)
        ws.set_column(1, 1, 7)
        ws.set_column(2, 10, 13)
        ws.write(0, 0, "Литейка: qoldiq va harakat — %s" % data["label"], title)
        headers = ["Material", "Birlik", "Boshlang'ich qoldiq", "Kirim (xarid)", "Plavkadan chiqdi",
                   "Pressdan / boshqa ishlab chiqarishdan", "Plavkaga sarf", "Boshqa sarf", "Tuzatish va boshqa",
                   "Oxirgi qoldiq", "Kod"]
        ws.write_row(2, 0, headers, head)
        ws.set_row(2, 32)
        for i, r in enumerate(data["movement"], start=3):
            ws.write(i, 0, r["excel_name"], cell)
            ws.write(i, 1, r["uom"], cell)
            for j, key in enumerate(("opening", "kirim", "chiqish_plavka", "chiqish_boshqa", "sarf_plavka",
                                     "sarf_boshqa"), start=2):
                val(ws, i, j, r[key])
            val(ws, i, 8, r["tuzatish"] + r["boshqa"])
            ws.write_number(i, 9, r["closing"], num_neg if r["negative"] else bold_num)
            ws.write(i, 10, r["code"], cell)

        # 3) Plavkalar (daftar)
        ws = wb.add_worksheet("Plavkalar")
        ws.freeze_panes(3, 4)
        ws.write(0, 0, "Plavkalar (ishchi daftari) — %s" % data["label"], title)
        cols = ["Sana", "Pech", "Smena", "Hujjat"]
        cols += [c["excel"] for c in data["metal_cols"]]
        cols += ["Kirdi (metall), kg", "Stalba, kg", "Uzunlik, m", "Сталба отход", "Литейка отход", "Шлак",
                 "Chiqdi jami", "Угар, kg", "Угар, %", "Balans"]
        cols += [c["excel"] + (" (%s)" % c["uom"]) for c in data["aux_cols"]]
        cols += ["Holat", "Izoh"]
        ws.write_row(2, 0, cols, head)
        ws.set_row(2, 45)
        ws.set_column(0, 0, 11)
        ws.set_column(1, 1, 16)
        ws.set_column(2, 2, 14)
        ws.set_column(3, 3, 12)
        ws.set_column(4, len(cols), 11)
        for i, m in enumerate(data["melts"], start=3):
            c = 0
            ws.write_datetime(i, c, date.fromisoformat(m["date"]), dfmt)
            ws.write(i, c + 1, m["pech"], cell)
            ws.write(i, c + 2, m["day_no"] or "", cell)
            ws.write(i, c + 3, m["name"], cell)
            c = 4
            for col in data["metal_cols"]:
                pid = str(col["product_id"])
                val(ws, i, c, m["qty"].get(pid, 0))
                if m["text"].get(pid):
                    ws.write_comment(i, c, m["text"][pid])
                c += 1
            for key in ("charge_metal", "billet_qty", "billet_length", "cut_waste_qty", "foundry_waste_qty",
                        "slag_qty", "output_total", "loss_qty"):
                val(ws, i, c, m[key])
                c += 1
            ws.write_number(i, c, m["loss_pct"], pct_bad if m["balance_state"] == "bad" else pct)
            ws.write(i, c + 1, BALANCE_LABELS.get(m["balance_state"], ""), cell)
            c += 2
            for col in data["aux_cols"]:
                val(ws, i, c, m["qty"].get(str(col["product_id"]), 0))
                c += 1
            ws.write(i, c, STATE_LABELS.get(m["state"], m["state"]), cell)
            ws.write(i, c + 1, m["note"], cell)

        # 4) Kirim (Лист2 o'rniga)
        ws = wb.add_worksheet("Kirim")
        ws.write(0, 0, "Kirimlar — %s" % data["label"], title)
        ws.write_row(2, 0, ["Дата Прихода", "Номер машины", "Наименование", "Вес, kg", "Цена за 1 кг",
                            "Общая сумма", "Yetkazib beruvchi", "Hujjat"], head)
        ws.set_column(0, 0, 12)
        ws.set_column(1, 1, 16)
        ws.set_column(2, 2, 28)
        ws.set_column(3, 5, 14)
        ws.set_column(6, 7, 20)
        for i, r in enumerate(data["receipts"], start=3):
            ws.write(i, 0, r["date_label"], cell)
            ws.write(i, 1, r["vehicle"], cell)
            ws.write(i, 2, r["product"], cell)
            ws.write_number(i, 3, r["qty"], num)
            val(ws, i, 4, r["price"], num0)
            val(ws, i, 5, r["amount"], num0)
            ws.write(i, 6, r["partner"], cell)
            ws.write(i, 7, r["name"], cell)
        if data["receipts"]:
            last = 3 + len(data["receipts"])
            ws.write(last, 2, "Jami", head)
            ws.write_formula(last, 3, "=SUM(D4:D%s)" % last, bold_num)
            ws.write_formula(last, 5, "=SUM(F4:F%s)" % last, bold_num)

        wb.close()
        filename = "Craf_Litey_%s_%s.xlsx" % (data["date_from"], data["date_to"])
        return request.make_response(output.getvalue(), headers=[
            ("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ("Content-Disposition", content_disposition(filename)),
        ])
