from collections import defaultdict

from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt


class CrafFoundryMelt(models.Model):
    _name = "craf.foundry.melt"
    _description = "Plavka (Литейка)"
    _inherit = ["craf.production.mixin"]
    _order = "date desc, id desc"

    _craf_sequence_code = "craf.foundry.melt"
    _craf_stage = "foundry"
    _craf_default_src = "Литейка"
    _craf_default_dest = "Press sexi"

    billet_product_id = fields.Many2one(
        "product.product", string="Quyma (mahsulot)", required=True,
        default=lambda self: self._craf_product("XA-09"))
    billet_tmpl_id = fields.Many2one(related="billet_product_id.product_tmpl_id")
    bom_id = fields.Many2one(
        "mrp.bom", string="Shixta retsepti", domain="[('product_tmpl_id', '=', billet_tmpl_id)]",
        default=lambda self: self._default_bom())
    plan_qty = fields.Float("Reja: quyma, kg", default=2000.0, digits=(16, 1))
    location_dest_id = fields.Many2one(
        "stock.location", string="Quyma qayerga", required=True, domain=[("usage", "=", "internal")],
        default=lambda self: self._craf_loc(self._craf_default_dest))
    line_ids = fields.One2many("craf.foundry.melt.line", "melt_id", string="Shixta", copy=True)
    temperature = fields.Integer("Harorat, °C", default=740, aggregator="avg")

    billet_qty = fields.Float("Quyma chiqdi, kg", digits=(16, 1), tracking=True, aggregator="sum")
    slag_product_id = fields.Many2one(
        "product.product", string="Шлак (mahsulot)", default=lambda self: self._craf_product("PF-14"))
    slag_qty = fields.Float("Шлак, kg", digits=(16, 1), aggregator="sum")

    charge_total = fields.Float("Jami shixta, kg", compute="_compute_kpi", store=True, digits=(16, 1),
                                aggregator="sum")
    charge_metal = fields.Float("Metall shixta, kg", compute="_compute_kpi", store=True, digits=(16, 1),
                                aggregator="sum")
    burn_loss_qty = fields.Float("Угар, kg", compute="_compute_kpi", store=True, digits=(16, 1),
                                 aggregator="sum")
    burn_loss_pct = fields.Float("Угар, %", compute="_compute_kpi", store=True, digits=(16, 2),
                                 aggregator="avg")
    yield_pct = fields.Float("Chiqish, %", compute="_compute_kpi", store=True, digits=(16, 1),
                             aggregator="avg")
    balance_text = fields.Char("Balans", compute="_compute_balance_text")

    @api.model
    def _default_bom(self):
        billet = self._craf_product("XA-09")
        if not billet:
            return self.env["mrp.bom"]
        return self.env["mrp.bom"].search([("product_tmpl_id", "=", billet.product_tmpl_id.id)], limit=1)

    @api.depends("line_ids.qty", "line_ids.is_metal", "billet_qty", "slag_qty")
    def _compute_kpi(self):
        for melt in self:
            total = sum(melt.line_ids.mapped("qty"))
            metal = sum(melt.line_ids.filtered("is_metal").mapped("qty"))
            loss = metal - melt.billet_qty - melt.slag_qty if melt.billet_qty else 0.0
            melt.charge_total = total
            melt.charge_metal = metal
            melt.burn_loss_qty = loss
            melt.burn_loss_pct = loss / metal * 100.0 if metal and melt.billet_qty else 0.0
            melt.yield_pct = melt.billet_qty / metal * 100.0 if metal else 0.0

    @api.depends("charge_metal", "billet_qty", "slag_qty", "burn_loss_qty")
    def _compute_balance_text(self):
        for melt in self:
            metal, loss = melt.charge_metal, melt.burn_loss_qty
            if metal:
                melt.balance_text = "%s kg metall = %s quyma + %s шлак + %s угар" % (
                    fmt(metal), fmt(melt.billet_qty), fmt(melt.slag_qty), fmt(loss, 1))
            else:
                melt.balance_text = False

    def action_load_recipe(self):
        for melt in self:
            if melt.state != "draft":
                continue
            bom = melt.bom_id or melt._default_bom()
            if not bom:
                raise UserError("Quyma uchun shixta retsepti (BoM) topilmadi.")
            if melt.plan_qty <= 0:
                raise UserError("Reja quyma miqdorini kiriting.")
            factor = melt.plan_qty / (bom.product_qty or 1.0)
            melt.write({
                "bom_id": bom.id,
                "line_ids": [Command.clear()] + [Command.create({
                    "sequence": i,
                    "product_id": line.product_id.id,
                    "qty_plan": round(line.product_qty * factor, 1),
                    "qty": round(line.product_qty * factor, 1),
                }) for i, line in enumerate(bom.bom_line_ids, 1)],
            })
        return True

    def _craf_action_done(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.qty > EPS)
        if not lines:
            raise UserError("Shixta tarkibini kiriting (yoki 'Retseptdan to'ldirish' ni bosing).")
        if self.billet_qty <= EPS:
            raise UserError("Chiqqan quyma miqdorini (kg) kiriting.")
        if self.billet_qty + self.slag_qty > self.charge_metal + EPS:
            raise UserError("Quyma + шлак (%s kg) metall shixtadan (%s kg) ko'p bo'lishi mumkin emas." % (
                fmt(self.billet_qty + self.slag_qty, 1), fmt(self.charge_metal, 1)))
        needs = defaultdict(float)
        for line in lines:
            needs[line.product_id] += line.qty
        self._craf_check_available(self.location_src_id, needs)
        byproducts = []
        if self.slag_qty > EPS:
            if not self.slag_product_id:
                raise UserError("Шлак mahsulotini tanlang.")
            byproducts.append((self.slag_product_id, self.slag_qty, self.waste_location_id))
        mo = self._craf_produce(self.billet_product_id, self.billet_qty, self.location_src_id,
                                self.location_dest_id, list(needs.items()), byproducts)
        self._craf_post_summary([
            Markup("<b>Plavka tasdiqlandi</b> — %s") % mo.name,
            "Shixta: %s kg (metall %s kg)" % (fmt(self.charge_total, 1), fmt(self.charge_metal, 1)),
            "Quyma: %s kg → %s" % (fmt(self.billet_qty, 1), self.location_dest_id.name),
            "Шлак: %s kg, угар: %s kg (%s%%)" % (
                fmt(self.slag_qty, 1), fmt(self.burn_loss_qty, 1), fmt(self.burn_loss_pct, 2)),
        ])


class CrafFoundryMeltLine(models.Model):
    _name = "craf.foundry.melt.line"
    _description = "Plavka shixtasi"
    _order = "sequence, id"

    melt_id = fields.Many2one("craf.foundry.melt", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one("product.product", string="Material", required=True,
                                 domain=[("is_storable", "=", True), ("craf_section_id", "=", False)])
    uom_id = fields.Many2one(related="product_id.uom_id", string="Birlik")
    is_metal = fields.Boolean("Metall", compute="_compute_is_metal", store=True, readonly=False)
    qty_plan = fields.Float("Reja, kg", digits=(16, 1))
    qty = fields.Float("Haqiqiy, kg", digits=(16, 1))
    available_qty = fields.Float("Bor", compute="_compute_available_qty", digits=(16, 1))
    state = fields.Selection(related="melt_id.state")

    @api.depends("product_id")
    def _compute_is_metal(self):
        for line in self:
            line.is_metal = not line.product_id.craf_not_metal

    @api.depends("product_id", "melt_id.location_src_id")
    def _compute_available_qty(self):
        Quant = self.env["stock.quant"]
        for line in self:
            if line.product_id and line.melt_id.location_src_id:
                line.available_qty = Quant._get_available_quantity(line.product_id, line.melt_id.location_src_id)
            else:
                line.available_qty = 0.0
