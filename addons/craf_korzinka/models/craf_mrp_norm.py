from odoo import fields, models


class CrafMrpNorm(models.Model):
    _inherit = "craf.mrp.norm"

    chem_m2_h = fields.Float("Kimyoviy ishlov, m²/soat", default=80.0)
    wc_chem_id = fields.Many2one("mrp.workcenter", "Kimyoviy ishlov vannasi")

    def action_generate_boms(self):
        res = super().action_generate_boms()
        self._craf_add_chem_operation()
        return res

    def _craf_add_chem_operation(self):
        """Bo'yalgan profil BoM iga 'Kimyoviy ishlov' operatsiyasini qo'shadi, kimyo shu operatsiyada sarflanadi."""
        self.ensure_one()
        if not self.wc_chem_id:
            return
        chem_products = self.env["product.product"].search([("default_code", "in", ("XA-03", "XA-04", "XA-05"))])
        Op = self.env["mrp.routing.workcenter"]
        boms = self.env["mrp.bom"].search([("craf_auto", "=", True), ("product_tmpl_id.craf_color_id.is_painted", "=", True)])
        for bom in boms:
            tmpl = bom.product_tmpl_id
            area_pc = (tmpl.craf_length_m or 0.0) * (tmpl.craf_section_id.perimeter_m or 0.0)
            semi_line = bom.bom_line_ids.filtered(lambda l: l.product_id.craf_section_id)[:1]
            area = (semi_line.product_qty if semi_line else bom.product_qty) * area_pc
            minutes = max(round(area / max(self.chem_m2_h, 1) * 60, 2), 0.1) if area else bom.product_qty * 0.3
            op = bom.operation_ids.filtered(lambda o: o.name == "Kimyoviy ishlov")[:1]
            vals = {"name": "Kimyoviy ishlov", "workcenter_id": self.wc_chem_id.id, "time_mode": "manual",
                    "time_cycle_manual": minutes, "sequence": 5}
            if op:
                op.write(vals)
            else:
                op = Op.create(dict(vals, bom_id=bom.id))
            bom.bom_line_ids.filtered(lambda l: l.product_id in chem_products).write({"operation_id": op.id})
