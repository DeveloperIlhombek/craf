import io

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from werkzeug.exceptions import NotFound

from odoo import http
from odoo.http import request

from odoo.addons.craf_hisobot.controllers.main import CrafKunlikController

THIN = Side(style="thin", color="000000")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD_FILL = PatternFill("solid", fgColor="E8E8E3")


class CrafKunlikSotuvController(CrafKunlikController):

    @http.route("/craf/kunlik/xlsx", type="http", auth="user")
    def craf_kunlik_xlsx(self, date=None, **kwargs):
        response = super().craf_kunlik_xlsx(date=date, **kwargs)
        try:
            wb = load_workbook(io.BytesIO(response.get_data()))
        except Exception:  # noqa: BLE001 — asl fayl qaytadi
            return response
        Hisobot = request.env["craf.kunlik.hisobot"]
        data = Hisobot.get_data(date)
        self._craf_fix_departments(wb)
        self._craf_finished_sold(wb, data)
        self._craf_sales_sheet(wb, data, Hisobot.get_sales_rows(date))
        out = io.BytesIO()
        wb.save(out)
        response.set_data(out.getvalue())
        return response

    @staticmethod
    def _craf_fix_departments(wb):
        """"Bo'limlar" varag'ida sotuv bo'limining "Chiqish" sarlavhasi -> "Sotildi"."""
        if "Bo'limlar" not in wb.sheetnames:
            return
        ws = wb["Bo'limlar"]
        in_sales = False
        for row in ws.iter_rows(min_col=1, max_col=1):
            cell = row[0]
            if isinstance(cell.value, str):
                if cell.value.startswith("6. Sotuv"):
                    in_sales = True
                elif in_sales and cell.value == "Chiqish: kod":
                    cell.value = "Sotildi: kod"

    @staticmethod
    def _craf_finished_sold(wb, data):
        """"Tayyor mahsulot" varag'iga "Sotildi" ustuni (Jo'natildi / chiqim dan keyin)."""
        if "Tayyor mahsulot" not in wb.sheetnames:
            return
        ws = wb["Tayyor mahsulot"]
        # ustunlar: Kod, Nomi, Birlik, Boshlang'ich, Kirim, Chiqim(6), Oxirgi, Oxirgi kg
        ws.insert_cols(6)
        new_head = ws.cell(row=3, column=6, value="Sotildi (mijozlarga)")
        new_head.font = Font(bold=True)
        new_head.fill = HEAD_FILL
        new_head.border = BORDER
        new_head.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=3, column=7, value="Boshqa chiqim (ishlab chiqarish, ko'chirish)")
        ws.column_dimensions["F"].width = 13
        ws.column_dimensions["G"].width = 13
        ws.column_dimensions["H"].width = 13
        ws.column_dimensions["I"].width = 13
        for i, r in enumerate(data["finished"], start=4):
            cell = ws.cell(row=i, column=6, value=r.get("out_sale") or 0)
            cell.number_format = "# ##0"
            cell.border = BORDER

    @staticmethod
    def _craf_sales_sheet(wb, data, rows):
        ws = wb.create_sheet("Sotuv")
        ws.column_dimensions["A"].width = 17
        ws.column_dimensions["B"].width = 11
        ws.column_dimensions["C"].width = 22
        ws.column_dimensions["D"].width = 13
        ws.column_dimensions["E"].width = 10
        ws.column_dimensions["F"].width = 18
        ws.column_dimensions["G"].width = 36
        for col in "HIJKL":
            ws.column_dimensions[col].width = 11
        ws["A1"] = "Sotuv (mijozlarga berildi) — %s" % data["date_label"]
        ws["A1"].font = Font(bold=True, size=14)
        headers = ["Vaqt", "Hujjat", "Mijoz", "Mashina", "Joy", "Kod", "Mahsulot", "Pachka", "Dona (+)",
                   "Jami dona", "kg", "1C"]
        for j, h in enumerate(headers, start=1):
            c = ws.cell(row=3, column=j, value=h)
            c.font = Font(bold=True)
            c.fill = HEAD_FILL
            c.border = BORDER
            c.alignment = Alignment(wrap_text=True, vertical="top")
        r = 4
        for row in rows:
            values = [row["time"], row["order"], row["partner"], row["truck"], row["location"], row["code"],
                      row["name"], row["packs"], row["extra"], row["pcs"], round(row["kg"], 2), row["c1"]]
            for j, v in enumerate(values, start=1):
                c = ws.cell(row=r, column=j, value=v)
                c.border = BORDER
                if j in (8, 9, 10):
                    c.number_format = "# ##0"
                elif j == 11:
                    c.number_format = "# ##0.00"
            r += 1
        if rows:
            ws.cell(row=r, column=7, value="Jami").font = Font(bold=True)
            for j, key in ((10, "pcs"), (11, "kg")):
                c = ws.cell(row=r, column=j, value=round(sum(x[key] for x in rows), 2))
                c.font = Font(bold=True)
                c.number_format = "# ##0.00" if key == "kg" else "# ##0"
        else:
            ws.cell(row=4, column=1, value="Bu kunda sotuv yo'q")


class CrafSotuvPhoto(http.Controller):

    @http.route("/craf/sotuv/photo/<int:att_id>", type="http", auth="user", readonly=True)
    def craf_sotuv_photo(self, att_id, size=None, **kwargs):
        """Mashina rasmi — yuklovchi/sotuvchi ko'radi (buyurtmaga ruxsati bo'lmasa ham)."""
        env = request.env
        if not env.user.has_group("craf_sotuv.group_craf_loader"):
            raise NotFound()
        att = env["ir.attachment"].sudo().browse(att_id).exists()
        if not att or not env["sale.order"].sudo().search_count([("craf_truck_photo_ids", "in", att.ids)]):
            raise NotFound()
        try:
            px = max(0, min(int(size or 0), 2048))
        except ValueError:
            px = 0
        stream = env["ir.binary"]._get_image_stream_from(att, "raw", width=px, height=px)
        return stream.get_response(max_age=86400)
