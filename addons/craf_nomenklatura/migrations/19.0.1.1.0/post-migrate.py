"""19.0.1.1.0: Toifalarni jadvaldagi tuzilishga keltirish.

Xom-ashyo -> Хом-ашё, Полуфабрикаты ; Tayyor mahsulot.
Ma'lumotlar noupdate bo'lgani uchun mavjud yozuvlar shu yerda yangilanadi.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    root = env.ref("craf_nomenklatura.categ_raw_root", raise_if_not_found=False)
    if not root:
        return
    raw = env.ref("craf_nomenklatura.categ_raw", raise_if_not_found=False)
    semi = env.ref("craf_nomenklatura.categ_semi", raise_if_not_found=False)
    fin = env.ref("craf_nomenklatura.categ_finished", raise_if_not_found=False)
    if raw:
        raw.write({"name": "Хом-ашё", "parent_id": root.id})
    if semi:
        semi.write({"name": "Полуфабрикаты", "parent_id": root.id})
        for tmpl in env["product.template"].with_context(active_test=False).search([("categ_id", "=", semi.id)]):
            if tmpl.default_code and tmpl.default_code.startswith("LT-"):
                tmpl.default_code = "PF-" + tmpl.default_code[3:]
    if fin:
        fin.write({"name": "Tayyor mahsulot"})
