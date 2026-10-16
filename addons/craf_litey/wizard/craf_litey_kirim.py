from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_litey.models.craf_foundry_melt import parse_sum
from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt


class CrafLiteyKirim(models.TransientModel):
    _name = "craf.litey.kirim"
    _description = "Литейка: kirim (mashina)"

    date = fields.Date("Sana", required=True, default=fields.Date.context_today)
    partner_id = fields.Many2one("res.partner", string="Yetkazib beruvchi")
    vehicle = fields.Char("Mashina raqami")
    location_id = fields.Many2one(
        "stock.location", string="Qayerga", required=True, domain=[("usage", "=", "internal")],
        default=lambda self: self.env["craf.production.mixin"]._craf_loc("Литейка"))
    note = fields.Char("Izoh")
    line_ids = fields.One2many("craf.litey.kirim.line", "wizard_id", string="Materiallar")
    amount_total = fields.Float("Jami summa", compute="_compute_amount_total", digits=(16, 0))

    @api.depends("line_ids.amount")
    def _compute_amount_total(self):
        for wiz in self:
            wiz.amount_total = sum(wiz.line_ids.mapped("amount"))

    def action_confirm(self):
        self.ensure_one()
        picking = self._craf_create_picking()
        lines = self.line_ids.filtered(lambda l: l.product_id and l.qty > EPS)
        total = sum(l.qty for l in lines)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": "Kirim yozildi",
                "message": "%s: %s ta qator, %s kg → %s" % (picking.name, len(lines), fmt(total, 1),
                                                          self.location_id.name),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _craf_create_picking(self):
        """Kirim (WH/IN) hujjatini yaratib darhol bajaradi; o'tgan sana bo'lsa, harakatlar o'sha kunga yoziladi."""
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.product_id and l.qty > EPS)
        if not lines:
            raise UserError("Kamida bitta material va miqdor kiriting.")
        H = self.env["craf.litey.hisobot"]
        moment = H._moment(self.date)
        H._check_lock(lines.product_id, moment, "Kirim")
        warehouse = self.location_id.warehouse_id or self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1)
        ptype = warehouse.in_type_id
        if not ptype:
            raise UserError("Omborda kirim (Receipts) turi topilmadi.")
        supplier = ptype.default_location_src_id or self.env.ref("stock.stock_location_suppliers")
        origin = "Kirim" + (": %s" % self.vehicle if self.vehicle else "")
        picking = self.env["stock.picking"].create({
            "picking_type_id": ptype.id,
            "partner_id": self.partner_id.id or False,
            "location_id": supplier.id,
            "location_dest_id": self.location_id.id,
            "origin": origin,
            "craf_vehicle": self.vehicle or False,
            "move_ids": [Command.create({
                "product_id": l.product_id.id,
                "product_uom_qty": l.qty,
                "product_uom": l.product_id.uom_id.id,
                "location_id": supplier.id,
                "location_dest_id": self.location_id.id,
                "craf_price": l.price_unit,
                "origin": origin,
            }) for l in lines],
        })
        if self.note:
            picking.message_post(body=self.note)
        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.with_context(skip_backorder=True, picking_ids_not_to_backorder=picking.ids).button_validate()
        if picking.state != "done":
            raise UserError("Kirim bajarilmadi (%s): %s" % (picking.state, picking.name))
        if moment:
            picking.write({"date_done": moment, "scheduled_date": moment})
            picking.move_ids.write({"date": moment})
            picking.move_ids.move_line_ids.write({"date": moment})
        return picking


class CrafLiteyKirimLine(models.TransientModel):
    _name = "craf.litey.kirim.line"
    _description = "Литейка kirim qatori"

    wizard_id = fields.Many2one("craf.litey.kirim", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", string="Material", required=True,
                                 domain=[("craf_litey_seq", ">", 0), ("craf_litey_hidden", "=", False)])
    qty_text = fields.Char("Tortishlar", help="Masalan: 1381+2527")
    qty = fields.Float("Miqdor", digits=(16, 2))
    uom_name = fields.Char(related="product_id.uom_id.name", string="Birligi")
    price_unit = fields.Float("Narx (1 kg / 1 dona)", digits=(16, 2))
    amount = fields.Float("Summa", compute="_compute_amount", digits=(16, 0))

    @api.depends("qty", "price_unit")
    def _compute_amount(self):
        for line in self:
            line.amount = line.qty * line.price_unit

    @api.onchange("qty_text")
    def _onchange_qty_text(self):
        if self.qty_text:
            try:
                value = parse_sum(self.qty_text)
            except UserError as err:
                return {"warning": {"title": "Tortishlar", "message": str(err)}}
            if value is not None:
                self.qty = value

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("qty_text") and not vals.get("qty"):
                vals["qty"] = parse_sum(vals["qty_text"]) or 0.0
        return super().create(vals_list)
