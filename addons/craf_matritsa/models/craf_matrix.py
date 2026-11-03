from odoo import api, fields, models

MATRIX_STATES = [("ok", "Yaroqli"), ("broken", "Yaroqsiz")]


class CrafMatrix(models.Model):
    """Matritsa (qolip): har biri raqami bilan; qaysi profil (kesim) uchun va holati."""
    _name = "craf.matrix"
    _description = "Matritsa (qolip)"
    _inherit = ["mail.thread"]
    _order = "section_id, name"

    name = fields.Char("Raqami", required=True, tracking=True)
    section_id = fields.Many2one("craf.profile.section", "Profil (kesim)", required=True, index=True, tracking=True)
    state = fields.Selection(MATRIX_STATES, "Holati", required=True, default="ok", index=True, tracking=True)
    broken_date = fields.Date("Yaroqsiz bo'lgan sana", copy=False)
    broken_note = fields.Char("Yaroqsizlik sababi", copy=False, tracking=True)
    note = fields.Char("Izoh")
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint("unique(name)", "Bunday raqamli matritsa bor.")

    @api.depends("name", "section_id.name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s · %s" % (rec.name, rec.section_id.name) if rec.section_id else rec.name

    def action_mark_broken(self, note=False):
        self.write({"state": "broken", "broken_date": fields.Date.context_today(self),
                    "broken_note": note or False})
        return True

    def action_mark_ok(self):
        self.write({"state": "ok", "broken_date": False, "broken_note": False})
        return True


class CrafProfileSection(models.Model):
    _inherit = "craf.profile.section"

    matrix_ids = fields.One2many("craf.matrix", "section_id", "Matritsalar")
    matrix_count = fields.Integer("Matritsalar soni", compute="_compute_matrix_counts")
    matrix_ok_count = fields.Integer("Yaroqli matritsa", compute="_compute_matrix_counts")

    def _compute_matrix_counts(self):
        groups = self.env["craf.matrix"]._read_group([("section_id", "in", self.ids)], ["section_id", "state"],
                                                     ["__count"])
        counts = {}
        for section, state, count in groups:
            counts.setdefault(section.id, {})[state] = count
        for rec in self:
            c = counts.get(rec.id, {})
            rec.matrix_count = sum(c.values())
            rec.matrix_ok_count = c.get("ok", 0)
