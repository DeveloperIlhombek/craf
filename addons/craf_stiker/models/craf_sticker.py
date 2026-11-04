from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, FORECAST_STATUS, fmt

ADHESION = [("medium", "Medium (50 mic)"), ("high", "High (80 mic)")]
STOCK_LOCATION = "Xom-ashyo ombori"


class CrafStickerLogo(models.Model):
    _name = "craf.sticker.logo"
    _description = "Stiker logosi"
    _order = "sequence, name"

    name = fields.Char("Logo", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    sticker_ids = fields.One2many("craf.sticker", "logo_id", string="Stikerlar")

    _name_uniq = models.Constraint("UNIQUE(name)", "Logo nomi takrorlanmasligi kerak.")

    @api.model
    def _craf_for_section(self, section):
        """Kesim seriyasi logoga mos bo'lsa (ALUSAM, CRAF) — o'sha logo."""
        series = (section.series or "").strip().lower()
        if not series:
            return self.browse()
        return self.search([]).filtered(lambda l: l.name.strip().lower() == series)[:1]


class CrafSticker(models.Model):
    _name = "craf.sticker"
    _description = "Stiker lenta turi"
    _order = "logo_sequence, logo_id, adhesion desc, width_mm"

    name = fields.Char("Stiker", compute="_compute_name", store=True)
    logo_id = fields.Many2one("craf.sticker.logo", string="Logo", required=True, ondelete="restrict")
    logo_sequence = fields.Integer(related="logo_id.sequence", store=True)
    adhesion = fields.Selection(ADHESION, string="Yopishqoqlik", required=True, default="medium")
    width_mm = fields.Integer("Kenglik, mm", required=True, aggregator=None)
    micron = fields.Integer("Qalinlik, mic", aggregator=None)
    roll_length_m = fields.Float("Rulon uzunligi, m", required=True, default=500.0, digits=(16, 1),
                                 aggregator=None)
    size_text = fields.Char("O'lcham", compute="_compute_name", store=True)
    product_id = fields.Many2one("product.product", string="Ombor mahsuloti", readonly=True, copy=False,
                                 ondelete="restrict",
                                 help="Qoldiq metrda yuritiladi; stiker yaratilganda o'zi yaratiladi.")
    active = fields.Boolean(default=True)
    note = fields.Text("Izoh")

    min_rolls = fields.Float("Minimal qoldiq, rulon", compute="_compute_min_rolls", inverse="_inverse_min_rolls",
                             digits=(16, 0))
    qty_m = fields.Float("Zavodda, m", compute="_compute_forecast", digits=(16, 0))
    qty_rolls = fields.Float("Zavodda, rulon", compute="_compute_forecast", digits=(16, 1))
    in_sex_rolls = fields.Float("Sexda, rulon", compute="_compute_forecast", digits=(16, 1),
                                help="Bo'yash sexi va Qadoqlash joylarida")
    used_rolls = fields.Float("Sarf (davr), rulon", compute="_compute_forecast", digits=(16, 1))
    period = fields.Integer("Davr, kun", compute="_compute_forecast")
    avg_rolls = fields.Float("Kuniga, rulon", compute="_compute_forecast", digits=(16, 2))
    days_left = fields.Float("Necha kunga yetadi", compute="_compute_forecast", digits=(16, 1))
    days_text = fields.Char("Yetadi", compute="_compute_forecast")
    end_date = fields.Date("Tugash sanasi", compute="_compute_forecast")
    status = fields.Selection(FORECAST_STATUS, string="Holat", compute="_compute_forecast")

    _type_uniq = models.Constraint("UNIQUE(logo_id, adhesion, width_mm)",
                                   "Bu logo, yopishqoqlik va kenglikdagi stiker allaqachon bor.")
    _positive = models.Constraint("CHECK(width_mm > 0 AND roll_length_m > 0)",
                                  "Kenglik va rulon uzunligi musbat bo'lishi kerak.")

    @api.depends("logo_id.name", "adhesion", "width_mm", "micron", "roll_length_m")
    def _compute_name(self):
        labels = dict(ADHESION)
        for rec in self:
            size = "%smm" % rec.width_mm
            if rec.micron:
                size += "*%smic" % rec.micron
            size += "*%sm" % fmt(rec.roll_length_m, 0 if rec.roll_length_m % 1 == 0 else 1).replace(" ", "")
            rec.size_text = size
            rec.name = "%s %s %s" % (rec.logo_id.name or "", (labels.get(rec.adhesion) or "").split(" ")[0], size)

    # ------------------------------------------------------------------ ombor mahsuloti
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records.filtered(lambda r: not r.product_id):
            rec.product_id = rec._craf_create_product()
        return records

    def write(self, vals):
        res = super().write(vals)
        if {"logo_id", "adhesion", "width_mm", "micron", "roll_length_m"} & set(vals):
            for rec in self.filtered("product_id"):
                rec.product_id.product_tmpl_id.write({"name": "Stiker %s" % rec.name,
                                                      "default_code": rec._craf_code()})
        if "active" in vals:
            self.product_id.product_tmpl_id.write({"active": vals["active"]})
        return res

    def _craf_code(self):
        self.ensure_one()
        return "STK-%s-%s-%s" % ((self.logo_id.name or "").upper().replace(" ", ""),
                                 "H" if self.adhesion == "high" else "M", self.width_mm)

    def _craf_create_product(self):
        self.ensure_one()
        categ = self.env.ref("craf_paint.categ_pack_material", raise_if_not_found=False)
        tmpl = self.env["product.template"].create({
            "name": "Stiker %s" % self.name,
            "default_code": self._craf_code(),
            "type": "consu",
            "is_storable": True,
            "uom_id": self.env.ref("uom.product_uom_meter").id,
            "categ_id": categ.id if categ else self.env.ref("product.product_category_all").id,
            "sale_ok": False,
            "purchase_ok": True,
        })
        return tmpl.product_variant_id

    @api.ondelete(at_uninstall=False)
    def _unlink_check_moves(self):
        moved = self.filtered(lambda r: r.product_id and self.env["stock.move"].search_count(
            [("product_id", "=", r.product_id.id)], limit=1))
        if moved:
            raise UserError("Harakati bor stikerni o'chirib bo'lmaydi — arxivlang: %s" %
                            ", ".join(moved.mapped("name")))

    def unlink(self):
        products = self.product_id
        res = super().unlink()
        products.product_tmpl_id.unlink()
        return res

    # ------------------------------------------------------------------ qoldiq va prognoz
    @api.depends("product_id.craf_min_qty", "roll_length_m")
    def _compute_min_rolls(self):
        for rec in self:
            rec.min_rolls = (rec.product_id.craf_min_qty or 0.0) / rec.roll_length_m if rec.roll_length_m else 0.0

    def _inverse_min_rolls(self):
        for rec in self.filtered("product_id"):
            rec.product_id.product_tmpl_id.craf_min_qty = rec.min_rolls * rec.roll_length_m

    def _compute_forecast(self):
        rows = self.env["craf.paint.batch"]._craf_material_forecast(self.product_id) if self.product_id else {}
        today = fields.Date.context_today(self)
        for rec in self:
            r = rows.get(rec.product_id.id)
            k = rec.roll_length_m or 1.0
            days = r["days_left"] if r else None
            rec.qty_m = r["qty"] if r else 0.0
            rec.qty_rolls = rec.qty_m / k
            rec.in_sex_rolls = (r["in_sex"] if r else 0.0) / k
            rec.used_rolls = (r["used"] if r else 0.0) / k
            rec.period = r["period"] if r else 0
            rec.avg_rolls = (r["avg"] if r else 0.0) / k
            rec.days_left = days or 0.0
            rec.days_text = self.env["craf.paint.batch"]._craf_days_text(days)
            rec.end_date = today + timedelta(days=int(days)) if days is not None and days <= 365 else False
            rec.status = r["status"] if r else False

    @api.model
    def _cron_min_qty(self):
        stickers = self.search([("product_id", "!=", False)])
        rows = self.env["craf.paint.batch"]._craf_material_forecast(stickers.product_id)
        for sticker in stickers:
            r = rows.get(sticker.product_id.id)
            if r:
                r["uom"] = "m"
        self.env["craf.paint.batch"]._craf_min_qty_sync(
            list(rows.values()), "boyash", "craf_stiker.mail_activity_stiker_min", "Stiker")

    @api.model
    def _craf_apply_count(self, counts, label):
        """counts: {stiker: sanalgan rulon (butun zavod bo'yicha)} — farq Xom-ashyo omboriga
        inventarizatsiya bilan yoziladi."""
        location = self.env["craf.paint.batch"]._craf_loc(STOCK_LOCATION)
        if not location:
            raise UserError("«%s» joylashuvi topilmadi." % STOCK_LOCATION)
        Quant = self.env["stock.quant"].sudo().with_context(inventory_mode=True, inventory_name=label)
        quants = Quant.browse()
        for sticker, rolls in counts.items():
            product = sticker.product_id
            if not product:
                continue
            target = rolls * sticker.roll_length_m
            total = sum(Quant.search([("product_id", "=", product.id),
                                      ("location_id.usage", "=", "internal")]).mapped("quantity"))
            if abs(target - total) <= EPS:
                continue
            quant = Quant.search([("product_id", "=", product.id), ("location_id", "=", location.id)], limit=1) \
                or Quant.create({"product_id": product.id, "location_id": location.id})
            here = quant.quantity
            new_here = here + target - total
            if new_here < -EPS:
                raise UserError("%s: sanalgan %s rulon sexlardagi qoldiqdan kam — avval sexdagi qoldiqni "
                                "tekshiring." % (sticker.name, fmt(rolls, 1)))
            quant.inventory_quantity = new_here
            quants |= quant
        if quants:
            quants.action_apply_inventory()
        return quants

    def action_count(self):
        stickers = self or self.search([])
        return {
            "type": "ir.actions.act_window",
            "name": "Stiker sanash",
            "res_model": "craf.sticker.count",
            "view_mode": "form",
            "target": "new",
            "context": {"default_sticker_ids": stickers.ids},
        }

    def action_view_moves(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "%s — harakatlar" % self.name,
            "res_model": "stock.move.line",
            "view_mode": "list,form",
            "domain": [("product_id", "=", self.product_id.id)],
            "context": {"create": False},
        }


class CrafStickerRule(models.Model):
    _name = "craf.sticker.rule"
    _description = "Profil stiker normasi"
    _order = "section_id, width_mm"

    section_id = fields.Many2one("craf.profile.section", string="Kesim (profil turi)", required=True,
                                 ondelete="cascade", index=True)
    width_mm = fields.Integer("Kenglik, mm", required=True, aggregator=None,
                              help="Shu kesimga ketadigan stiker kengligi (40, 52, 68).")
    sides = fields.Selection([("1", "1 tomoni"), ("2", "2 tomoni")], string="Tomonlar", required=True,
                             default="1")
    sticker_id = fields.Many2one(
        "craf.sticker", string="Aniq stiker",
        help="Bo'sh bo'lsa: logo — kesim seriyasi yoki smenadagi logo, yopishqoqlik — rang bo'yicha "
             "(Antratsit — High). To'ldirilsa — har doim shu stiker ishlatiladi.")
    note = fields.Char("Izoh")

    _section_width_uniq = models.Constraint("UNIQUE(section_id, width_mm)",
                                            "Bu kesim uchun shu kenglikdagi norma allaqachon bor.")

    @api.depends("section_id.name", "width_mm", "sides")
    def _compute_display_name(self):
        for rule in self:
            rule.display_name = "%s · %s mm · %s tomon" % (rule.section_id.display_name or "?", rule.width_mm,
                                                           rule.sides)

    @api.onchange("sticker_id")
    def _onchange_sticker_id(self):
        if self.sticker_id:
            self.width_mm = self.sticker_id.width_mm

    @api.constrains("sticker_id", "width_mm")
    def _check_sticker_width(self):
        for rule in self:
            if rule.sticker_id and rule.sticker_id.width_mm != rule.width_mm:
                raise UserError("%s: tanlangan stiker kengligi %s mm, normada %s mm." % (
                    rule.section_id.name, rule.sticker_id.width_mm, rule.width_mm))

    @api.constrains("width_mm")
    def _check_width_positive(self):
        for rule in self:
            if rule.width_mm <= 0:
                raise UserError("Stiker kengligi musbat bo'lishi kerak (40, 52, 68 mm).")

    @api.model
    def _craf_norm_section(self, section):
        """Normasi olinadigan kesim: o'zining normasi bo'lmasa va brend kesim bo'lsa (L ALUSAM, T CRAF —
        seriyasi logo nomi) — oddiy kesimniki (L, T): profil bir xil, faqat stiker boshqa."""
        if not section or self.search_count([("section_id", "=", section.id)]):
            return section
        if section.profile_type and self.env["craf.sticker.logo"]._craf_for_section(section):
            base = self.env["craf.profile.section"].search([
                ("profile_type", "=", section.profile_type), ("id", "!=", section.id)]).filtered(
                lambda s: not (s.series or "").strip())[:1]
            if base:
                return base
        return section

    @api.model
    def _craf_stickers_for(self, section, color, default_logo):
        """Profil (kesim) va rang uchun qaysi stikerlar ketadi — bo'yash smenasi ham, «Tekshirish» ham shu bilan.

        [{norm, sticker, width, sides, adhesion, logo, adhesion_rule, logo_rule, series_logo, explicit}]
        - kenglik va tomon — profil normasidan (bitta profilga bir nechta kenglik bo'lishi mumkin);
        - qalinlik (yopishqoqlik) — stiker qoidasidan (masalan, Antratsit → High 80 mic), qoida bo'lmasa Medium;
        - logo — stiker qoidasidan, bo'lmasa kesim seriyasidan (ALUSAM, CRAF), bo'lmasa smenadagi logodan;
        - normada aniq stiker tanlangan bo'lsa — har doim o'sha."""
        Sticker = self.env["craf.sticker"]
        adhesion_rule, logo_rule = self.env["craf.sticker.choice"]._craf_match(section, color)
        adhesion = adhesion_rule.adhesion or "medium"
        series_logo = self.env["craf.sticker.logo"]._craf_for_section(section)
        logo = logo_rule.logo_id or series_logo or default_logo
        result = []
        for norm in self.search([("section_id", "=", self._craf_norm_section(section).id)]):
            sticker = norm.sticker_id
            if not sticker and logo:
                sticker = Sticker.search([("logo_id", "=", logo.id), ("adhesion", "=", adhesion),
                                          ("width_mm", "=", norm.width_mm)], limit=1)
            result.append({
                "norm": norm, "sticker": sticker, "width": norm.width_mm, "sides": int(norm.sides),
                "adhesion": sticker.adhesion if norm.sticker_id else adhesion,
                "logo": sticker.logo_id if norm.sticker_id else logo,
                "adhesion_rule": adhesion_rule, "logo_rule": logo_rule, "series_logo": series_logo,
                "explicit": bool(norm.sticker_id),
            })
        return result


class CrafStickerChoice(models.Model):
    """Stiker tanlash qoidasi: qaysi rang va/yoki profil uchun qanday stiker — qalinlik (yopishqoqlik) va logo.

    Masalan: «J306 Антрацит → High (80 mic)», «ALUSAM profillari → Alusam logo». Bir nechta qoida mos kelsa —
    aniqrog'i ustun (profil + rang > faqat profil > faqat rang > hamma uchun), teng bo'lsa — tartib raqami kichigi.
    Qoida mos kelmasa: qalinlik — Medium (50 mic), logo — kesim seriyasi yoki smenadagi logo."""
    _name = "craf.sticker.choice"
    _description = "Stiker tanlash qoidasi"
    _order = "sequence, id"

    sequence = fields.Integer("Tartib", default=10,
                              help="Bir xil aniqlikdagi qoidalar mos kelsa — kichik raqamlisi ishlaydi.")
    active = fields.Boolean("Faol", default=True)
    color_ids = fields.Many2many("craf.color", "craf_sticker_choice_color_rel", "choice_id", "color_id",
                                 string="Ranglar", domain=[("is_painted", "=", True)],
                                 help="Bo'sh — hamma rang.")
    section_ids = fields.Many2many("craf.profile.section", "craf_sticker_choice_section_rel", "choice_id",
                                   "section_id", string="Profillar", help="Bo'sh — hamma profil.")
    adhesion = fields.Selection(ADHESION, string="Qalinlik (yopishqoqlik)",
                                help="Shu holatda qaysi stiker: Medium (50 mic) yoki High (80 mic). "
                                     "Bo'sh — qalinlikni o'zgartirmaydi.")
    logo_id = fields.Many2one("craf.sticker.logo", string="Logo", ondelete="restrict",
                              help="Bo'sh — logoni o'zgartirmaydi (kesim seriyasi yoki smenadagi logo).")
    note = fields.Char("Izoh")
    summary = fields.Char("Qoida", compute="_compute_summary")

    @api.depends("color_ids.name", "section_ids.name", "adhesion", "logo_id.name")
    def _compute_summary(self):
        labels = dict(ADHESION)
        for rec in self:
            cond = []
            cond.append(", ".join(rec.color_ids.mapped("name")) if rec.color_ids else "hamma rang")
            if rec.section_ids:
                cond.append(", ".join(rec.section_ids.mapped("name")))
            result = []
            if rec.adhesion:
                result.append(labels[rec.adhesion])
            if rec.logo_id:
                result.append("logo %s" % rec.logo_id.name)
            rec.summary = "%s → %s" % (" · ".join(cond), ", ".join(result) or "—")

    @api.depends("summary")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.summary

    @api.constrains("adhesion", "logo_id")
    def _check_result(self):
        for rec in self:
            if not rec.adhesion and not rec.logo_id:
                raise UserError("Qoida natijasini tanlang: stiker qalinligi va/yoki logo.")

    @api.constrains("color_ids", "section_ids", "active")
    def _check_duplicate(self):
        for rec in self.filtered("active"):
            same = self.search([("id", "!=", rec.id)]).filtered(
                lambda r: r.color_ids == rec.color_ids and r.section_ids == rec.section_ids)
            if same:
                raise UserError("Shu shartli qoida allaqachon bor: %s. Uni tahrirlang." % same[0].summary)

    @api.model
    def _craf_match(self, section, color):
        """(qalinlik qoidasi, logo qoidasi) — shu profil va rang uchun eng aniq mos qoidalar."""
        best = {}
        for rule in self.search([]):
            if rule.color_ids and color not in rule.color_ids:
                continue
            if rule.section_ids and section not in rule.section_ids:
                continue
            key = (-(2 * bool(rule.section_ids) + bool(rule.color_ids)), rule.sequence, rule.id)
            for field in ("adhesion", "logo_id"):
                if rule[field] and (field not in best or key < best[field][0]):
                    best[field] = (key, rule)
        empty = self.browse()
        return best.get("adhesion", (None, empty))[1], best.get("logo_id", (None, empty))[1]
