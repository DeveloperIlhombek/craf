import logging

from odoo import Command, fields, models

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    craf_bill_id = fields.Many2one("account.move", "Hisob-faktura", copy=False, readonly=True,
                                   index="btree_not_null", help="Yetkazib beruvchi hisob-fakturasi (yoki qaytarish)")

    # ------------------------------------------------------------------ kirim (yetkazib beruvchidan)
    def _craf_is_supply(self):
        self.ensure_one()
        return (self.state == "done" and self.location_id.usage == "supplier"
                and self.location_dest_id.usage == "internal"
                and not ("purchase_id" in self._fields and self.purchase_id))

    def _craf_supply_moves(self):
        return self.move_ids.filtered(lambda m: m.state == "done" and m.quantity > 0)

    def _craf_bill_missing(self):
        """Hisob-faktura uchun nima yetishmaydi (bo'sh — hammasi bor)."""
        self.ensure_one()
        missing = []
        if not self.partner_id:
            missing.append("yetkazib beruvchi")
        if any((m.craf_price or 0.0) <= 0 for m in self._craf_supply_moves()):
            missing.append("narx")
        return missing

    def _craf_day(self):
        return fields.Date.context_today(self, self.date_done) if self.date_done else fields.Date.context_today(self)

    def _craf_make_bill(self, day=None):
        """Yetkazib beruvchi hisob-fakturasi (darhol tasdiqlanadi). Narx yoki yetkazib beruvchi bo'lmasa — yo'q."""
        self.ensure_one()
        if self.craf_bill_id and self.craf_bill_id.state != "cancel":
            return self.craf_bill_id
        if not self._craf_is_supply() or self._craf_bill_missing():
            return self.env["account.move"]
        day = day or self._craf_day()
        partner = self.partner_id.commercial_partner_id
        bill = self.env["account.move"].sudo().create({
            "move_type": "in_invoice",
            "partner_id": partner.id,
            "invoice_date": day,
            "date": day,
            "ref": " · ".join(filter(None, [self.name, self.craf_vehicle])),
            "invoice_origin": self.name,
            "invoice_line_ids": [Command.create({
                "product_id": m.product_id.id,
                "name": m.product_id.display_name,
                "quantity": m.quantity,
                "product_uom_id": m.product_uom.id,
                "price_unit": m.craf_price,
                "tax_ids": [Command.clear()],
            }) for m in self._craf_supply_moves()],
        })
        bill.action_post()
        self.sudo().craf_bill_id = bill
        self.env["craf.pul"]._reconcile_partner(partner, "liability_payable")
        return bill

    def _craf_auto_bill(self, day=None):
        """Kirimni to'xtatmaydi: xato bo'lsa kirim hujjatiga yozib qo'yiladi."""
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                return self._craf_make_bill(day)
        except Exception as err:  # noqa: BLE001
            _logger.warning("Craf: %s hisob-fakturasi yaratilmadi: %s", self.name, err)
            self.sudo().message_post(body="Hisob-faktura avtomatik yaratilmadi: %s" % err)
        return self.env["account.move"]

    # ------------------------------------------------------------------ qaytarish (yetkazib beruvchiga)
    def _craf_bill_return(self, origin):
        """self — origin kirimining qaytarish hujjati. To'lanmagan va to'liq qaytarilgan bo'lsa hisob-faktura
        bekor qilinadi, aks holda qaytarish hisob-fakturasi (kredit) yoziladi."""
        self.ensure_one()
        bill = origin.craf_bill_id
        if not bill or bill.state != "posted":
            return self.env["account.move"]
        moves = self.move_ids.filtered(lambda m: m.state == "done" and m.quantity > 0)
        full = all(abs(m.quantity - (m.origin_returned_move_id.quantity or 0.0)) < 1e-6 for m in moves) \
            and set(moves.origin_returned_move_id.ids) == set(origin._craf_supply_moves().ids)
        partner = bill.partner_id
        if full and bill.payment_state == "not_paid":
            bill.sudo().button_draft()
            bill.sudo().button_cancel()
            origin.message_post(body="Qaytarildi — %s hisob-fakturasi bekor qilindi." % bill.name)
            return bill
        day = self._craf_day()
        refund = self.env["account.move"].sudo().create({
            "move_type": "in_refund",
            "partner_id": partner.id,
            "invoice_date": day,
            "date": day,
            "ref": "Qaytarish: %s" % " · ".join(filter(None, [self.name, origin.name])),
            "invoice_origin": self.name,
            "reversed_entry_id": bill.id,
            "invoice_line_ids": [Command.create({
                "product_id": m.product_id.id,
                "name": m.product_id.display_name,
                "quantity": m.quantity,
                "product_uom_id": m.product_uom.id,
                "price_unit": m.origin_returned_move_id.craf_price or 0.0,
                "tax_ids": [Command.clear()],
            }) for m in moves],
        })
        refund.action_post()
        self.sudo().craf_bill_id = refund
        self.env["craf.pul"]._reconcile_partner(partner, "liability_payable")
        return refund
