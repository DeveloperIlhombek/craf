from odoo import models


def _money(value):
    return "{:,.0f}".format(value or 0.0).replace(",", " ")


class CrafLiteyKirim(models.TransientModel):
    _inherit = "craf.litey.kirim"

    def _craf_create_picking(self):
        picking = super()._craf_create_picking()
        picking._craf_auto_bill(self.date)
        return picking


class CrafLiteyHisobot(models.AbstractModel):
    _inherit = "craf.litey.hisobot"

    def _return_picking(self, picking):
        new = super()._return_picking(picking)
        if picking.craf_bill_id:
            new._craf_bill_return(picking)
        return new

    def _picking_detail(self, picking):
        res = super()._picking_detail(picking)
        bill = picking.craf_bill_id
        if bill or picking._craf_is_supply():
            if bill and bill.state == "posted":
                paid = bill.amount_total - bill.amount_residual
                state = "to'langan" if bill.payment_state in ("paid", "in_payment") else (
                    "qarz %s" % _money(bill.amount_residual) if not paid else
                    "to'langan %s, qarz %s" % (_money(paid), _money(bill.amount_residual)))
                res["meta"].append(("Hisob-faktura", "%s · %s %s · %s" % (
                    bill.name, _money(bill.amount_total), bill.currency_id.symbol or "", state)))
            elif bill and bill.state == "cancel":
                res["meta"].append(("Hisob-faktura", "%s bekor qilingan" % bill.name))
            else:
                missing = picking._craf_bill_missing()
                if missing:
                    res["warning"] = ("Hisob-faktura yo'q: %s yozilmagan. Pul sahifasida «Hisob-fakturasiz kirim» "
                                      "dan to'ldiring." % " va ".join(missing))
        return res
