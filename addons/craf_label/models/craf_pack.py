import math

from odoo import api, fields, models

EPS = 1e-6


class CrafPack(models.Model):
    _name = "craf.pack"
    _description = "Pachka"
    _order = "date desc, id desc"

    name = fields.Char("Pachka №", required=True, copy=False, readonly=True, default="Yangi", index=True)
    product_id = fields.Many2one("product.product", "Mahsulot", required=True, index=True)
    product_tmpl_id = fields.Many2one(related="product_id.product_tmpl_id", store=True, string="Shablon")
    default_code = fields.Char(related="product_id.default_code", string="Kod")
    section_id = fields.Many2one(related="product_id.craf_section_id", store=True, string="Kesim")
    color_id = fields.Many2one(related="product_id.craf_color_id", store=True, string="Rang")
    length_m = fields.Float(related="product_id.craf_length_m", string="Uzunlik, m")
    pcs = fields.Integer("Dona", required=True, aggregator="sum")
    kg_theory = fields.Float("Nazariy kg", digits=(16, 2), compute="_compute_kg", store=True, aggregator="sum")
    kg_actual = fields.Float("Haqiqiy kg", digits=(16, 2), aggregator="sum",
                             help="Tarozida tortilgan og'irlik. Bo'sh qolsa, yorliqda chiziq chiqadi.")
    kg_diff_pct = fields.Float("Farq, %", digits=(16, 1), compute="_compute_kg", store=True, aggregator="avg")
    location_id = fields.Many2one("stock.location", "Joylashuv", domain=[("usage", "=", "internal")], index=True)
    origin = fields.Char("Manba hujjat", index=True)
    date = fields.Datetime("Sana", required=True, default=fields.Datetime.now)
    user_id = fields.Many2one("res.users", "Qadoqlovchi", default=lambda self: self.env.user)
    note = fields.Char("Izoh")
    qr_value = fields.Char("QR havola", compute="_compute_qr_value")
    pcs_text = fields.Char("Dona (matn)", compute="_compute_pcs_text")
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint("unique(name)", "Pachka raqami takrorlanmasligi kerak.")
    _pcs_positive = models.Constraint("CHECK(pcs > 0)", "Pachkadagi dona soni 0 dan katta bo'lishi kerak.")

    @api.model_create_multi
    def create(self, vals_list):
        Seq = self.env["ir.sequence"]
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == "Yangi":
                vals["name"] = Seq.next_by_code("craf.pack") or "Yangi"
        return super().create(vals_list)

    @api.depends("pcs", "kg_actual", "product_id.craf_kg_per_pc")
    def _compute_kg(self):
        for pack in self:
            theory = pack.pcs * (pack.product_id.craf_kg_per_pc or 0.0)
            pack.kg_theory = theory
            pack.kg_diff_pct = (pack.kg_actual - theory) / theory * 100.0 if pack.kg_actual and theory else 0.0

    def _compute_qr_value(self):
        base = (self.env["ir.config_parameter"].sudo().get_param("web.base.url") or "").rstrip("/")
        for pack in self:
            pack.qr_value = "%s/craf/p/%s" % (base, pack.name) if pack.name else False

    @api.depends("pcs", "product_id.craf_pcs_per_pack")
    def _compute_pcs_text(self):
        for pack in self:
            per = pack.product_id.craf_pcs_per_pack
            if per and pack.pcs != per:
                pack.pcs_text = "%s dona (to'liq emas: %s dan)" % (pack.pcs, per)
            else:
                pack.pcs_text = "%s dona" % pack.pcs

    @api.model
    def _craf_find(self, code):
        """Skaner yoki qo'lda kiritilgan qiymatdan pachkani topadi (raqam yoki QR havola)."""
        code = (code or "").strip()
        if not code:
            return self.browse()
        code = code.rstrip("/").rsplit("/", 1)[-1].strip()
        return self.search([("name", "=ilike", code)], limit=1)

    def action_print(self):
        return self.env.ref("craf_label.action_report_craf_pack").report_action(self)

    @api.model
    def _craf_split(self, product, pcs):
        """Jami donani pachkalarga bo'ladi: [20, 20, 7]."""
        pcs = int(math.floor((pcs or 0) + EPS))
        per = product.craf_pcs_per_pack or pcs
        if pcs <= 0 or per <= 0:
            return []
        full, rest = divmod(pcs, per)
        return [per] * full + ([rest] if rest else [])
