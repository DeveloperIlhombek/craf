"""2026-11-04: rang kartochkasidagi «Stiker yopishqoqligi» o'rniga — Stiker qoidalari (craf.sticker.choice).
High tanlangan ranglar (Antratsit) bitta qoidaga ko'chiriladi: «shu ranglar → High (80 mic)»."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    cr.execute("SELECT 1 FROM information_schema.columns "
               "WHERE table_name = 'craf_color' AND column_name = 'craf_sticker_adhesion'")
    if not cr.fetchone():
        return
    cr.execute("SELECT id FROM craf_color WHERE craf_sticker_adhesion = 'high'")
    color_ids = [row[0] for row in cr.fetchall()]
    env = api.Environment(cr, SUPERUSER_ID, {})
    Choice = env["craf.sticker.choice"]
    if color_ids and not Choice.with_context(active_test=False).search_count([("adhesion", "=", "high")]):
        Choice.create({"color_ids": [(6, 0, color_ids)], "adhesion": "high",
                       "note": "Antratsit bo'yoq — 80 mic stiker (rang sozlamasidan ko'chirildi)"})
