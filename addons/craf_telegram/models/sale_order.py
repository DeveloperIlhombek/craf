import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def _craf_after_load_done(self, moves, photos, full):
        """Yuklovchi «Berildi» bosdi — savdo guruhiga mahsulotlar ro'yxati va mashina rasmi.
        Tranzaksiya saqlangandan keyin yuboriladi (xato bo'lsa — guruhga noto'g'ri xabar ketmaydi)."""
        res = super()._craf_after_load_done(moves, photos, full)
        TG = self.env["craf.telegram"].sudo()
        if not TG._sale_chat() or not TG._token():
            return res
        order_id, move_ids, photo_ids = self.id, moves.ids, photos.ids
        uid, context, registry = self.env.uid, dict(self.env.context), self.env.registry

        def _send():
            try:
                with registry.cursor() as cr:
                    env = api.Environment(cr, uid, context)
                    env["craf.telegram"].sudo().send_sale_loaded(
                        env["sale.order"].browse(order_id), env["stock.move"].browse(move_ids),
                        env["ir.attachment"].browse(photo_ids), full)
            except Exception:  # noqa: BLE001 — Telegram xatosi yuklashni buzmasin
                _logger.exception("Telegram: savdo guruhiga %s yuborilmadi", order_id)

        self.env.cr.postcommit.add(_send)
        return res
