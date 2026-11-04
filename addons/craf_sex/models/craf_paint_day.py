"""Kunlik bo'yash va qadoqlash — bo'yash xodimining daftaridagidek bitta kunlik yozuv:

    03.11.2026
    L 6m — 211                     (CRAF stiker)
    Alusam L 6m — 17 pachka 1 dona
    T 6m — 41+39+44                9016 kukun 297,6 kg

Har qator: profil (kesim), uzunlik, rang, stiker (logo), pachka (bir nechta son «+» bilan) va + dona. Bir kunda bir
nechta rang bo'lishi mumkin (1376 va 9016). Kukun sarfi — har rang bo'yicha kg.

Tasdiqlanganda har (rang, stiker) juftligi uchun bo'yash smenasi (craf.paint.batch) yaratilib tasdiqlanadi:
bo'yalmagan profil Bo'yash sexidan yechiladi, tayyor mahsulot (Alusam stikerli — «… ALUSAM» mahsuloti, bo'lsa)
darhol Tayyor mahsulot omboriga o'tadi, kukun rang qatorlariga maydon (m²) bo'yicha bo'linadi, stiker avtomatik.
"""
import re

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt

DAY_STATES = [("draft", "Qoralama"), ("done", "Tasdiqlangan"), ("cancel", "Bekor qilingan")]
DEFAULT_POWDER_NORM = 120.0  # g/m², rang kartochkasida bo'lmasa (craf_paint bilan bir xil)


def parse_packs(text):
    """«41+39+44» → 124; «211» → 211; bo'sh → 0. Noto'g'ri yozuv — UserError."""
    text = (text or "").strip()
    if not text:
        return 0
    parts = [p for p in re.split(r"[+\s,;]+", text) if p]
    try:
        return sum(int(p) for p in parts)
    except ValueError as err:
        raise UserError("Pachka sonini raqam bilan yozing (bir nechta bo'lsa «41+39+44»): %s" % text) from err


class CrafPaintDay(models.Model):
    _name = "craf.paint.day"
    _description = "Kunlik bo'yash va qadoqlash"
    _inherit = ["mail.thread"]
    _order = "date desc, id desc"

    name = fields.Char("Raqam", required=True, copy=False, readonly=True, default="Yangi", index=True)
    date = fields.Date("Sana", required=True, default=fields.Date.context_today, tracking=True, index=True)
    employee_id = fields.Many2one("hr.employee", string="Mas'ul", tracking=True)
    state = fields.Selection(DAY_STATES, string="Holat", required=True, default="draft", tracking=True, index=True)
    line_ids = fields.One2many("craf.paint.day.line", "day_id", string="Qadoqlangan profillar", copy=True)
    powder_ids = fields.One2many("craf.paint.day.powder", "day_id", string="Bo'yoq sarfi", copy=True)
    batch_ids = fields.One2many("craf.paint.batch", "paint_day_id", string="Bo'yash smenalari", readonly=True)
    note = fields.Text("Izoh")
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    packs_total = fields.Integer("Pachka", compute="_compute_totals", store=True)
    pcs_total = fields.Integer("Dona", compute="_compute_totals", store=True)
    kg_total = fields.Float("Kg", compute="_compute_totals", store=True, digits=(16, 1))
    powder_total = fields.Float("Kukun, kg", compute="_compute_totals", store=True, digits=(16, 2))

    @api.depends("line_ids.packs", "line_ids.pcs", "line_ids.kg", "powder_ids.qty")
    def _compute_totals(self):
        for day in self:
            day.packs_total = sum(day.line_ids.mapped("packs"))
            day.pcs_total = sum(day.line_ids.mapped("pcs"))
            day.kg_total = sum(day.line_ids.mapped("kg"))
            day.powder_total = sum(day.powder_ids.mapped("qty"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == "Yangi":
                vals["name"] = self.env["ir.sequence"].next_by_code("craf.paint.day") or "Yangi"
        return super().create(vals_list)

    def unlink(self):
        if any(day.state == "done" for day in self):
            raise UserError("Tasdiqlangan kunlik yozuvni o'chirib bo'lmaydi.")
        return super().unlink()

    # ------------------------------------------------------------------ mahsulotni topish
    @api.model
    def _craf_resolve(self, section, length, color, logo):
        """(bo'yalmagan profil, tayyor mahsulot) — kesim, uzunlik, rang va stiker bo'yicha.

        Bo'yalmagan profil — oddiy kesimniki (press shuni chiqaradi). Stiker logosi nomli kesim bo'lsa
        (L → «L ALUSAM») va shu rangda mahsuloti bo'lsa — o'sha tayyor mahsulot, aks holda oddiy kesimniki."""
        Tmpl = self.env["product.template"]
        raw = Tmpl._craf_raw_color()

        def find(sec, col):
            if not sec or not col:
                return self.env["product.product"]
            return Tmpl.search([("craf_section_id", "=", sec.id), ("craf_length_m", "=", length),
                                ("craf_color_id", "=", col.id)], limit=1).product_variant_id

        semi = find(section, raw)
        product = self.env["product.product"]
        if logo and section.profile_type and not (section.series or "").strip():
            brand = self.env["craf.profile.section"].search([
                ("profile_type", "=", section.profile_type), ("series", "=ilike", logo.name),
                ("id", "!=", section.id)], limit=1)
            product = find(brand, color)
        return semi, product or find(section, color)

    # ------------------------------------------------------------------ tasdiqlash
    def action_confirm(self):
        """Har (rang, stiker) uchun bo'yash smenasi yaratiladi va tasdiqlanadi (omborga — darhol)."""
        Sex = self.env["craf.sex"]
        for day in self:
            if day.state != "draft":
                raise UserError("%s allaqachon %s." % (day.name, dict(DAY_STATES)[day.state].lower()))
            lines = day.line_ids.filtered(lambda l: l.pcs > 0)
            if not lines:
                raise UserError("Qadoqlangan profillarni yozing (profil, rang, pachka).")
            for line in lines:
                if not line.semi_product_id:
                    raise UserError("%s %s m uchun bo'yalmagan profil katalogda yo'q." % (
                        line.section_id.name, fmt(line.length_m, 0)))
                if not line.product_id:
                    raise UserError("%s %s m, %s uchun tayyor mahsulot katalogda yo'q." % (
                        line.section_id.name, fmt(line.length_m, 0), line.color_id.name))
            powder = {p.color_id: p.qty for p in day.powder_ids if p.qty > EPS}
            groups = {}
            for line in lines:
                groups.setdefault((line.color_id, line.logo_id), self.env["craf.paint.day.line"])
                groups[(line.color_id, line.logo_id)] |= line
            # kukun: rang qatorlariga maydon bo'yicha bo'linadi (oxirgisi — qoldiq)
            color_area = {}
            for (color, _logo), group in groups.items():
                color_area[color] = color_area.get(color, 0.0) + sum(group.mapped("area_m2"))
            left = dict(powder)
            seen = {}
            batches = self.env["craf.paint.batch"]
            for (color, logo), group in groups.items():
                seen[color] = seen.get(color, 0) + 1
                last = seen[color] == sum(1 for (c, _l) in groups if c == color)
                share = 0.0
                if powder.get(color):
                    area = sum(group.mapped("area_m2"))
                    share = left[color] if last else round(powder[color] * (area / color_area[color]
                                                                             if color_area[color] else 0.0), 2)
                    left[color] -= share
                vals = {
                    "date": day.date,
                    "shift": "1",
                    "color_id": color.id,
                    "employee_id": day.employee_id.id,
                    "note": "Kunlik bo'yash: %s" % day.name,
                    "paint_day_id": day.id,
                    "line_ids": [Command.create({
                        "semi_product_id": l.semi_product_id.id, "product_id": l.product_id.id,
                        "pcs_in": l.pcs, "pcs_defect": 0, "out_packs": l.packs, "out_extra": l.extra,
                    }) for l in group],
                    "powder_qty": share,
                    "film_qty": 0.0,
                    "tape_qty": 0.0,
                }
                if logo and "sticker_logo_id" in self.env["craf.paint.batch"]._fields:
                    vals["sticker_logo_id"] = logo.id
                batch = self.env["craf.paint.batch"].create(vals)
                Sex._confirm(batch)
                batches |= batch
            day.state = "done"
            day.message_post(body="Tasdiqlandi — bo'yash smenalari: %s" % ", ".join(batches.mapped("name")))
        return True

    def action_cancel(self):
        if any(day.state == "done" for day in self):
            raise UserError("Tasdiqlangan kunlik yozuvni bekor qilib bo'lmaydi.")
        self.state = "cancel"

    def action_draft(self):
        self.filtered(lambda d: d.state == "cancel").state = "draft"

    # ------------------------------------------------------------------ daftardagidek matn
    def _craf_lines_text(self):
        """[(qator matni, rang)] — «Alusam L 6m — 17 pachka 1 dona»."""
        self.ensure_one()
        res = []
        for line in self.line_ids:
            logo = line.logo_id.name or ""
            prefix = "" if not logo or logo.upper() == "CRAF" else logo + " "
            packs = line.packs_text if line.packs_text and "+" in line.packs_text else str(line.packs)
            text = "%s%s %sm — %s pachka" % (prefix, line.section_id.name, fmt(line.length_m, 0), packs)
            if line.extra:
                text += " %s dona" % line.extra
            res.append((text, line.color_id.name or ""))
        return res


class CrafPaintDayLine(models.Model):
    _name = "craf.paint.day.line"
    _description = "Kunlik bo'yash qatori"
    _order = "id"

    day_id = fields.Many2one("craf.paint.day", required=True, ondelete="cascade", index=True)
    state = fields.Selection(related="day_id.state")
    section_id = fields.Many2one("craf.profile.section", string="Profil", required=True)
    length_m = fields.Float("Uzunlik, m", required=True, default=6.0, digits=(16, 1))
    color_id = fields.Many2one("craf.color", string="Rang", required=True, domain=[("is_painted", "=", True)])
    logo_id = fields.Many2one("craf.sticker.logo", string="Stiker")
    packs_text = fields.Char("Pachka (yozilgani)", help="Bir nechta son «+» bilan: 41+39+44")
    packs = fields.Integer("Pachka")
    extra = fields.Integer("+ dona")
    semi_product_id = fields.Many2one("product.product", string="Bo'yalmagan profil",
                                      compute="_compute_products", store=True)
    product_id = fields.Many2one("product.product", string="Tayyor mahsulot", compute="_compute_products",
                                 store=True)
    per_pack = fields.Integer("Pachkada, dona", compute="_compute_values", store=True)
    pcs = fields.Integer("Dona", compute="_compute_values", store=True)
    kg = fields.Float("Kg", compute="_compute_values", store=True, digits=(16, 1))
    area_m2 = fields.Float("Maydon, m²", compute="_compute_values", store=True, digits=(16, 2))

    @api.depends("section_id", "length_m", "color_id", "logo_id")
    def _compute_products(self):
        Day = self.env["craf.paint.day"]
        for line in self:
            semi, product = Day._craf_resolve(line.section_id, line.length_m, line.color_id, line.logo_id) \
                if line.section_id and line.color_id else (False, False)
            line.semi_product_id = semi
            line.product_id = product

    @api.depends("packs", "extra", "product_id.craf_pcs_per_pack", "semi_product_id.craf_kg_per_pc",
                 "semi_product_id.craf_length_m", "section_id.perimeter_m")
    def _compute_values(self):
        for line in self:
            per_pack = line.product_id.craf_pcs_per_pack or line.semi_product_id.craf_pcs_per_pack or 0
            pcs = line.packs * per_pack + line.extra
            line.per_pack = per_pack
            line.pcs = pcs
            line.kg = pcs * (line.semi_product_id.craf_kg_per_pc or 0.0)
            line.area_m2 = pcs * line.length_m * (line.section_id.perimeter_m or 0.0)


class CrafPaintDayPowder(models.Model):
    _name = "craf.paint.day.powder"
    _description = "Kunlik bo'yash: bo'yoq (kukun) sarfi"
    _order = "id"

    day_id = fields.Many2one("craf.paint.day", required=True, ondelete="cascade", index=True)
    color_id = fields.Many2one("craf.color", string="Rang", required=True)
    product_id = fields.Many2one("product.product", string="Kukun", compute="_compute_product_id", store=True)
    qty = fields.Float("Sarf, kg", digits=(16, 2))

    @api.depends("color_id.paint_tmpl_id")
    def _compute_product_id(self):
        for rec in self:
            rec.product_id = rec.color_id.paint_tmpl_id.product_variant_id


class CrafPaintBatch(models.Model):
    _inherit = "craf.paint.batch"

    paint_day_id = fields.Many2one("craf.paint.day", string="Kunlik bo'yash", copy=False, index=True,
                                   ondelete="set null")
