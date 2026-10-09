from datetime import datetime, time

import pytz

from odoo import fields, models

C1_STATES = [("new", "1C ga kiritilmagan"), ("done", "1C ga kiritildi")]


class CrafProductionMixin(models.AbstractModel):
    _inherit = "craf.production.mixin"

    c1_state = fields.Selection(C1_STATES, string="1C", default="new", required=True, copy=False, index=True,
                                tracking=True)
    c1_date = fields.Datetime("1C ga kiritilgan vaqt", readonly=True, copy=False)
    c1_user_id = fields.Many2one("res.users", "1C ga kiritgan", readonly=True, copy=False)

    def action_done(self):
        res = super().action_done()
        today = fields.Date.context_today(self)
        for rec in self.filtered(lambda r: r.state == "done" and r.date and r.date != today):
            rec._craf_backdate_moves()
        return res

    def _craf_backdate_moves(self):
        """Kechikib kiritilgan hujjat: ombor harakatlari hujjat sanasiga (soat 12:00) yoziladi —
        kunlik hisobot va 1C bir xil kunni ko'rsatadi."""
        self.ensure_one()
        tz = pytz.timezone(self.env.user.tz or "Asia/Tashkent")
        when = tz.localize(datetime.combine(self.date, time(12))).astimezone(pytz.utc).replace(tzinfo=None)
        Move = self.env["stock.move"]
        moves = Move.search([("origin", "=", self.name), ("state", "=", "done")])
        if self.production_ids:
            moves |= Move.search(["|", ("raw_material_production_id", "in", self.production_ids.ids),
                                  ("production_id", "in", self.production_ids.ids), ("state", "=", "done")])
            self.production_ids.write({"date_finished": when})
        if "picking_ids" in self._fields and self.picking_ids:
            moves |= self.picking_ids.move_ids.filtered(lambda m: m.state == "done")
            self.picking_ids.write({"date_done": when})
        if moves:
            moves.write({"date": when})
            moves.move_line_ids.write({"date": when})

    def action_c1_done(self):
        self.filtered(lambda r: r.state == "done").write({
            "c1_state": "done", "c1_date": fields.Datetime.now(), "c1_user_id": self.env.user.id})
        return True

    def action_c1_reset(self):
        self.write({"c1_state": "new", "c1_date": False, "c1_user_id": False})
        return True
