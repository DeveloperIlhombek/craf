from odoo import SUPERUSER_ID, api

from odoo.addons.craf_zavod.hooks import apply_layout


def migrate(cr, version):
    """Xaritada Press va Bo'yash orasida «Kimyoviy ishlov» bloki; tartib qayta qo'yiladi."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    apply_layout(env)
    env["ir.config_parameter"].sudo().set_param("craf_zavod.virtual_layout", "{}")
