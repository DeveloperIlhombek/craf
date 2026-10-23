"""2026-10-23: kunlik hisobot standart soati 8:00 → 11:00 (sozlamada boshqa soat tanlangan bo'lsa, tegilmaydi)."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    param = env["ir.config_parameter"].sudo()
    if (param.get_param("craf_telegram.daily_hour") or "8").strip() == "8":
        param.set_param("craf_telegram.daily_hour", "11")
