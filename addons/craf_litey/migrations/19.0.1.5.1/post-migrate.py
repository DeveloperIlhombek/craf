"""2026-10-29: Liteyka sozlamalari, qirindi (PF-20), nomli smenalar (eski plavkalar: 1-smena → Kunduzgi, 2/3 → Tungi)."""
from odoo import SUPERUSER_ID, api

from odoo.addons.craf_litey.hooks import craf_setup_settings


def migrate(cr, version):
    craf_setup_settings(api.Environment(cr, SUPERUSER_ID, {}))
