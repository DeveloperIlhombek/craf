"""Литейка: qoldiqni sanash hujjati (inventarizatsiya).

Odoo 19 da inventarizatsiya alohida hujjat emas — har bir tuzatish `stock.move` (is_inventory) bo'lib
yoziladi. Bu hujjat ularni bitta raqam (SN-26-0001), sana, joy, mas'ul va qatorlar bilan jamlaydi:
ishchi telefonda sanaydi, qoralama saqlanadi, tasdiqlanganda farqlar Inventarizatsiya ga
«SN-26-0001» nomi bilan yoziladi.
"""
from datetime import time, timedelta

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_litey.models.craf_foundry_melt import parse_sum
from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt

COUNT_STATES = [("draft", "Qoralama"), ("done", "Tasdiqlangan"), ("cancel", "Bekor qilingan")]


class CrafLiteyCount(models.Model):
    _name = "craf.litey.count"
    _description = "Литейка: qoldiqni sanash"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Raqam", required=True, copy=False, readonly=True, default="Yangi", index=True)
    date = fields.Date("Sana", required=True, default=fields.Date.context_today, tracking=True,
                       help="Bugun — qoldiq hozirgi holatga tuzatiladi. O'tgan kun — shu kun oxiridagi (23:59) "
                            "qoldiq sanalgan deb hisoblanadi.")
    location_id = fields.Many2one(
        "stock.location", string="Joy", required=True, domain=[("usage", "=", "internal")], tracking=True,
        default=lambda self: self.env["craf.litey.hisobot"]._litey_location())
    user_id = fields.Many2one("res.users", string="Sanagan", default=lambda self: self.env.user, tracking=True)
    note = fields.Text("Izoh")
    state = fields.Selection(COUNT_STATES, string="Holat", default="draft", required=True, tracking=True,
                             copy=False, index=True)
    line_ids = fields.One2many("craf.litey.count.line", "count_id", string="Qatorlar", copy=True)
    move_ids = fields.Many2many("stock.move", "craf_litey_count_move_rel", "count_id", "move_id",
                                string="Ombor tuzatishlari", copy=False, readonly=True)
    done_date = fields.Datetime("Qoldiq vaqti", copy=False, readonly=True,
                                help="Sanalgan qoldiq qaysi vaqtga yozildi")
    counted_count = fields.Integer("Sanalgan", compute="_compute_summary")
    diff_count = fields.Integer("Farqli", compute="_compute_summary")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)

    @api.depends("line_ids.counted", "line_ids.diff_qty")
    def _compute_summary(self):
        for rec in self:
            counted = rec.line_ids.filtered("counted")
            rec.counted_count = len(counted)
            rec.diff_count = len(counted.filtered(lambda l: abs(l.diff_qty) > EPS))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == "Yangi":
                vals["name"] = self.env["ir.sequence"].next_by_code("craf.litey.count") or "Yangi"
        return super().create(vals_list)

    # ---------------------------------------------------------------- vaqt
    def _moment(self):
        """Qoldiq qaysi vaqtga sanalgan: bugun — hozir (None), o'tgan kun — o'sha kun 23:59."""
        self.ensure_one()
        return self.env["craf.litey.hisobot"]._moment(self.date, time(23, 59))

    def _system_qty(self, product, moment=None):
        ctx = {"location": self.location_id.id}
        if moment:
            ctx["to_date"] = moment
        return product.with_context(**ctx).qty_available

    # ---------------------------------------------------------------- tugmalar
    def action_done(self):
        for rec in self:
            rec._action_done()
        return True

    def _action_done(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError("%s allaqachon %s." % (self.name, dict(COUNT_STATES)[self.state].lower()))
        if not self.env.user.has_group("stock.group_stock_manager"):
            raise UserError("Sanash qoralama sifatida saqlandi. Qoldiqni tuzatish (tasdiqlash) uchun Inventarizatsiya "
                            "menejeri huquqi kerak — rahbar tasdiqlaydi.")
        lines = self.line_ids.filtered("counted")
        if not lines:
            raise UserError("Hech bir material sanalmagan: kamida bitta qatorga sanalgan miqdorni yozing.")
        if any(l.counted_qty < 0 for l in lines):
            raise UserError("Sanalgan miqdor manfiy bo'lishi mumkin emas.")
        H = self.env["craf.litey.hisobot"]
        moment = self._moment()
        H._check_lock(lines.product_id, moment, "Sanash %s" % self.name)
        Quant = self.env["stock.quant"].with_context(inventory_mode=True)
        quants = Quant.browse()
        for line in lines:
            system = self._system_qty(line.product_id, moment)
            diff = line.counted_qty - system
            line.write({"system_qty": system, "diff_qty": diff})
            if abs(diff) <= EPS:
                continue
            quant = Quant.search([("product_id", "=", line.product_id.id), ("location_id", "=", self.location_id.id),
                                  ("lot_id", "=", False), ("package_id", "=", False), ("owner_id", "=", False)],
                                 limit=1)
            if quant:
                quant.inventory_quantity = quant.quantity + diff
            else:
                quant = Quant.create({"product_id": line.product_id.id, "location_id": self.location_id.id,
                                      "inventory_quantity": diff})
            quants |= quant
        moves = self.env["stock.move"]
        if quants:
            before = self.env["stock.move"].search([], order="id desc", limit=1).id or 0
            quants.with_context(inventory_name=self.name)._apply_inventory(date=moment)
            moves = self.env["stock.move"].search([("id", ">", before), ("is_inventory", "=", True),
                                                   ("product_id", "in", quants.product_id.ids)])
            if moment:
                moves.write({"date": moment})
                moves.move_line_ids.write({"date": moment})
        self.write({"state": "done", "move_ids": [(6, 0, moves.ids)],
                    "done_date": moment or fields.Datetime.now()})
        changed = lines.filtered(lambda l: abs(l.diff_qty) > EPS)
        body = [Markup("<b>Sanash tasdiqlandi</b> — %s, %s ta material sanaldi, %s tasida farq bor") % (
            self.location_id.name, len(lines), len(changed))]
        for line in changed:
            body.append("• %s: tizimda %s, sanaldi %s (%s%s %s)" % (
                line.product_id.display_name, fmt(line.system_qty, 2 if line.system_qty % 1 else 0),
                fmt(line.counted_qty, 2 if line.counted_qty % 1 else 0), "+" if line.diff_qty > 0 else "",
                fmt(line.diff_qty, 2 if line.diff_qty % 1 else 0), line.uom_name or ""))
        self.message_post(body=Markup("<br/>").join(body))

    def action_cancel(self):
        if any(rec.state == "done" for rec in self):
            raise UserError("Tasdiqlangan sanashni bekor qilib bo'lmaydi: qoldiq allaqachon tuzatilgan. "
                            "Xato bo'lsa — yangi sanash qiling, u qoldiqni to'g'rilaydi.")
        self.write({"state": "cancel"})

    def action_draft(self):
        self.filtered(lambda r: r.state == "cancel").write({"state": "draft"})

    def unlink(self):
        if any(rec.state == "done" for rec in self):
            raise UserError("Tasdiqlangan sanashni o'chirib bo'lmaydi.")
        return super().unlink()

    def action_view_moves(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("stock.stock_move_action")
        action.update({"domain": [("id", "in", self.move_ids.ids)], "context": {"create": False}})
        return action


class CrafLiteyCountLine(models.Model):
    _name = "craf.litey.count.line"
    _description = "Sanash qatori"
    _order = "sequence, id"

    count_id = fields.Many2one("craf.litey.count", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one("product.product", string="Material", required=True,
                                 domain=[("is_storable", "=", True)])
    uom_name = fields.Char("Birlik", compute="_compute_uom_name")
    counted_text = fields.Char("Sanaldi (yozuv)", help="Bir necha tortish: 993+600+351")
    counted_qty = fields.Float("Sanaldi", digits=(16, 3))
    counted = fields.Boolean("Sanalgan", help="Belgilanmagan qator qoldiqqa ta'sir qilmaydi")
    system_qty = fields.Float("Tizimda", digits=(16, 3), help="Tasdiqlangan paytdagi tizim qoldig'i")
    diff_qty = fields.Float("Farq", digits=(16, 3))
    state = fields.Selection(related="count_id.state")

    _product_uniq = models.Constraint("UNIQUE(count_id, product_id)", "Bitta materialni bir sanashda ikki marta yozib bo'lmaydi.")

    @api.depends("product_id")
    def _compute_uom_name(self):
        H = self.env["craf.litey.hisobot"]
        for line in self:
            line.uom_name = H._uom(line.product_id) if line.product_id else ""

    @api.onchange("counted_text")
    def _onchange_counted_text(self):
        if self.counted_text:
            try:
                value = parse_sum(self.counted_text)
            except UserError as err:
                return {"warning": {"title": "Sanaldi", "message": str(err)}}
            if value is not None:
                self.counted_qty = value
                self.counted = True

    @api.model
    def _prepare(self, vals):
        if vals.get("counted_text"):
            vals["counted_qty"] = parse_sum(vals["counted_text"]) or 0.0
            vals.setdefault("counted", True)
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._prepare(dict(v)) for v in vals_list])

    def write(self, vals):
        return super().write(self._prepare(dict(vals)))
