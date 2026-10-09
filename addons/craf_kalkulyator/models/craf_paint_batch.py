from odoo import api, fields, models
from odoo.exceptions import UserError


def packs_text(pcs, per_pack):
    pcs = int(pcs or 0)
    if not per_pack:
        return "%s dona" % pcs
    packs, rest = divmod(pcs, per_pack)
    if not packs:
        return "%s dona" % rest
    return "%s pachka + %s dona" % (packs, rest) if rest else "%s pachka" % packs


class CrafPaintBatch(models.Model):
    _inherit = "craf.paint.batch"

    powder_bags = fields.Float("Kukun, o'ram", digits=(16, 2))
    powder_pkg_kg = fields.Float(related="powder_product_id.craf_pkg_kg", string="1 o'ram kukun, kg", digits=(16, 2))
    pcs_packed = fields.Integer("Qadoqlandi, dona", compute="_compute_pcs_packed", store=True, aggregator="sum")

    @api.depends("line_ids.pcs_packed")
    def _compute_pcs_packed(self):
        for batch in self:
            batch.pcs_packed = sum(batch.line_ids.mapped("pcs_packed"))

    @api.onchange("powder_bags")
    def _onchange_powder_bags(self):
        if self.powder_bags and self.powder_pkg_kg:
            self.powder_qty = round(self.powder_bags * self.powder_pkg_kg, 2)

    def _craf_action_done(self):
        for line in self.line_ids.filtered(lambda l: l.pcs_in > 0 and (l.out_packs or l.out_extra)):
            if line.out_packs and not line.per_pack:
                raise UserError("%s: \"dona / pachka\" kiritilmagan — mahsulot kartochkasida (Profil) belgilang." %
                                line.product_id.display_name)
            if line.pcs_packed != line.pcs_ok:
                raise UserError(
                    "%s: qadoqlandi %s dona (%s), bo'yaldi esa %s dona (kirdi %s − brak %s).\n"
                    "Pachka sonini yoki brakni tekshiring." % (
                        line.product_id.display_name or line.semi_product_id.display_name, line.pcs_packed,
                        line.packs_text, line.pcs_ok, line.pcs_in, line.pcs_defect))
        return super()._craf_action_done()


class CrafPaintBatchLine(models.Model):
    _inherit = "craf.paint.batch.line"

    per_pack = fields.Integer("Dona / pachka", compute="_compute_per_pack")
    out_packs = fields.Integer("Qadoqlandi, pachka")
    out_extra = fields.Integer("+ dona", help="To'liq bo'lmagan pachkadagi dona")
    pcs_packed = fields.Integer("Qadoqlandi, dona", compute="_compute_pcs_packed", store=True)
    packs_text = fields.Char("Qadoqlandi", compute="_compute_packs_text")
    pcs_in_auto = fields.Boolean(
        "Kirdi pachkadan hisoblangan", copy=False,
        help="Kirgan dona korzinkadan emas, qadoqlangan pachka + brakdan hisoblangan")

    @api.depends("product_id.craf_pcs_per_pack", "semi_product_id.craf_pcs_per_pack")
    def _compute_per_pack(self):
        for line in self:
            line.per_pack = line.product_id.craf_pcs_per_pack or line.semi_product_id.craf_pcs_per_pack

    @api.depends("out_packs", "out_extra", "product_id.craf_pcs_per_pack", "semi_product_id.craf_pcs_per_pack")
    def _compute_pcs_packed(self):
        for line in self:
            per_pack = line.product_id.craf_pcs_per_pack or line.semi_product_id.craf_pcs_per_pack
            line.pcs_packed = (line.out_packs or 0) * (per_pack or 0) + (line.out_extra or 0)

    @api.depends("pcs_packed", "per_pack")
    def _compute_packs_text(self):
        for line in self:
            line.packs_text = packs_text(line.pcs_packed, line.per_pack)

    def _craf_packed_vals(self, packed):
        """Qadoqlangan dona bo'yicha kirdi/brakni moslash.

        Kirgan dona ma'lum bo'lsa (masalan korzinkalardan) — brak = kirdi − qadoqlandi;
        bo'lmasa yoki qadoqlangan undan ko'p bo'lsa — kirdi = qadoqlandi + brak.
        """
        self.ensure_one()
        defect = self.pcs_defect or 0
        if not self.pcs_in or self.pcs_in_auto or packed + defect > self.pcs_in:
            return {"pcs_in": packed + defect, "pcs_in_auto": True}
        return {"pcs_defect": self.pcs_in - packed}

    @api.onchange("pcs_in")
    def _onchange_pcs_in_manual(self):
        # qo'lda o'zgartirilgan "kirdi" — endi pachkadan hisoblanmaydi
        if self.pcs_in_auto and self.pcs_in != self.pcs_packed + (self.pcs_defect or 0):
            self.pcs_in_auto = False

    @api.onchange("pcs_defect")
    def _onchange_pcs_defect_auto(self):
        if self.pcs_in_auto and (self.out_packs or self.out_extra):
            self.pcs_in = self.pcs_packed + (self.pcs_defect or 0)

    @api.onchange("out_packs", "out_extra", "product_id")
    def _onchange_out_packs(self):
        if not (self.out_packs or self.out_extra):
            return
        per_pack = self.product_id.craf_pcs_per_pack or self.semi_product_id.craf_pcs_per_pack
        if self.out_packs and not per_pack:
            return {"warning": {
                "title": "Dona / pachka yo'q",
                "message": "%s uchun \"dona / pachka\" kiritilmagan. Mahsulot kartochkasida (Profil) belgilang." %
                           (self.product_id.display_name or self.semi_product_id.display_name),
            }}
        packed = (self.out_packs or 0) * (per_pack or 0) + (self.out_extra or 0)
        self.update(self._craf_packed_vals(packed))
