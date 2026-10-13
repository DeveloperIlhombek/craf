import base64
import io
import re
from datetime import date as Date, datetime, time, timedelta

import pytz

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_litey.models.craf_litey_hisobot import DAILY_PRODUCED_CODES
from odoo.addons.craf_production.models.craf_production_mixin import fmt

SKIP_ROWS = ("ишлабчикарилганлитейка", "ишлабчиқарилганлитейка")


def norm(text):
    """Excel nomini solishtirish uchun: kichik harf, bo'shliq va qavslarsiz, ё=е."""
    text = (text or "").lower().replace("ё", "е").replace("қ", "к").replace("ў", "у")
    return re.sub(r"[\s().,\-_/]+", "", text)


class CrafLiteyImport(models.TransientModel):
    _name = "craf.litey.import"
    _description = "Литейка: Excel jadvalidagi qoldiqni yuklash"

    state = fields.Selection([("upload", "Fayl"), ("preview", "Taqqoslash")], default="upload")
    file = fields.Binary("Excel fayl (.xlsx)")
    filename = fields.Char("Fayl nomi")
    date = fields.Date("Qaysi kun ustuni", help="Bo'sh qoldirilsa — fayldagi oxirgi kun")
    moment = fields.Selection(
        [("start", "Kun boshidagi qoldiq"), ("end", "Kun oxiridagi qoldiq")], string="Ustundagi raqam",
        default="end", required=True,
        help="Kun boshida: shu kunning plavkalaridan oldin sanalgan. Kun oxirida: shu kunning barcha "
             "harakatlaridan keyin.")
    fill_prev = fields.Boolean("Bo'sh katak — oldingi kundagi qiymat", default=True,
                               help="Shu kun ustuni to'ldirilmagan qatorlar uchun oxirgi to'ldirilgan qiymat olinadi")
    consolidate = fields.Boolean("Hammasini asosiy joyga yig'ish", default=True,
                                 help="Boshqa ichki joylardagi qoldiq 0 qilinib, Excel dagi miqdor mahsulotning "
                                      "asosiy joyiga (odatda Литейка) yoziladi.")
    dates_info = fields.Char("Fayldagi kunlar", readonly=True)
    line_ids = fields.One2many("craf.litey.import.line", "wizard_id", string="Qatorlar")
    diff_count = fields.Integer("Farqli qatorlar", compute="_compute_diff_count")

    @api.depends("line_ids.apply")
    def _compute_diff_count(self):
        for wiz in self:
            wiz.diff_count = len(wiz.line_ids.filtered("apply"))

    # ---------------------------------------------------------------- vaqt
    def _moment_utc(self):
        tz = pytz.timezone(self.env.user.tz or "Asia/Tashkent")
        day = self.date - timedelta(days=1) if self.moment == "start" else self.date
        when = tz.localize(datetime.combine(day, time(23, 59))).astimezone(pytz.utc).replace(tzinfo=None)
        return min(when, fields.Datetime.now() - timedelta(seconds=5))

    # ---------------------------------------------------------------- o'qish
    def _read_sheet(self):
        if not self.file:
            raise UserError("Excel faylni tanlang.")
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(base64.b64decode(self.file)), data_only=True, read_only=True)
        except Exception as err:  # noqa: BLE001 — foydalanuvchiga tushunarli xabar
            raise UserError("Faylni o'qib bo'lmadi: %s" % err) from err
        for ws in wb.worksheets:
            rows = [list(r) for r in ws.iter_rows(values_only=True)]
            for h, row in enumerate(rows[:6]):
                cols = {i: v.date() if isinstance(v, datetime) else v for i, v in enumerate(row)
                        if isinstance(v, (datetime, Date))}
                if len(cols) >= 2:
                    return rows, h, cols
        raise UserError("Faylda sanalar qatori topilmadi (birinchi qatorda kunlar bo'lishi kerak, Лист1 kabi).")

    def _match(self, name, products):
        key = norm(name)
        for p in products:
            for candidate in (p.craf_litey_name, p.name, p.craf_name_1c):
                if candidate and norm(candidate) == key:
                    return p
        return self.env["product.product"]

    def action_parse(self):
        self.ensure_one()
        rows, header, date_cols = self._read_sheet()
        dates = sorted(set(date_cols.values()))
        if not self.date:
            filled = [d for c, d in date_cols.items()
                      if any(isinstance(r[c] if c < len(r) else None, (int, float)) for r in rows[header + 1:])]
            self.date = max(filled or dates)
        products = self.env["craf.litey.hisobot"]._products()
        when = None
        lines = []
        for r in rows[header + 1:]:
            name = next((v for v in r[:2] if isinstance(v, str) and v.strip()), None)
            if not name:
                continue
            values = {d: r[c] for c, d in date_cols.items() if c < len(r) and isinstance(r[c], (int, float))}
            product = self._match(name, products)
            vals = {"excel_name": name.strip(), "product_id": product.id or False}
            if norm(name) in SKIP_ROWS or (product and product.default_code in DAILY_PRODUCED_CODES):
                vals.update(note="Kunlik chiqish — plavkalardan hisoblanadi, yuklanmaydi", skip=True)
                lines.append(vals)
                continue
            if not product:
                vals.update(note="Odoo da mos mahsulot topilmadi", skip=True)
                lines.append(vals)
                continue
            used = self.date if self.date in values else None
            if used is None and self.fill_prev:
                prev = [d for d in values if d <= self.date]
                used = max(prev) if prev else None
            if used is None:
                vals.update(note="Bu kunda qiymat yo'q", skip=True)
                lines.append(vals)
                continue
            if when is None:
                when = self._moment_utc()
            excel_qty = float(values[used])
            odoo_qty = product.with_context(to_date=when).qty_available
            vals.update({
                "excel_qty": excel_qty, "odoo_qty": odoo_qty, "value_date": used,
                "location_id": (product.craf_litey_location_id
                                or self.env["craf.production.mixin"]._craf_loc("Литейка")).id,
                "apply": abs(excel_qty - odoo_qty) > 0.005,
                "note": "" if used == self.date else "%s dagi qiymat" % used.strftime("%d.%m"),
            })
            lines.append(vals)
        self.write({
            "state": "preview",
            "dates_info": "%s — %s, %s kun" % (dates[0].strftime("%d.%m.%Y"), dates[-1].strftime("%d.%m.%Y"),
                                                 len(dates)),
            "line_ids": [Command.clear()] + [Command.create(v) for v in lines],
        })
        return self._reopen()

    def action_back(self):
        self.write({"state": "upload", "line_ids": [Command.clear()]})
        return self._reopen()

    def _reopen(self):
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
            "view_mode": "form", "views": [(False, "form")], "target": "new",
            "name": "Excel jadvalidagi qoldiqni yuklash",
        }

    # ---------------------------------------------------------------- yozish
    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group("stock.group_stock_manager"):
            raise UserError("Qoldiqni tuzatish uchun ombor menejeri huquqi kerak.")
        todo = self.line_ids.filtered(lambda l: l.apply and l.product_id and not l.skip)
        if not todo:
            raise UserError("Yuklanadigan qator yo'q (farqli qatorlarni belgilang).")
        when = self._moment_utc()
        Quant = self.env["stock.quant"].with_context(inventory_mode=True)
        Move = self.env["stock.move"]
        before = Move.search([], order="id desc", limit=1).id or 0
        quants = Quant.browse()
        for line in todo:
            product, main = line.product_id, line.location_id
            now_total = product.qty_available
            at_moment = product.with_context(to_date=when).qty_available
            target_now = line.excel_qty + (now_total - at_moment)
            internal = Quant.search([("product_id", "=", product.id), ("location_id.usage", "=", "internal"),
                                     ("company_id", "in", [self.env.company.id, False])])
            by_loc = {}
            for q in internal:
                by_loc.setdefault(q.location_id, Quant.browse())
                by_loc[q.location_id] |= q
            targets = {}
            if self.consolidate:
                for loc, qs in by_loc.items():
                    if loc != main and abs(sum(qs.mapped("quantity"))) > 1e-6:
                        targets[loc] = 0.0
                targets[main] = target_now
            else:
                diff = target_now - now_total
                main_qty = sum(by_loc.get(main, Quant.browse()).mapped("quantity"))
                if diff >= 0:
                    targets[main] = main_qty + diff
                else:
                    need = -diff
                    order = [main] + sorted((l for l in by_loc if l != main),
                                            key=lambda l: -sum(by_loc[l].mapped("quantity")))
                    for loc in order:
                        have = sum(by_loc.get(loc, Quant.browse()).mapped("quantity"))
                        take = min(need, max(have, 0.0))
                        if take > 0:
                            targets[loc] = have - take
                            need -= take
                        if need <= 1e-6:
                            break
                    if need > 1e-6:
                        targets[main] = targets.get(main, main_qty) - need
            for loc, qty in targets.items():
                existing = by_loc.get(loc, Quant.browse())
                if existing:
                    q = existing[:1]
                    (existing - q).write({"inventory_quantity": 0.0})
                    quants |= existing - q
                    q.inventory_quantity = qty
                else:
                    q = Quant.create({"product_id": product.id, "location_id": loc.id, "inventory_quantity": qty})
                quants |= q
        name = "Excel qoldig'i %s (%s)" % (self.date.strftime("%d.%m.%Y"), dict(
            self._fields["moment"].selection)[self.moment].lower())
        quants.with_context(inventory_name=name)._apply_inventory(date=when)
        moves = Move.search([("id", ">", before), ("is_inventory", "=", True)])
        moves.write({"date": when})
        moves.move_line_ids.write({"date": when})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": "Qoldiq yuklandi",
                "message": "%s ta material Excel bo'yicha tuzatildi (%s)." % (len(todo), name),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }


class CrafLiteyImportLine(models.TransientModel):
    _name = "craf.litey.import.line"
    _description = "Excel qoldig'i qatori"
    _order = "id"

    wizard_id = fields.Many2one("craf.litey.import", required=True, ondelete="cascade")
    excel_name = fields.Char("Excel dagi nomi", readonly=True)
    product_id = fields.Many2one("product.product", string="Odoo mahsuloti")
    value_date = fields.Date("Kun", readonly=True)
    excel_qty = fields.Float("Excel", digits=(16, 2))
    odoo_qty = fields.Float("Odoo", digits=(16, 2), readonly=True)
    diff = fields.Float("Farq", compute="_compute_diff", digits=(16, 2))
    location_id = fields.Many2one("stock.location", string="Joy", domain=[("usage", "=", "internal")])
    apply = fields.Boolean("Yuklash")
    skip = fields.Boolean()
    note = fields.Char("Izoh", readonly=True)
    uom_name = fields.Char(related="product_id.uom_id.name", string="Birligi")

    @api.depends("excel_qty", "odoo_qty")
    def _compute_diff(self):
        for line in self:
            line.diff = line.excel_qty - line.odoo_qty

    def _fmt(self, value):
        return fmt(value, 2 if value % 1 else 0)
