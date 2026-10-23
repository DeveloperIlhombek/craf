from odoo import api, fields, models
from odoo.exceptions import ValidationError


def hhmm(value):
    """8.5 → «08:30»."""
    minutes = int(round((value or 0.0) * 60)) % (24 * 60)
    return "%02d:%02d" % (minutes // 60, minutes % 60)


class CrafPressSmena(models.Model):
    """Press smenasi (masalan, «Kunduzgi smena», 08:00–20:00, Press №1, mas'ul Yo'ldosh). Bir marta kiritiladi va
    doimiy ishlaydi; press varag'ida faqat smena tanlanadi — press, mas'ul va ish vaqti shundan olinadi."""
    _name = "craf.press.smena"
    _description = "Press smenasi (jamoa)"
    _order = "sequence, id"

    name = fields.Char("Smena", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    time_from = fields.Float("Boshlanishi", default=8.0, help="Toshkent vaqti, masalan 08:00")
    time_to = fields.Float("Tugashi", default=20.0, help="Yarim tundan o'tsa ham bo'ladi, masalan 20:00 – 08:00")
    duration = fields.Float("Ish vaqti, soat", compute="_compute_duration", store=True)
    time_text = fields.Char("Ish vaqti", compute="_compute_duration", store=True)
    equipment_id = fields.Many2one("maintenance.equipment", "Press", domain=[("craf_stage", "=", "press")])
    responsible_id = fields.Many2one("hr.employee", "Mas'ul shaxs")
    worker_ids = fields.Many2many("hr.employee", "craf_press_smena_worker_rel", "smena_id", "employee_id",
                                  string="Ishchilar")
    worker_count = fields.Integer("Ishchilar soni", compute="_compute_worker_count")
    note = fields.Char("Izoh")

    _name_uniq = models.Constraint("UNIQUE(name)", "Smena nomi takrorlanmasligi kerak.")

    @api.depends("time_from", "time_to")
    def _compute_duration(self):
        for rec in self:
            hours = (rec.time_to - rec.time_from) % 24  # tungi smena: 20:00 → 08:00 = 12 soat
            rec.duration = hours or 24.0
            rec.time_text = "%s–%s" % (hhmm(rec.time_from), hhmm(rec.time_to))

    @api.depends("worker_ids")
    def _compute_worker_count(self):
        for rec in self:
            rec.worker_count = len(rec.worker_ids)

    @api.constrains("time_from", "time_to")
    def _check_time(self):
        for rec in self:
            if not (0 <= rec.time_from < 24 and 0 <= rec.time_to < 24):
                raise ValidationError("Ish vaqti 00:00 dan 23:59 gacha bo'ladi.")

    @api.depends("name", "responsible_id", "time_text")
    def _compute_display_name(self):
        for rec in self:
            parts = [rec.name or ""]
            if rec.time_text:
                parts.append("(%s)" % rec.time_text)
            if rec.responsible_id:
                parts.append("— %s" % rec.responsible_id.name)
            rec.display_name = " ".join(parts)
