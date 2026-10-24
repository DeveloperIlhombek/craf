from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS


class CrafStickerCount(models.TransientModel):
    _name = "craf.sticker.count"
    _description = "Stiker sanash"

    note = fields.Char("Izoh", default="Stiker sanash")
    line_ids = fields.One2many("craf.sticker.count.line", "wizard_id", string="Stikerlar")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ids = self.env.context.get("default_sticker_ids") or []
        stickers = self.env["craf.sticker"].browse(ids) if ids else self.env["craf.sticker"].search([])
        res["line_ids"] = [Command.create({"sticker_id": s.id, "qty_rolls": round(s.qty_rolls, 2),
                                           "counted_rolls": round(s.qty_rolls, 2)}) for s in stickers]
        return res

    def action_apply(self):
        self.ensure_one()
        counts = {l.sticker_id: l.counted_rolls for l in self.line_ids
                  if abs(l.counted_rolls - l.qty_rolls) > EPS}
        if not counts:
            raise UserError("Sanalgan qoldiq dasturdagidan farq qilmaydi.")
        self.env["craf.sticker"]._craf_apply_count(counts, self.note or "Stiker sanash")
        return {"type": "ir.actions.act_window_close"}


class CrafStickerCountLine(models.TransientModel):
    _name = "craf.sticker.count.line"
    _description = "Stiker sanash qatori"

    wizard_id = fields.Many2one("craf.sticker.count", required=True, ondelete="cascade")
    sticker_id = fields.Many2one("craf.sticker", string="Stiker", required=True, readonly=True)
    qty_rolls = fields.Float("Dasturda, rulon", digits=(16, 2), readonly=True)
    counted_rolls = fields.Float("Sanaldi, rulon", digits=(16, 2))
    diff_rolls = fields.Float("Farq", compute="_compute_diff", digits=(16, 2))

    @api.depends("qty_rolls", "counted_rolls")
    def _compute_diff(self):
        for line in self:
            line.diff_rolls = line.counted_rolls - line.qty_rolls
