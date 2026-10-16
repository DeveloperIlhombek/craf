import logging

from odoo import fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PRICE_MIN = 1.0  # 1 so'm va undan kam — narx yozilmagan (Odoo yangi mahsulotga 1.0 qo'yadi)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    craf_price_missing = fields.Boolean(
        "Narx kerak", copy=False, index=True, readonly=True,
        help="Mahsulot berildi, lekin narxi yo'qligi uchun hisob-faktura yaratilmadi")

    def write(self, vals):
        res = super().write(vals)
        # «Berildi» (yuklovchi yoki sotuvchi): berilgan qismga hisob-faktura
        if vals.get("craf_given_date") and not self.env.context.get("craf_no_invoice"):
            for order in self:
                order._craf_auto_invoice()
        return res

    def _craf_auto_invoice(self):
        """Yetkazib berishni to'xtatmaydi: xato bo'lsa buyurtmaga yozib qo'yiladi."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                self.sudo()._craf_make_invoice()
        except Exception as err:  # noqa: BLE001 — har qanday xato yetkazib berishni buzmasligi kerak
            _logger.warning("Craf: %s hisob-fakturasi yaratilmadi: %s", self.name, err)
            self.sudo().message_post(body="Hisob-faktura avtomatik yaratilmadi: %s" % err)

    def _craf_local_date(self, dt):
        return fields.Date.context_today(self, dt) if dt else fields.Date.context_today(self)

    def _craf_lines_to_invoice(self):
        return self.order_line.filtered(lambda l: not l.display_type and l.product_id and l.qty_to_invoice > 0)

    def _craf_unlocked(self):
        """Qulflangan buyurtmada narxni o'zgartirish uchun vaqtincha ochadi; qulflanganmi — qaytaradi."""
        locked = self.filtered("locked")
        if locked:
            locked.action_unlock()
        return locked

    def _craf_make_invoice(self):
        """Berilgan, lekin hisob-faktura qilinmagan miqdorga hisob-faktura (darhol tasdiqlanadi)."""
        self.ensure_one()
        lines = self._craf_lines_to_invoice()
        if not lines:
            self.craf_price_missing = False
            return self.env["account.move"]
        locked = self._craf_unlocked()
        try:
            for line in lines.filtered(lambda l: l.price_unit <= PRICE_MIN):
                if line.product_id.lst_price > PRICE_MIN:
                    line.price_unit = line.product_id.lst_price
            if any(l.price_unit <= PRICE_MIN for l in lines):
                if not self.craf_price_missing:
                    self.craf_price_missing = True
                    self.message_post(body="Narx yozilmagan mahsulot berildi — hisob-faktura Pul sahifasida "
                                           "narx yozilgandan keyin yaratiladi.")
                return self.env["account.move"]
            taxed = lines.filtered("tax_ids")
            if taxed:
                taxed.write({"tax_ids": [(5,)]})
            moves = self._create_invoices(final=True)
            day = self._craf_local_date(self.craf_given_date)
            moves.write({"invoice_date": day})
            moves.invoice_line_ids.filtered("tax_ids").write({"tax_ids": [(5,)]})
            moves.action_post()
            self.craf_price_missing = False
        finally:
            if locked:
                locked.action_lock()
        self.env["craf.pul"]._reconcile_partner(self.partner_id, "asset_receivable")
        return moves

    def _craf_after_return(self, picking):
        """Sotuvdan qaytarish: hisob-faktura qilingan miqdor qaytgan bo'lsa — qaytarish hisob-fakturasi."""
        res = super()._craf_after_return(picking)
        try:
            with self.env.cr.savepoint():
                self.sudo()._craf_make_refund(picking)
        except Exception as err:  # noqa: BLE001 — qaytarishni buzmasin
            _logger.warning("Craf: %s qaytarish hisob-fakturasi yaratilmadi: %s", self.name, err)
            self.sudo().message_post(body="Qaytarish hisob-fakturasi avtomatik yaratilmadi: %s" % err)
        return res

    def _craf_make_refund(self, picking):
        self.ensure_one()
        lines = self.order_line.filtered(lambda l: not l.display_type and l.product_id and l.qty_to_invoice < 0)
        if not lines:
            return self.env["account.move"]
        locked = self._craf_unlocked()
        try:
            moves = self._create_invoices(final=True)
            day = fields.Date.context_today(self, picking.date_done) if picking.date_done else \
                fields.Date.context_today(self)
            moves.write({"invoice_date": day, "ref": "Qaytarish %s" % picking.name})
            moves.invoice_line_ids.filtered("tax_ids").write({"tax_ids": [(5,)]})
            moves.action_post()
        finally:
            if locked:
                locked.action_lock()
        self.env["craf.pul"]._reconcile_partner(self.partner_id, "asset_receivable")
        return moves

    def _craf_set_prices(self, prices):
        """prices: {sale.order.line id: narx}. Tasdiqlangan hisob-fakturalar ham yangi narxga o'tadi."""
        self.ensure_one()
        lines = self.order_line.filtered(lambda l: str(l.id) in prices or l.id in prices)
        locked = self._craf_unlocked()
        try:
            for line in lines:
                price = prices.get(str(line.id), prices.get(line.id))
                price = float(price or 0.0)
                if price < 0:
                    raise UserError("Narx manfiy bo'lishi mumkin emas.")
                if abs(line.price_unit - price) > 1e-6:
                    line.price_unit = price
            invoices = self.invoice_ids.filtered(lambda m: m.move_type == "out_invoice" and m.state == "posted")
            for inv in invoices:
                changes = []
                for il in inv.invoice_line_ids:
                    sl = il.sale_line_ids[:1]
                    if sl and abs(il.price_unit - sl.price_unit) > 1e-6:
                        changes.append((il, sl.price_unit))
                if not changes:
                    continue
                inv.button_draft()
                for il, price in changes:
                    il.price_unit = price
                inv.action_post()
        finally:
            if locked:
                locked.action_lock()
        self._craf_make_invoice()
        self.env["craf.pul"]._reconcile_partner(self.partner_id, "asset_receivable")
        return True
