from odoo import fields, models

PAY_METHODS = [("naqd", "Naqd"), ("plastik", "Plastik"), ("bank", "Bank o'tkazma")]


class AccountJournal(models.Model):
    _inherit = "account.journal"

    craf_pay_method = fields.Selection(PAY_METHODS, string="Craf: to'lov usuli", copy=False,
                                       help="Pul sahifasida shu kassa / hisob qaysi to'lov usuli sifatida ko'rinadi")


class AccountPayment(models.Model):
    _name = "account.payment"
    _inherit = ["account.payment", "craf.c1.mixin"]

    def _craf_c1_ready(self):
        self.ensure_one()
        return self.state in ("in_process", "paid")


class AccountMove(models.Model):
    _inherit = "account.move"

    craf_picking_ids = fields.One2many("stock.picking", "craf_bill_id", string="Kirim hujjatlari")
