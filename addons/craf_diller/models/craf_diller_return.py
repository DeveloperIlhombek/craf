"""Qaytarish so'rovi: diller ochadi, sotuvchi tasdiqlaydi, mahsulot kelganda mavjud _craf_return ishlaydi."""
from odoo import api, fields, models

from odoo.addons.craf_sotuv.models.sale_order_line import packs_text

REASONS = [("brak", "Brak"), ("ortiqcha", "Ortiqcha"), ("notogri", "Noto'g'ri mahsulot")]
STATES = [("new", "Yangi"), ("approved", "Tasdiqlandi — olib keladi"), ("done", "Qabul qilindi"),
          ("rejected", "Rad etildi")]


class CrafDillerReturn(models.Model):
    _name = "craf.diller.return"
    _description = "Diller qaytarish so'rovi"
    _inherit = ["mail.thread"]
    _order = "id desc"

    name = fields.Char("Raqam", required=True, copy=False, readonly=True, default="Yangi")
    order_id = fields.Many2one("sale.order", "Buyurtma", required=True, readonly=True, index=True)
    partner_id = fields.Many2one("res.partner", "Diller", required=True, readonly=True, index=True)
    user_id = fields.Many2one("res.users", "So'ragan", readonly=True)
    state = fields.Selection(STATES, "Holat", default="new", required=True, tracking=True, readonly=True)
    reason = fields.Selection(REASONS, "Sabab", required=True, readonly=True)
    note = fields.Char("Izoh", readonly=True)
    location_id = fields.Many2one("stock.location", "Qayerga olib keladi", domain=[("craf_sale_point", "=", True)],
                                  required=True)
    photo_ids = fields.Many2many("ir.attachment", string="Rasmlar", readonly=True)
    line_ids = fields.One2many("craf.diller.return.line", "return_id", "Qatorlar", readonly=True)
    reject_note = fields.Char("Rad etish sababi")
    picking_id = fields.Many2one("stock.picking", "Kirim hujjati", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec.name = "QS-%05d" % rec.id
        return records

    def _push(self, title, body):
        self.env["craf.diller.notice"].sudo()._craf_push(self.partner_id, title, body, order=self.order_id)

    def action_approve(self):
        for rec in self.filtered(lambda r: r.state == "new"):
            rec.state = "approved"
            rec._push("Qaytarish tasdiqlandi", "%s: mahsulotni %s ga olib keling." % (
                rec.name, rec.location_id._craf_sale_label()))
        return True

    def action_reject(self):
        for rec in self.filtered(lambda r: r.state in ("new", "approved")):
            rec.state = "rejected"
            rec._push("Qaytarish rad etildi", "%s%s." % (rec.name, ": %s" % rec.reject_note if rec.reject_note else ""))
        return True

    def action_receive(self):
        """Mahsulot jismonan keldi: kirim, qaytarish hisob-fakturasi, qarz kamayadi."""
        for rec in self.filtered(lambda r: r.state == "approved"):
            label = dict(REASONS).get(rec.reason)
            quantities = {line.sale_line_id: line.qty for line in rec.line_ids}
            picking = rec.order_id.sudo()._craf_return(rec.location_id, quantities, "%s — %s" % (rec.name, label))
            rec.write({"state": "done", "picking_id": picking.id})
            rec._push("Qaytarish qabul qilindi", "%s qabul qilindi, qarz yangilandi." % rec.name)
        return True


class CrafDillerReturnLine(models.Model):
    _name = "craf.diller.return.line"
    _description = "Qaytarish so'rovi qatori"

    return_id = fields.Many2one("craf.diller.return", required=True, ondelete="cascade", index=True)
    sale_line_id = fields.Many2one("sale.order.line", "Buyurtma qatori", required=True)
    product_id = fields.Many2one(related="sale_line_id.product_id", string="Mahsulot")
    qty = fields.Float("Dona", digits=(16, 0), required=True)
    qty_text = fields.Char("Miqdor", compute="_compute_qty_text")

    @api.depends("qty", "product_id.craf_pcs_per_pack")
    def _compute_qty_text(self):
        for line in self:
            line.qty_text = packs_text(line.qty, line.product_id.craf_pcs_per_pack)
