from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        res = super()._action_done()
        # Ombordan qo'lda bajarilgan yetkazib berish ham yuklash holatini yangilaydi
        orders = self.filtered(lambda p: p.picking_type_code == "outgoing").sale_id
        for order in orders.filtered(lambda o: o.craf_load_state in ("draft", "queue", "loading")):
            if not order._craf_open_pickings():
                vals = {"craf_load_state": "done"}
                if not order.craf_given_date:
                    vals["craf_given_date"] = fields.Datetime.now()
                if not order.craf_loader_id:
                    vals["craf_loader_id"] = self.env.user.id
                order.write(vals)
        return res
