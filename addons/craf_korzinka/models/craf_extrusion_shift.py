from odoo import Command, api, fields, models
from odoo.exceptions import UserError


class CrafExtrusionShift(models.Model):
    _inherit = "craf.extrusion.shift"

    basket_load_ids = fields.One2many("craf.basket.load", "shift_id", string="Korzinkalar", copy=False)
    basket_count = fields.Integer("Korzinkalar soni", compute="_compute_basket_totals", store=True,
                                  aggregator="sum")
    basket_pcs = fields.Integer("Korzinkalarda, dona", compute="_compute_basket_totals", store=True,
                                aggregator="sum")
    basket_kg = fields.Float("Korzinkalarda, kg", compute="_compute_basket_totals", store=True,
                             digits=(16, 1), aggregator="sum")

    basket_gross_kg = fields.Float("Brutto jami, kg", compute="_compute_basket_totals", store=True, digits=(16, 1),
                                   aggregator="sum")
    basket_net_kg = fields.Float("Netto jami, kg", compute="_compute_basket_totals", store=True, digits=(16, 1),
                                 aggregator="sum", help="Brutto − korzinka − kryuchok − palka (daftardagi «ИТОГО»)")
    basket_theory_kg = fields.Float("Nazariy jami, kg", compute="_compute_basket_totals", store=True,
                                    digits=(16, 1), aggregator="sum")

    @api.depends("basket_load_ids.pcs_total", "basket_load_ids.kg_theory", "basket_load_ids.net_kg",
                 "basket_load_ids.gross_kg")
    def _compute_basket_totals(self):
        for shift in self:
            loads = shift.basket_load_ids
            shift.basket_count = len(loads)
            shift.basket_pcs = sum(loads.mapped("pcs_total"))
            shift.basket_kg = sum(l.net_kg or l.kg_theory for l in loads)
            shift.basket_gross_kg = sum(loads.mapped("gross_kg"))
            shift.basket_net_kg = sum(loads.mapped("net_kg"))
            shift.basket_theory_kg = sum(loads.mapped("kg_theory"))

    # Yangi korzinka qatori oxirgisidan profil, 1 dona kg, kryuchok va palkani oladi (daftarda odatda bir xil):
    # formada qator konteksti shu maydonlardan default_* qiymat oladi.
    last_section_id = fields.Many2one("craf.profile.section", compute="_compute_last_load")
    last_piece_kg = fields.Float(compute="_compute_last_load", digits=(16, 3))
    last_hook_kg = fields.Float(compute="_compute_last_load", digits=(16, 1))
    last_stick_kg = fields.Float(compute="_compute_last_load", digits=(16, 1))

    @api.depends("basket_load_ids.section_id", "basket_load_ids.piece_kg", "basket_load_ids.hook_kg",
                 "basket_load_ids.stick_kg")
    def _compute_last_load(self):
        for shift in self:
            last = shift.basket_load_ids.filtered("section_id")[-1:]
            shift.last_section_id = last.section_id
            shift.last_piece_kg = last.piece_kg
            shift.last_hook_kg = last.hook_kg if last else 28.0
            shift.last_stick_kg = last.stick_kg if last else 6.0

    def _craf_sync_lines_from_baskets(self):
        """Korzinkalardagi profillarni chiqish qatorlariga yig'adi (boshqa qatorlarga tegmaydi)."""
        for shift in self:
            quantities = shift.basket_load_ids._product_quantities()
            if not quantities:
                continue
            # joy qatorning o'zida: bo'yaladigan profil — Bo'yash sexi, sotiladigan bo'yalmagan — Qadoqlash
            # (kimyoviy ishlov alohida yuritilmaydi)
            commands = [Command.unlink(l.id) for l in shift.line_ids if l.product_id in quantities]
            commands += [Command.create({"product_id": product.id, "pcs": qty}) for product, qty in quantities.items()]
            vals = {"line_ids": commands}
            if not shift.section_id:
                # bir varaqda bir nechta profil — norma eng ko'p chiqqan profildan olinadi
                kg = {}
                for product, qty in quantities.items():
                    kg[product.craf_section_id] = kg.get(product.craf_section_id, 0.0) + qty * product.craf_kg_per_pc
                vals["section_id"] = max(kg, key=kg.get).id
            shift.write(vals)

    def _craf_check_reopen(self):
        moved = self.basket_load_ids.filtered(
            lambda l: l.state != "press" or l.sort_line_ids.filtered(lambda s: s.state == "done"))
        if moved:
            raise UserError("%s ni qaytarib bo'lmaydi: korzinkalar keyingi bosqichga o'tgan (%s). Avval kimyoviy "
                            "ishlov / brak ajratish hujjatini bekor qiling." % (
                                self.name, ", ".join(moved.basket_id.mapped("name"))))
        return super()._craf_check_reopen()

    def action_fill_from_baskets(self):
        drafts = self.filtered(lambda s: s.state == "draft")
        if not drafts.basket_load_ids:
            raise UserError("Avval korzinkalarni kiriting.")
        drafts._craf_sync_lines_from_baskets()
        return True

    def _craf_action_done(self):
        if self.basket_load_ids:
            self._craf_sync_lines_from_baskets()
        return super()._craf_action_done()

    def action_view_baskets(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id("craf_korzinka.action_craf_basket_load")
        action["domain"] = [("shift_id", "=", self.id)]
        action["context"] = {"default_shift_id": self.id}
        return action

