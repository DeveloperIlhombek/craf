from odoo import api, fields, models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    craf_melt_seq = fields.Integer(
        "Plavka daftarida tartib",
        help="0 dan katta bo'lsa, yangi plavkada shu tartibda bo'sh qator bo'lib turadi (ishchi faqat raqam yozadi).")
    craf_litey_seq = fields.Integer(
        "Литейка hisobotida tartib", help="0 dan katta bo'lsa, Литейка hisoboti va Excel jadvalida ko'rinadi.")
    craf_litey_name = fields.Char(
        "Excel dagi nomi", help="Литейка Excel jadvalidagi qator nomi — eksport va import shu nom bilan.")
    craf_litey_location_id = fields.Many2one(
        "stock.location", string="Asosiy joy", domain=[("usage", "=", "internal")],
        help="Excel qoldig'i yuklanganda shu joyga yoziladi (bo'sh bo'lsa — Литейка).")
    craf_litey_hidden = fields.Boolean(
        "Литейка ro'yxatidan chiqarilgan", copy=False,
        help="Material Литейка hisobotida ko'rinmaydi, lekin mahsulot va uning tarixi Inventarizatsiya da qoladi. "
             "Литейка hisoboti → material → «Qaytarish» bilan qaytariladi.")

    @api.model
    def _craf_setup_press_waste(self):
        """Питак, brak, briket — press chiqindisi; quymalarga питак mahsuloti (o'rnatish/yangilashda, bo'sh bo'lsa)."""
        def tmpl(code):
            return self.search([("default_code", "=", code)], limit=1)
        for code in ("PF-06", "PF-07", "PF-16", "PF-17", "PF-18"):
            t = tmpl(code)
            if t and not t.craf_press_waste:
                t.craf_press_waste = True
        for billet, butt in (("XA-09", "PF-06"), ("XA-02", "PF-18")):
            b, p = tmpl(billet), tmpl(butt)
            if b and p and not b.craf_butt_product_id:
                b.craf_butt_product_id = p.product_variant_id
