from collections import defaultdict

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt

from .craf_sticker import ADHESION


class CrafColor(models.Model):
    _inherit = "craf.color"

    craf_sticker_adhesion = fields.Selection(
        ADHESION, string="Stiker yopishqoqligi", default="medium",
        help="Shu rangdagi profilga qaysi stiker ketadi: Antratsit (J306) — High (80 mic), qolganlari — Medium.")


class CrafPaintBatch(models.Model):
    _inherit = "craf.paint.batch"

    sticker_logo_id = fields.Many2one(
        "craf.sticker.logo", string="Stiker logosi", default=lambda self: self._craf_default_sticker_logo(),
        help="Kesim seriyasi logoga mos bo'lmagan profillar uchun (ALUSAM, CRAF seriyali kesimlar o'z logosini "
             "oladi).")
    sticker_line_ids = fields.One2many("craf.paint.sticker.line", "batch_id", string="Stiker sarfi", copy=False)
    sticker_m = fields.Float("Stiker, m", compute="_compute_sticker_total", store=True, digits=(16, 0),
                             aggregator="sum")
    sticker_rolls = fields.Float("Stiker, rulon", compute="_compute_sticker_total", store=True, digits=(16, 2),
                                 aggregator="sum")
    sticker_missing = fields.Char("Stiker normasi yo'q", compute="_compute_sticker_missing")

    @api.model
    def _craf_default_sticker_logo(self):
        Logo = self.env["craf.sticker.logo"]
        return Logo.search([("name", "=ilike", "CRAF")], limit=1) or Logo.search([], limit=1)

    @api.depends("sticker_line_ids.meters", "sticker_line_ids.rolls")
    def _compute_sticker_total(self):
        for batch in self:
            batch.sticker_m = sum(batch.sticker_line_ids.mapped("meters"))
            batch.sticker_rolls = sum(batch.sticker_line_ids.mapped("rolls"))

    @api.depends("line_ids.product_id", "line_ids.pcs_ok")
    def _compute_sticker_missing(self):
        Rule = self.env["craf.sticker.rule"]
        for batch in self:
            sections = batch.line_ids.filtered(lambda l: l.pcs_ok > 0).product_id.craf_section_id
            covered = Rule.search([("section_id", "in", sections.ids)]).section_id
            batch.sticker_missing = ", ".join((sections - covered).mapped("name")) or False

    # ------------------------------------------------------------------ hisob
    def _craf_sticker_plan(self):
        """{stiker: metr} — bo'yalgan dona × profil uzunligi × tomonlar, kesim normalari bo'yicha."""
        self.ensure_one()
        Rule = self.env["craf.sticker.rule"]
        Sticker = self.env["craf.sticker"]
        Logo = self.env["craf.sticker.logo"]
        adhesion = self.color_id.craf_sticker_adhesion or "medium"
        plan, missing = defaultdict(float), []
        for line in self.line_ids.filtered(lambda l: l.pcs_ok > 0 and l.product_id):
            product = line.product_id
            section = product.craf_section_id
            length = product.craf_length_m or line.semi_product_id.craf_length_m
            for rule in Rule.search([("section_id", "=", section.id)]):
                sticker = rule.sticker_id
                if not sticker:
                    logo = Logo._craf_for_section(section) or self.sticker_logo_id
                    sticker = Sticker.search([("logo_id", "=", logo.id), ("adhesion", "=", adhesion),
                                              ("width_mm", "=", rule.width_mm)], limit=1)
                    if not sticker:
                        missing.append("%s: %s %s %s mm" % (product.name, logo.name or "logo tanlanmagan",
                                                            dict(ADHESION)[adhesion].split(" ")[0], rule.width_mm))
                        continue
                plan[sticker] += line.pcs_ok * length * int(rule.sides)
        if missing:
            raise UserError("Bu stiker turlari ro'yxatda yo'q (Stiker → Stiker qoldig'i dan qo'shing yoki "
                            "profil normasida aniq stiker tanlang):\n• %s" % "\n• ".join(missing))
        return plan

    def _craf_fill_stickers(self):
        """Stiker qatorlarini normadan yangilaydi; qo'lda o'zgartirilgan sarf (norma ≠ sarf) saqlanadi."""
        for batch in self.filtered(lambda b: b.state == "draft"):
            plan = batch._craf_sticker_plan()
            commands = []
            for line in batch.sticker_line_ids:
                manual = abs(line.meters - line.meters_norm) > EPS
                if line.sticker_id in plan:
                    norm = round(plan.pop(line.sticker_id), 1)
                    vals = {"meters_norm": norm} if manual else {"meters_norm": norm, "meters": norm}
                    commands.append(Command.update(line.id, vals))
                elif manual:
                    commands.append(Command.update(line.id, {"meters_norm": 0.0}))
                else:
                    commands.append(Command.unlink(line.id))
            for sticker, meters in plan.items():
                meters = round(meters, 1)
                commands.append(Command.create({"sticker_id": sticker.id, "meters_norm": meters, "meters": meters}))
            if commands:
                batch.write({"sticker_line_ids": commands})
        return True

    def action_fill_stickers(self):
        return self._craf_fill_stickers()

    def action_fill_norms(self):
        res = super().action_fill_norms()
        self._craf_fill_stickers()
        return res

    def _craf_pack_materials(self):
        res = super()._craf_pack_materials()
        if self.state == "draft":
            self._craf_fill_stickers()
        for line in self.sticker_line_ids.filtered(lambda l: l.meters > EPS):
            res.append((line.product_id, line.meters))
        return res

    def _craf_action_done(self):
        res = super()._craf_action_done()
        if self.sticker_rolls:
            self._craf_post_summary(["Stiker: %s" % "; ".join(
                "%s — %s m (%s rulon)" % (l.sticker_id.name, fmt(l.meters, 0), fmt(l.rolls, 2))
                for l in self.sticker_line_ids if l.meters > EPS)])
        return res


class CrafPaintStickerLine(models.Model):
    _name = "craf.paint.sticker.line"
    _description = "Bo'yash smenasi stiker sarfi"
    _order = "date desc, id"

    batch_id = fields.Many2one("craf.paint.batch", required=True, ondelete="cascade", index=True)
    date = fields.Date(related="batch_id.date", store=True, string="Sana")
    state = fields.Selection(related="batch_id.state", store=True, string="Holat")
    color_id = fields.Many2one(related="batch_id.color_id", store=True, string="Rang")
    sticker_id = fields.Many2one("craf.sticker", string="Stiker", required=True, ondelete="restrict")
    product_id = fields.Many2one(related="sticker_id.product_id", string="Mahsulot")
    logo_id = fields.Many2one(related="sticker_id.logo_id", store=True, string="Logo")
    width_mm = fields.Integer(related="sticker_id.width_mm", store=True, string="Kenglik, mm", aggregator=None)
    meters_norm = fields.Float("Normada, m", digits=(16, 1), readonly=True)
    meters = fields.Float("Sarf, m", digits=(16, 1))
    rolls = fields.Float("Sarf, rulon", compute="_compute_rolls", store=True, digits=(16, 2))

    @api.depends("meters", "sticker_id.roll_length_m")
    def _compute_rolls(self):
        for line in self:
            k = line.sticker_id.roll_length_m
            line.rolls = line.meters / k if k else 0.0
