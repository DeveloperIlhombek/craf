"""Quyma (alyuminiy silindr) kunlik sanash: Press sexidagi stalba dona va kg.

Press varag'ida quyma sarfi yozilmaydi — kundalik sanash farqi pressga sarf hisoblanadi:
tasdiqlanganda Press sexidagi qoldiq sanalganga tenglashadi (kam bo'lsa — Press sexi → ishlab chiqarish, ya'ni sarf;
ko'p bo'lsa — tuzatish). Hujjat to'liq CRUD: tasdiqlangani «Tahrirlash» bilan qaytariladi (harakatlar bekor qilinadi).
"""
from datetime import datetime, time

from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt

from .craf_extrusion_shift import BILLET_CODES

STATES = [("draft", "Qoralama"), ("done", "Tasdiqlangan")]


class CrafBilletCount(models.Model):
    _name = "craf.billet.count"
    _description = "Quyma sanash"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Raqam", required=True, copy=False, readonly=True, default="Yangi", index=True)
    date = fields.Date("Sana", required=True, default=fields.Date.context_today, tracking=True, index=True,
                       help="Sanash shu kun oxiridagi (18:00) qoldiq deb yoziladi.")
    location_id = fields.Many2one("stock.location", "Joy", required=True, domain=[("usage", "=", "internal")],
                                  default=lambda self: self.env["craf.production.mixin"]._craf_loc("Press sexi"))
    line_ids = fields.One2many("craf.billet.count.line", "count_id", string="Quymalar", copy=True,
                               default=lambda self: self._default_lines())
    state = fields.Selection(STATES, string="Holat", default="draft", required=True, tracking=True, copy=False)
    move_ids = fields.Many2many("stock.move", string="Ombor harakatlari", copy=False, readonly=True)
    note = fields.Text("Izoh")
    total_kg = fields.Float("Jami, kg", compute="_compute_totals", store=True, digits=(16, 1))
    total_pcs = fields.Integer("Jami, dona", compute="_compute_totals", store=True)
    diff_kg = fields.Float("Farq, kg", compute="_compute_diff_kg", digits=(16, 1),
                           help="Sanalgan − dasturdagi: manfiy — pressga sarf")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)

    @api.model
    def _default_lines(self):
        products = self.env["product.product"].search([("default_code", "in", BILLET_CODES)], order="default_code desc")
        return [Command.create({"product_id": p.id}) for p in products]

    @api.depends("line_ids.qty_kg", "line_ids.pcs")
    def _compute_totals(self):
        for rec in self:
            rec.total_kg = sum(rec.line_ids.mapped("qty_kg"))
            rec.total_pcs = sum(rec.line_ids.mapped("pcs"))

    @api.depends("line_ids.diff_kg")
    def _compute_diff_kg(self):
        for rec in self:
            rec.diff_kg = sum(rec.line_ids.mapped("diff_kg"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Yangi") == "Yangi":
                vals["name"] = self.env["ir.sequence"].next_by_code("craf.billet.count") or "Yangi"
        return super().create(vals_list)

    def _moment(self):
        """Sanash vaqti: shu kun 18:00 (Toshkent) UTC da."""
        self.ensure_one()
        return datetime.combine(self.date, time(13, 0))

    def action_done(self):
        for rec in self.filtered(lambda r: r.state == "draft"):
            later = self.search([("id", "!=", rec.id), ("state", "=", "done"), ("date", ">", rec.date),
                                 ("location_id", "=", rec.location_id.id)], limit=1)
            if later:
                raise UserError("%s sanasidan keyin tasdiqlangan sanash bor (%s, %s). Avval uni tahrirlashga "
                                "qaytaring." % (rec.date.strftime("%d.%m.%Y"), later.name, later.date.strftime("%d.%m.%Y")))
            lines = rec.line_ids.filtered(lambda l: l.counted)
            if not lines:
                raise UserError("Sanalgan dona yoki kg ni kiriting.")
            lines.invalidate_recordset(["system_qty"])
            for line in lines:
                line.system_done = line.system_qty  # tasdiqlash paytidagi qoldiq qotadi
            Move = self.env["stock.move"]
            moves = Move
            parts = []
            for line in lines:
                diff = line.qty_kg - line.system_qty
                if abs(diff) < EPS:
                    parts.append("%s: farq yo'q" % line.product_id.name)
                    continue
                product = line.product_id
                if diff < 0:  # sanalgandan kam — pressga sarf
                    src, dst, label = rec.location_id, product.property_stock_production, "pressga sarf"
                else:  # ortiqcha — tuzatish
                    src, dst, label = product.property_stock_inventory, rec.location_id, "ortiqcha (tuzatish)"
                move = Move.create({
                    "product_id": product.id, "product_uom_qty": abs(diff), "product_uom": product.uom_id.id,
                    "location_id": src.id, "location_dest_id": dst.id, "is_inventory": diff > 0,
                    "origin": "%s: %s" % (rec.name, label), "company_id": rec.company_id.id,
                })
                move._action_confirm()
                move.quantity = abs(diff)
                move.picked = True
                move._action_done()
                move.write({"date": rec._moment()})
                move.move_line_ids.write({"date": rec._moment()})
                moves |= move
                parts.append("%s: %s kg (%s dona), %s %s kg" % (product.name, fmt(line.qty_kg, 1), fmt(line.pcs),
                                                                 label, fmt(abs(diff), 1)))
            rec.write({"state": "done", "move_ids": [Command.set(moves.ids)]})
            rec.message_post(body=Markup("<b>Sanash tasdiqlandi</b><br/>%s") % Markup("<br/>").join(parts))
        return True

    def action_reopen(self):
        """Tahrirlash: tasdiqlangan sanash harakatlari teskari harakat bilan bekor qilinadi, hujjat qoralamaga."""
        for rec in self.filtered(lambda r: r.state == "done"):
            Move = self.env["stock.move"]
            for move in rec.move_ids.filtered(lambda m: m.state == "done"):
                rev = Move.create({
                    "product_id": move.product_id.id, "product_uom_qty": move.quantity,
                    "product_uom": move.product_uom.id, "location_id": move.location_dest_id.id,
                    "location_dest_id": move.location_id.id, "is_inventory": move.is_inventory,
                    "origin": "%s (qaytarildi)" % rec.name, "company_id": move.company_id.id,
                })
                rev._action_confirm()
                rev.quantity = move.quantity
                rev.picked = True
                rev._action_done()
                rev.write({"date": move.date})
                rev.move_line_ids.write({"date": move.date})
            rec.write({"state": "draft", "move_ids": [Command.clear()]})
            rec.message_post(body=Markup("<b>Tahrirlash uchun qoralamaga qaytarildi</b> — ombor harakatlari bekor qilindi"))
        return True

    def unlink(self):
        if any(rec.state == "done" for rec in self):
            raise UserError("Tasdiqlangan sanashni o'chirishdan oldin «Tahrirlash» bilan qoralamaga qaytaring.")
        return super().unlink()


class CrafBilletCountLine(models.Model):
    _name = "craf.billet.count.line"
    _description = "Quyma sanash qatori"
    _order = "id"

    count_id = fields.Many2one("craf.billet.count", required=True, ondelete="cascade", index=True)
    product_id = fields.Many2one("product.product", "Quyma", required=True,
                                 domain=[("default_code", "in", BILLET_CODES)])
    system_qty = fields.Float("Dasturda, kg", compute="_compute_system_qty", digits=(16, 1),
                              help="Sanash vaqtigacha (shu sanashsiz) Press sexidagi qoldiq; tasdiqlanganda qotadi")
    system_done = fields.Float("Tasdiqlangandagi qoldiq, kg", digits=(16, 1), readonly=True, copy=False)
    pcs = fields.Integer("Sanaldi, dona")
    qty_kg = fields.Float("Sanaldi, kg", digits=(16, 1), help="Tortilgan og'irlik")
    counted = fields.Boolean(compute="_compute_diff")
    diff_kg = fields.Float("Farq, kg", compute="_compute_diff", digits=(16, 1),
                           help="Sanalgan − dasturdagi: manfiy — pressga sarf")
    avg_kg = fields.Float("1 dona o'rtacha, kg", compute="_compute_diff", digits=(16, 1))
    state = fields.Selection(related="count_id.state")

    @api.depends("product_id", "count_id.date", "count_id.location_id", "count_id.state", "system_done")
    def _compute_system_qty(self):
        for line in self:
            count = line.count_id
            if line.state == "done":
                line.system_qty = line.system_done
            elif line.product_id and count.date and count.location_id:
                line.system_qty = line.product_id.with_context(
                    location=count.location_id.id, to_date=datetime.combine(count.date, time(13, 0))).qty_available
            else:
                line.system_qty = 0.0

    @api.depends("qty_kg", "pcs", "system_qty")
    def _compute_diff(self):
        for line in self:
            line.counted = bool(line.qty_kg or line.pcs)
            line.diff_kg = line.qty_kg - line.system_qty if line.counted else 0.0
            line.avg_kg = line.qty_kg / line.pcs if line.pcs else 0.0
