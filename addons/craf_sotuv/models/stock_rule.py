from odoo import models


class StockRule(models.Model):
    _inherit = "stock.rule"

    def _get_stock_move_values(self, product_id, product_qty, product_uom, location_dest_id, name, origin,
                               company_id, values):
        vals = super()._get_stock_move_values(
            product_id, product_qty, product_uom, location_dest_id, name, origin, company_id, values)
        # Sotuv joyi (Zavod / Parnik / Rohat): yetkazib berish shu joydan olinadi
        location_id = values.get("craf_location_id")
        if location_id and self.picking_type_id.code == "outgoing":
            vals["location_id"] = location_id
        return vals
