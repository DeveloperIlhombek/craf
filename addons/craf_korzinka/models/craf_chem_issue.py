"""Kislota / kaustik soda / bo'yash materiallari olish: xodim ombordan qancha olib ketganini bir marta yozadi
(kislota — kimyo xodimi, kaustik soda — matritsa xodimi, bo'yoq, salofan va lenta — bo'yash xodimi).

Kimyo sarfi har bir kimyoviy ishlovda kuzatilmaydi (2026-11-03 qarori) — olib ketilgan miqdor shu zahoti
sarf hisoblanadi: Xom-ashyo omboridan ishlab chiqarishga (sarfga) yechiladi.
"""
from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt

CHEM_CODES = ("XA-03", "XA-04", "XA-05")
ISSUE_KINDS = [("kislota", "Kislota"), ("soda", "Kaustik soda"), ("boyash", "Bo'yash materiallari")]
KIND_CODES = {"kislota": CHEM_CODES, "soda": ("XA-10",)}
# bo'yash: rang kartochkalaridagi kukun bo'yoqlar + rangsiz kukunlar, salofan (plyonka) va lenta; stiker — avtomatik
PAINT_CODES = ("XA-01", "XA-11", "XA-12")
PACK_CODES = ("QM-01", "QM-02")


class CrafChemIssue(models.Model):
    _name = "craf.chem.issue"
    _description = "Ombordan olingan material (kislota, kaustik soda, bo'yash materiallari)"
    _inherit = ["craf.production.mixin"]
    _order = "date desc, id desc"

    _craf_sequence_code = "craf.chem.issue"
    _craf_stage = "chem"
    _craf_default_src = "Xom-ashyo ombori"

    kind = fields.Selection(ISSUE_KINDS, "Nima", required=True, default="kislota", index=True, tracking=True)
    line_ids = fields.One2many("craf.chem.issue.line", "issue_id", string="Olingan", copy=True)
    qty_total = fields.Float("Jami, kg", compute="_compute_qty_total", store=True, digits=(16, 2), aggregator="sum")
    content = fields.Char("Nima olindi", compute="_compute_qty_total", store=True)

    @api.depends("line_ids.qty", "line_ids.product_id")
    def _compute_qty_total(self):
        for rec in self:
            lines = rec.line_ids.filtered(lambda l: l.qty > EPS)
            rec.qty_total = sum(lines.mapped("qty"))
            rec.content = ", ".join("%s %s %s" % (l.product_id.name, fmt(l.qty, 2), l.product_id.uom_id.name)
                                    for l in lines) or False

    @api.model
    def _craf_chem_products(self, kind="kislota"):
        Product = self.env["product.product"]
        if kind == "boyash":
            # bo'yoq (kukun) sarfi — kunlik bo'yash yozuvida (rang bo'yicha); bu yerda salofan va lenta
            return Product.search([("default_code", "in", PACK_CODES)], order="default_code")
        products = Product
        for code in KIND_CODES.get(kind, CHEM_CODES):
            products |= self._craf_product(code)
        return products

    def _craf_take_plan(self, product, qty):
        """[(joy, miqdor)] — avval «Sarf qayerdan» joyidan, yetmasa boshqa ichki joylardan (ko'pi birinchi)."""
        Quant = self.env["stock.quant"]
        by_loc = {}
        for quant in Quant.search([("product_id", "=", product.id), ("location_id.usage", "=", "internal"),
                                   ("quantity", ">", 0), ("company_id", "in", [self.company_id.id, False])]):
            by_loc[quant.location_id] = by_loc.get(quant.location_id, 0.0) + quant.quantity
        plan, left = [], qty
        for loc, avail in sorted(by_loc.items(), key=lambda kv: (kv[0] != self.location_src_id, -kv[1])):
            take = min(left, avail)
            if take > EPS:
                plan.append((loc, take))
                left -= take
            if left <= EPS:
                break
        if left > EPS:
            raise UserError("%s: zavodda yetarli emas — kerak %s, bor %s %s." % (
                product.display_name, fmt(qty, 2), fmt(qty - left, 2), product.uom_id.name))
        return plan

    def _craf_action_done(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.qty > EPS)
        if not lines:
            raise UserError("Olingan miqdorni yozing.")
        plans = {line: self._craf_take_plan(line.product_id, line.qty) for line in lines}  # avval hammasi tekshiriladi
        for line in lines:
            dest = line.product_id.with_company(self.company_id).property_stock_production
            for loc, qty in plans[line]:
                move = self.env["stock.move"].create({
                    "product_id": line.product_id.id,
                    "product_uom_qty": qty,
                    "product_uom": line.product_id.uom_id.id,
                    "location_id": loc.id,
                    "location_dest_id": dest.id,
                    "origin": self.name,
                    "company_id": self.company_id.id,
                })
                move._action_confirm()
                move._action_assign()
                move.quantity = qty
                move.picked = True
                move._action_done()
                line.move_id = line.move_id or move
        self._craf_post_summary([
            Markup("<b>%s olindi</b> — %s") % (dict(ISSUE_KINDS)[self.kind], self.location_src_id.name),
            self.content or "—",
        ])

    def action_add_chems(self):
        """Shu turdagi (kislota yoki soda) mahsulot qatorlarini qo'shadi (miqdorini xodim yozadi)."""
        for rec in self.filtered(lambda r: r.state == "draft"):
            have = rec.line_ids.product_id
            rec.line_ids = [Command.create({"product_id": p.id}) for p in rec._craf_chem_products(rec.kind) - have]
        return True


class CrafChemIssueLine(models.Model):
    _name = "craf.chem.issue.line"
    _description = "Olingan kislota"
    _order = "id"

    issue_id = fields.Many2one("craf.chem.issue", required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one("product.product", string="Kislota", required=True,
                                 domain=[("is_storable", "=", True), ("craf_section_id", "=", False)])
    qty = fields.Float("Olindi, kg", digits=(16, 2))
    uom_id = fields.Many2one(related="product_id.uom_id", string="Birlik")
    available_qty = fields.Float("Omborda", compute="_compute_available_qty", digits=(16, 2))
    move_id = fields.Many2one("stock.move", "Ombor harakati", readonly=True, copy=False)
    state = fields.Selection(related="issue_id.state")

    @api.depends("product_id", "issue_id.location_src_id")
    def _compute_available_qty(self):
        Quant = self.env["stock.quant"]
        for line in self:
            loc = line.issue_id.location_src_id
            line.available_qty = Quant._get_available_quantity(line.product_id, loc) if line.product_id and loc else 0.0

    @api.constrains("qty")
    def _check_qty(self):
        for line in self:
            if line.qty < 0:
                raise ValidationError("Miqdor manfiy bo'lishi mumkin emas.")
