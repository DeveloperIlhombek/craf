from odoo import api, fields, models
from odoo.exceptions import UserError


class CrafPackWizard(models.TransientModel):
    _name = "craf.pack.wizard"
    _description = "Pachka yorlig'i chiqarish"

    product_id = fields.Many2one("product.product", "Mahsulot", required=True,
                                 domain=[("craf_section_id", "!=", False)])
    pcs_per_pack = fields.Integer("Dona / pachka", compute="_compute_pcs_per_pack", store=True, readonly=False)
    pack_count = fields.Integer("Pachkalar soni", default=1)
    kg_actual = fields.Float("Haqiqiy kg (1 pachka)", digits=(16, 2),
                             help="Tortilgan bo'lsa yozing; bo'sh qolsa yorliqda qo'lda yoziladigan joy qoladi.")
    location_id = fields.Many2one("stock.location", "Joylashuv", domain=[("usage", "=", "internal")],
                                  default=lambda self: self._default_location())
    origin = fields.Char("Manba hujjat")
    note = fields.Char("Izoh")
    summary = fields.Char("Jami", compute="_compute_summary")

    @api.model
    def _default_location(self):
        return self.env["stock.location"].search([("name", "=", "Qadoqlash"), ("usage", "=", "internal")], limit=1)

    @api.depends("product_id")
    def _compute_pcs_per_pack(self):
        for wiz in self:
            wiz.pcs_per_pack = wiz.product_id.craf_pcs_per_pack or wiz.pcs_per_pack

    @api.depends("product_id", "pcs_per_pack", "pack_count")
    def _compute_summary(self):
        for wiz in self:
            if not wiz.product_id or wiz.pcs_per_pack <= 0 or wiz.pack_count <= 0:
                wiz.summary = False
                continue
            pcs = wiz.pcs_per_pack * wiz.pack_count
            kg = pcs * (wiz.product_id.craf_kg_per_pc or 0.0)
            wiz.summary = "%s pachka × %s dona = %s dona · %s kg" % (
                wiz.pack_count, wiz.pcs_per_pack, pcs, ("%.1f" % kg).replace(".", ","))

    def action_create(self):
        self.ensure_one()
        if self.pcs_per_pack <= 0:
            raise UserError("Pachkadagi dona sonini kiriting.")
        if not 0 < self.pack_count <= 500:
            raise UserError("Pachkalar soni 1 dan 500 gacha bo'lishi kerak.")
        packs = self.env["craf.pack"].create([{
            "product_id": self.product_id.id,
            "pcs": self.pcs_per_pack,
            "kg_actual": self.kg_actual,
            "location_id": self.location_id.id,
            "origin": self.origin,
            "note": self.note,
        } for _i in range(self.pack_count)])
        action = packs.action_print()
        action["close_on_report_download"] = True
        return action
