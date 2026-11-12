from odoo import SUPERUSER_ID, api

from odoo.addons.craf_zavod.hooks import apply_layout


def migrate(cr, version):
    """Xaritada «Bo'yash sexi» va «Qadoqlash» bitta blok: Bo'yash bloki kengayadi, Qadoqlash bloki yashiriladi."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    apply_layout(env, names={"Bo'yash sexi", "Qadoqlash"})
