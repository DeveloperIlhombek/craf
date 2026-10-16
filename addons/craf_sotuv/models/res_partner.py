from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    craf_sale_line_count = fields.Integer("Berilgan", compute="_compute_craf_sale_line_count")

    def _compute_craf_sale_line_count(self):
        Line = self.env["sale.order.line"]
        data = Line._read_group(
            [("order_id.partner_id", "in", self.ids), ("order_id.state", "=", "sale"), ("display_type", "=", False)],
            ["order_partner_id"], ["__count"])
        counts = {partner.id: count for partner, count in data}
        for partner in self:
            partner.craf_sale_line_count = counts.get(partner.id, 0)

    def action_craf_sale_lines(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("craf_sotuv.action_craf_sale_lines")
        action["domain"] = [("order_partner_id", "=", self.id), ("order_id.state", "=", "sale"),
                            ("display_type", "=", False)]
        action["context"] = {"search_default_group_date": 0}
        action["name"] = "%s — berilgan mahsulotlar" % self.name
        return action
