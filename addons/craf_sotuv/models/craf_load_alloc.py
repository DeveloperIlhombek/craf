from odoo import fields, models


class CrafLoadAlloc(models.Model):
    """Yuklovchi rejasi: buyurtma qatori (ombor harakati) qaysi joydan qancha yuklandi.

    «Berildi» bosilganda har joy uchun alohida ombor harakati yaratiladi va qoldiq shu joydan ayriladi."""
    _name = "craf.load.alloc"
    _description = "Yuklash: joy bo'yicha miqdor"

    move_id = fields.Many2one("stock.move", "Ombor harakati", required=True, ondelete="cascade", index=True)
    order_id = fields.Many2one("sale.order", "Buyurtma", index=True, ondelete="cascade")
    product_id = fields.Many2one(related="move_id.product_id", string="Mahsulot")
    location_id = fields.Many2one("stock.location", "Joy", required=True, domain=[("usage", "=", "internal")])
    qty = fields.Float("Miqdor (dona)", digits=(16, 0), required=True, default=0.0)
    user_id = fields.Many2one("res.users", "Yuklovchi", default=lambda self: self.env.user)

    _move_loc_uniq = models.Constraint("UNIQUE(move_id, location_id)", "Bitta qator uchun bitta joy bir marta yoziladi.")
