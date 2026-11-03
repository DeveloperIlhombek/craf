"""2026-11-03: kimyoviy ishlovdan o'tgan korzinkalar bo'shatiladi — bo'yash va qadoqlash korzinka bilan ishlamaydi,
profillar Bo'yash sexidagi qoldiqdan bo'yaladi."""
from odoo import SUPERUSER_ID, api, fields


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    loads = env["craf.basket.load"].search([("state", "=", "kimyo")])
    loads.write({"state": "boyash", "returned_date": fields.Date.context_today(loads)})
