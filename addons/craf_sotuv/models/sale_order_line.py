from odoo import api, fields, models




def packs_text(pcs, per_pack):
    """1045, 20 -> '52 pachka + 5 dona'."""
    pcs = int(round(pcs or 0))
    if not per_pack:
        return "%s dona" % pcs
    packs, rest = divmod(pcs, per_pack)
    if packs and rest:
        return "%s pachka + %s dona" % (packs, rest)
    if packs:
        return "%s pachka" % packs
    return "%s dona" % rest


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    craf_per_pack = fields.Integer(related="product_id.craf_pcs_per_pack", string="Dona / pachka")
    craf_packs = fields.Integer("Pachka", compute="_compute_craf_packs", store=True, readonly=False)
    craf_extra = fields.Integer("Dona (+)", compute="_compute_craf_packs", store=True, readonly=False,
                                help="Pachkadan tashqari donalar")
    craf_packs_text = fields.Char("Pachka + dona", compute="_compute_craf_packs_text")
    craf_kg = fields.Float("kg", digits=(16, 1), compute="_compute_craf_kg", store=True, aggregator="sum")
    craf_source_line = fields.Char("Yozilgan qator", copy=False)
    craf_pack_ids = fields.One2many("craf.pack", "sale_line_id", "Pachkalar (QR)", readonly=True)
    craf_date = fields.Datetime("Berilgan vaqt", related="order_id.craf_given_date", store=True)
    craf_location_id = fields.Many2one(related="order_id.craf_location_id", store=True, string="Qayerdan")

    @api.depends("product_uom_qty", "product_id.craf_pcs_per_pack")
    def _compute_craf_packs(self):
        for line in self:
            pcs = int(round(line.product_uom_qty or 0))
            per = line.product_id.craf_pcs_per_pack
            if per:
                line.craf_packs, line.craf_extra = divmod(pcs, per)
            else:
                line.craf_packs, line.craf_extra = 0, pcs

    @api.onchange("craf_packs", "craf_extra")
    def _onchange_craf_packs(self):
        for line in self:
            if not line.product_id:
                continue
            pcs = (line.craf_packs or 0) * (line.product_id.craf_pcs_per_pack or 0) + (line.craf_extra or 0)
            if pcs != int(round(line.product_uom_qty or 0)):
                line.product_uom_qty = pcs

    @api.depends("product_uom_qty", "product_id.craf_pcs_per_pack")
    def _compute_craf_packs_text(self):
        for line in self:
            line.craf_packs_text = packs_text(line.product_uom_qty, line.product_id.craf_pcs_per_pack) \
                if line.product_id and not line.display_type else ""

    @api.depends("product_uom_qty", "product_id.craf_kg_per_pc")
    def _compute_craf_kg(self):
        for line in self:
            line.craf_kg = (line.product_uom_qty or 0.0) * (line.product_id.craf_kg_per_pc or 0.0)

    def _prepare_procurement_values(self):
        values = super()._prepare_procurement_values()
        if self.order_id.craf_location_id:
            values["craf_location_id"] = self.order_id.craf_location_id.id
        return values
