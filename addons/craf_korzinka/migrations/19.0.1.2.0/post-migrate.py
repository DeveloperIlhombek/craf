"""2026-10-23: korzinkadagi ikkinchi profil (section2_id, qty2_6, qty2_5) → qo'shimcha profillar qatori
(craf.basket.load.line). Bitta korzinkaga endi 2-3 xil profil solish mumkin. Eski ustunlar bazada qoladi."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    cr.execute("""SELECT column_name FROM information_schema.columns
                  WHERE table_name = 'craf_basket_load' AND column_name = 'section2_id'""")
    if not cr.fetchone():
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""SELECT id, section2_id, COALESCE(qty2_6, 0), COALESCE(qty2_5, 0) FROM craf_basket_load
                  WHERE section2_id IS NOT NULL AND (COALESCE(qty2_6, 0) > 0 OR COALESCE(qty2_5, 0) > 0)""")
    rows = cr.fetchall()
    Line = env["craf.basket.load.line"]
    for load_id, section_id, qty_6, qty_5 in rows:
        if not Line.search_count([("load_id", "=", load_id), ("section_id", "=", section_id)]):
            Line.create({"load_id": load_id, "section_id": section_id, "qty_6": qty_6, "qty_5": qty_5})
