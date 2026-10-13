from collections import OrderedDict

from odoo import models


class CrafKunlikHisobot(models.AbstractModel):
    _inherit = "craf.kunlik.hisobot"

    def _department(self, key, docs):
        res = super()._department(key, docs)
        if key == "pech":
            done = docs.filtered(lambda d: d.state == "done")
            bucket = OrderedDict()
            for d in done:
                self._add(bucket, d.foundry_waste_product_id, d.foundry_waste_qty)
            if bucket:
                res["waste"] = res["waste"] + self._rows(bucket)
        return res
