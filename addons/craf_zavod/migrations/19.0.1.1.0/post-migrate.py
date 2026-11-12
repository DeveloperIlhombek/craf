from odoo import SUPERUSER_ID, api

from odoo.addons.craf_zavod.hooks import apply_layout


def migrate(cr, version):
    """Yangi xarita: bloklar real oqim tartibida, «Kimyoviy ishlov» (ishlatilmaydi) yashiriladi."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    apply_layout(env)
    env["ir.config_parameter"].sudo().set_param("craf_zavod.virtual_layout", "{}")
