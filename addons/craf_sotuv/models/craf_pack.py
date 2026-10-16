from odoo import api, fields, models

PACK_STATES = [("stock", "Omborda"), ("sold", "Sotildi")]


class CrafPack(models.Model):
    _inherit = "craf.pack"

    sale_line_id = fields.Many2one("sale.order.line", "Sotuv qatori", index=True, copy=False, readonly=True)
    sale_order_id = fields.Many2one(related="sale_line_id.order_id", store=True, string="Sotuv")
    sold_partner_id = fields.Many2one(related="sale_line_id.order_id.partner_id", store=True, string="Mijoz")
    sold_date = fields.Datetime("Sotilgan vaqt", copy=False, readonly=True)
    load_move_id = fields.Many2one("stock.move", "Yuklanayotgan qator", copy=False, readonly=True, index=True,
                                   help="Yuklovchi skanerlagan, hali «Berildi» qilinmagan.")
    craf_state = fields.Selection(PACK_STATES, string="Holat", compute="_compute_craf_state", store=True)

    @api.depends("sale_line_id")
    def _compute_craf_state(self):
        for pack in self:
            pack.craf_state = "sold" if pack.sale_line_id else "stock"
