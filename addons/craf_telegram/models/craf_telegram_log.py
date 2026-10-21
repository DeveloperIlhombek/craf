from odoo import fields, models


class CrafTelegramLog(models.Model):
    _name = "craf.telegram.log"
    _description = "Telegram xabarlari jurnali"
    _order = "id desc"
    _rec_name = "chat_id"

    date = fields.Datetime("Vaqt", default=fields.Datetime.now, readonly=True)
    chat_id = fields.Char("Telegram ID", readonly=True)
    contact_id = fields.Many2one("craf.bolim.contact", "Kimga", readonly=True, ondelete="set null")
    bolim_id = fields.Many2one("craf.bolim", "Bo'lim", readonly=True, ondelete="set null")
    kind = fields.Selection([("report", "Kunlik hisobot"), ("alert", "Minimal qoldiq"), ("reply", "Botning javobi"),
                             ("test", "Sinov"), ("info", "Boshqa")], "Turi", readonly=True, default="info")
    text = fields.Text("Matn", readonly=True)
    state = fields.Selection([("sent", "Yuborildi"), ("error", "Xato")], "Holat", readonly=True)
    error = fields.Char("Xato", readonly=True)

    def _gc_old(self):
        """90 kundan eski yozuvlar o'chiriladi."""
        self.search([("date", "<", fields.Datetime.subtract(fields.Datetime.now(), days=90))]).unlink()
