from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt


class CrafBriket(models.Model):
    """Briketlash: yaroqsiz (brak) profil presslab, zichlab to'rtburchak briket qilinadi.
    Brak Chiqindi dan sarflanadi, briket Chiqindi ga kiradi va Литейка da qayta eritiladi."""
    _name = "craf.briket"
    _description = "Briketlash"
    _inherit = ["craf.production.mixin"]
    _order = "date desc, id desc"

    _craf_sequence_code = "craf.briket"
    _craf_stage = "press"
    _craf_default_src = "Chiqindi"

    input_product_id = fields.Many2one(
        "product.product", string="Nimadan (brak profil)", required=True,
        domain=[("craf_press_waste", "=", True)], default=lambda self: self._craf_product("PF-07"))
    input_qty = fields.Float("Sarf, kg", digits=(16, 1), tracking=True, aggregator="sum")
    input_available = fields.Float("Bor, kg", compute="_compute_input_available", digits=(16, 1))
    product_id = fields.Many2one(
        "product.product", string="Briket", required=True, domain=[("craf_press_waste", "=", True)],
        default=lambda self: self._craf_product("PF-16"))
    qty = fields.Float("Briket, kg", digits=(16, 1), tracking=True, aggregator="sum")
    location_dest_id = fields.Many2one(
        "stock.location", string="Briket qayerga", required=True, domain=[("usage", "=", "internal")],
        default=lambda self: self._craf_loc("Chiqindi"))
    loss_qty = fields.Float("Farq, kg", compute="_compute_loss", store=True, digits=(16, 1), aggregator="sum")

    @api.depends("input_product_id", "location_src_id")
    def _compute_input_available(self):
        Quant = self.env["stock.quant"]
        for rec in self:
            rec.input_available = Quant._get_available_quantity(rec.input_product_id, rec.location_src_id) \
                if rec.input_product_id and rec.location_src_id else 0.0

    @api.depends("input_qty", "qty")
    def _compute_loss(self):
        for rec in self:
            rec.loss_qty = rec.input_qty - rec.qty if rec.input_qty else 0.0

    @api.onchange("input_qty")
    def _onchange_input_qty(self):
        if self.input_qty and not self.qty:
            self.qty = self.input_qty

    def _craf_action_done(self):
        self.ensure_one()
        if self.input_qty <= EPS or self.qty <= EPS:
            raise UserError("Sarf va briket og'irligini (kg) kiriting.")
        if self.qty - self.input_qty > EPS:
            raise UserError("Briket (%s kg) sarfdan (%s kg) og'ir bo'lishi mumkin emas." % (
                fmt(self.qty, 1), fmt(self.input_qty, 1)))
        if self.input_product_id == self.product_id:
            raise UserError("Briket va sarf bir xil mahsulot bo'lishi mumkin emas.")
        self._craf_check_available(self.location_src_id, {self.input_product_id: self.input_qty})
        mo = self._craf_produce(self.product_id, self.qty, self.location_src_id, self.location_dest_id,
                                [(self.input_product_id, self.input_qty)])
        self._craf_post_summary([
            Markup("<b>Briketlash tasdiqlandi</b> — %s") % mo.name,
            "%s %s kg → %s %s kg (farq %s kg)" % (
                self.input_product_id.name, fmt(self.input_qty, 1), self.product_id.name, fmt(self.qty, 1),
                fmt(self.loss_qty, 1)),
        ])
