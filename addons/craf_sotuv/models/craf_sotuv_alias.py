from odoo import api, fields, models

from .parser import compact

ALIAS_KINDS = [
    ("item", "Mahsulot turi (L, T, Sh1 ...)"),
    ("group", "Seriya / rang sarlavhasi (Kraf antrasid, oq ...)"),
    ("location", "Joy (Zavod, Parnik, Rohat)"),
    ("product", "Aniq mahsulot (o'rgatilgan)"),
    ("partner", "Mijoz (o'rgatilgan)"),
    ("ignore", "E'tiborsiz so'z"),
]


class CrafSotuvAlias(models.Model):
    _name = "craf.sotuv.alias"
    _description = "Buyurtma qisqartmasi"
    _order = "kind, sequence, name"

    name = fields.Char("Yoziladi", required=True, help="Buyurtmada qanday yoziladi: L, TB, Sh1, Kraf, oq ...")
    key = fields.Char("Kalit", index=True, readonly=True,
                      help="Qidiruv kaliti (kichik harf, bo'shliqsiz). O'rgatilgan mahsulotda — qator + kontekst.")
    kind = fields.Selection(ALIAS_KINDS, string="Turi", required=True, default="item")
    sequence = fields.Integer(default=10)
    section_type = fields.Char("Profil turi", help="Kesimdagi 'Tur': L, T, Z, Штапик 104, Ламбер, Ёлка ...")
    series = fields.Char("Seriya", help="Kesimdagi seriya: Бал, CRAF, ALUSAM. Bir nechta bo'lsa: Эко|Эконом")
    color_id = fields.Many2one("craf.color", "Rang")
    family_type = fields.Char("Oila (profil turi)", help="Sarlavha uchun: 'Termo yolka' → Ёлка")
    filter_words = fields.Char("Nomida bo'lishi kerak", help="Bo'shliq bilan: термо")
    length_m = fields.Float("Uzunlik, m")
    location_id = fields.Many2one("stock.location", "Joy", domain=[("usage", "=", "internal")])
    product_id = fields.Many2one("product.product", "Mahsulot")
    partner_id = fields.Many2one("res.partner", "Mijoz")
    note = fields.Char("Izoh")
    active = fields.Boolean(default=True)

    _key_uniq = models.Constraint("UNIQUE(kind, key)", "Bu qisqartma lug'atda bor.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("key"):
                vals["key"] = compact(vals.get("name"))
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        if "name" in vals and "key" not in vals:
            for rec in self.filtered(lambda r: r.kind not in ("product",)):
                rec.key = compact(rec.name)
        return res

    @api.model
    def _craf_entries(self):
        """Ajratuvchi (parser) uchun lug'at."""
        entries = []
        for rec in self.search([]):
            entry = {"kind": rec.kind, "key": rec.key}
            if rec.kind == "item":
                entry.update({
                    "type": rec.section_type or None,
                    "series": [s.strip() for s in (rec.series or "").split("|") if s.strip()],
                    "filter": (rec.filter_words or "").lower().split(),
                })
            elif rec.kind == "group":
                entry.update({
                    "series": [s.strip() for s in (rec.series or "").split("|") if s.strip()],
                    "color": rec.color_id.id or None,
                    "family_type": rec.family_type or None,
                    "filter": (rec.filter_words or "").lower().split(),
                    "length": rec.length_m or None,
                })
            elif rec.kind == "location":
                entry["location_id"] = rec.location_id.id
            elif rec.kind == "product":
                entry["product_id"] = rec.product_id.id
            elif rec.kind == "partner":
                entry["partner_id"] = rec.partner_id.id
            entries.append(entry)
        return entries
