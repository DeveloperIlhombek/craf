from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt

CHEMS = [("XA-03", "chem_ac20"), ("XA-04", "chem_cr51"), ("XA-05", "chem_ac52")]


class CrafChemTreatment(models.Model):
    _name = "craf.chem.treatment"
    _description = "Kimyoviy ishlov"
    _inherit = ["craf.production.mixin"]
    _order = "date desc, id desc"

    _craf_sequence_code = "craf.chem.treatment"
    _craf_stage = "chem"
    _craf_default_src = "Kimyoviy ishlov"
    _craf_default_dest = "Bo'yash sexi"

    location_dest_id = fields.Many2one(
        "stock.location", string="Profillar qayerga", required=True, domain=[("usage", "=", "internal")],
        default=lambda self: self._craf_loc(self._craf_default_dest))
    load_ids = fields.Many2many(
        "craf.basket.load", "craf_chem_treatment_load_rel", "treatment_id", "load_id", string="Korzinkalar",
        domain="[('state', '=', 'press'), ('shift_state', '=', 'done')]")
    chem_line_ids = fields.One2many("craf.chem.treatment.line", "treatment_id", string="Kimyo sarfi", copy=True)
    picking_ids = fields.Many2many("stock.picking", string="Ko'chirishlar", copy=False, readonly=True)

    basket_count = fields.Integer("Korzinkalar", compute="_compute_totals", store=True, aggregator="sum")
    pcs_total = fields.Integer("Profil, dona", compute="_compute_totals", store=True, aggregator="sum")
    kg_total = fields.Float("Profil, kg", compute="_compute_totals", store=True, digits=(16, 1), aggregator="sum")
    area_total = fields.Float("Maydon, m²", compute="_compute_totals", store=True, digits=(16, 1),
                              aggregator="sum")
    chem_kg = fields.Float("Kimyo, kg", compute="_compute_chem_kg", store=True, digits=(16, 2), aggregator="sum")

    @api.depends("load_ids.pcs_total", "load_ids.kg_theory", "load_ids.net_kg", "load_ids.area_m2")
    def _compute_totals(self):
        for rec in self:
            rec.basket_count = len(rec.load_ids)
            rec.pcs_total = sum(rec.load_ids.mapped("pcs_total"))
            rec.kg_total = sum(l.net_kg or l.kg_theory for l in rec.load_ids)
            rec.area_total = sum(rec.load_ids.mapped("area_m2"))

    @api.depends("chem_line_ids.qty")
    def _compute_chem_kg(self):
        for rec in self:
            rec.chem_kg = sum(rec.chem_line_ids.mapped("qty"))

    def action_add_waiting(self):
        """Kimyoga kutayotgan barcha korzinkalarni qo'shadi."""
        for rec in self.filtered(lambda r: r.state == "draft"):
            waiting = self.env["craf.basket.load"].search([("state", "=", "press"), ("shift_state", "=", "done")])
            rec.load_ids = [Command.link(l.id) for l in waiting]
        return True

    def action_fill_norms(self):
        norm = self.env["craf.mrp.norm"]._get_norm(self.env.company)
        for rec in self.filtered(lambda r: r.state == "draft"):
            lines = []
            for code, fname in CHEMS:
                product = rec._craf_product(code)
                if product:
                    qty = round(rec.area_total * norm[fname], 2)
                    lines.append(Command.create({"product_id": product.id, "qty_norm": qty, "qty": qty}))
            rec.chem_line_ids = [Command.clear()] + lines
        return True

    def _craf_consume(self, product, qty, location):
        """Xom-ashyoni ishlab chiqarishga sarflaydi (to'g'ridan-to'g'ri ombor harakati)."""
        dest = product.with_company(self.company_id).property_stock_production
        move = self.env["stock.move"].create({
            "product_id": product.id,
            "product_uom_qty": qty,
            "product_uom": product.uom_id.id,
            "location_id": location.id,
            "location_dest_id": dest.id,
            "origin": self.name,
            "company_id": self.company_id.id,
        })
        move._action_confirm()
        move._action_assign()
        move.quantity = qty
        move.picked = True
        move._action_done()
        return move

    def _craf_action_done(self):
        self.ensure_one()
        if not self.load_ids:
            raise UserError("Ishlov berilgan korzinkalarni tanlang.")
        bad = self.load_ids.filtered(lambda l: l.state != "press")
        if bad:
            raise UserError("Bu korzinkalar kimyoga kutmayapti: %s" % ", ".join(bad.mapped("display_name")))
        quantities = self.load_ids._product_quantities()
        needs = dict(quantities)
        for line in self.chem_line_ids.filtered(lambda l: l.qty > EPS):
            needs[line.product_id] = needs.get(line.product_id, 0.0) + line.qty
        self._craf_check_available(self.location_src_id, needs)
        # 1) Profillar: Kimyoviy ishlov → Bo'yash sexi
        warehouse = self.location_src_id.warehouse_id or self.env["stock.warehouse"].search(
            [("company_id", "=", self.company_id.id)], limit=1)
        picking = self.env["stock.picking"].create({
            "picking_type_id": warehouse.int_type_id.id,
            "location_id": self.location_src_id.id,
            "location_dest_id": self.location_dest_id.id,
            "origin": self.name,
            "move_ids": [Command.create({
                "product_id": product.id,
                "product_uom_qty": qty,
                "product_uom": product.uom_id.id,
                "location_id": self.location_src_id.id,
                "location_dest_id": self.location_dest_id.id,
            }) for product, qty in quantities.items()],
        })
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.with_context(skip_backorder=True, picking_ids_not_to_backorder=picking.ids).button_validate()
        if picking.state != "done":
            raise UserError("Profillarni ko'chirish bajarilmadi (%s)." % picking.state)
        self.picking_ids = [Command.link(picking.id)]
        # 2) Kimyo sarfi
        for line in self.chem_line_ids.filtered(lambda l: l.qty > EPS):
            line.move_id = self._craf_consume(line.product_id, line.qty, self.location_src_id)
        self.load_ids.write({"state": "kimyo", "treatment_id": self.id})
        self._craf_post_summary([
            Markup("<b>Kimyoviy ishlov tasdiqlandi</b> — %s") % picking.name,
            "Korzinkalar: %s (%s dona, %s kg) → %s" % (
                self.basket_count, fmt(self.pcs_total), fmt(self.kg_total, 1), self.location_dest_id.name),
            "Kimyo: %s" % (", ".join("%s %s kg" % (l.product_id.name, fmt(l.qty, 2)) for l in self.chem_line_ids) or "—"),
        ])

    def action_view_pickings(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("stock.action_picking_tree_all")
        action["domain"] = [("id", "in", self.picking_ids.ids)]
        return action


class CrafChemTreatmentLine(models.Model):
    _name = "craf.chem.treatment.line"
    _description = "Kimyo sarfi"
    _order = "id"

    treatment_id = fields.Many2one("craf.chem.treatment", required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one("product.product", string="Kimyo", required=True,
                                 domain=[("is_storable", "=", True), ("craf_section_id", "=", False)])
    qty_norm = fields.Float("Me'yor, kg", digits=(16, 2))
    qty = fields.Float("Sarf, kg", digits=(16, 2))
    uom_id = fields.Many2one(related="product_id.uom_id", string="Birlik")
    available_qty = fields.Float("Bor", compute="_compute_available_qty", digits=(16, 2))
    move_id = fields.Many2one("stock.move", "Ombor harakati", readonly=True, copy=False)
    state = fields.Selection(related="treatment_id.state")

    @api.depends("product_id", "treatment_id.location_src_id")
    def _compute_available_qty(self):
        Quant = self.env["stock.quant"]
        for line in self:
            loc = line.treatment_id.location_src_id
            line.available_qty = Quant._get_available_quantity(line.product_id, loc) if line.product_id and loc else 0.0
