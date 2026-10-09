from odoo import models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt


class CrafProductionMixin(models.AbstractModel):
    _inherit = "craf.production.mixin"

    def _craf_check_available(self, location, needs):
        """Jismoniy qoldiq bo'yicha tekshiradi: rejalashtirilgan buyurtmalar band qilgan miqdor ham hisobga
        olinadi — sexda haqiqatda bor narsa sarflanadi, band qilish o'zi bo'shatiladi."""
        missing = []
        for product, qty in needs.items():
            if qty <= EPS or not product.is_storable:
                continue
            on_hand = product.with_context(location=location.id).qty_available
            if qty - on_hand > EPS:
                missing.append("• %s: kerak %s, bor %s %s" % (
                    product.display_name, fmt(qty, 2 if qty % 1 else 0),
                    fmt(on_hand, 2 if on_hand % 1 else 0), product.uom_id.name))
        if missing:
            raise UserError("%s da qoldiq yetarli emas:\n%s\n\nAvval xaritadan ko'chirib keling." % (
                location.display_name, "\n".join(missing)))
