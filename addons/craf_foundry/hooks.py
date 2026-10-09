# Namuna shixta retsepti: 1000 kg quyma uchun (prototip, haqiqiy retsept bilan almashtiriladi)
RECIPE = [
    ("PF-01", 540.0),   # Алюминий А8
    ("PF-13", 210.0),   # Бухоро Чушка Профил
    ("PF-03", 125.0),   # Бухоро Чушка Сим
    ("PF-07", 150.0),   # Брак Профиль Отход
    ("PF-05", 6.0),     # Кремний
    ("PF-04", 5.0),     # Магний
    ("PF-02", 1.0),     # Титан
    ("PF-08", 4.0),     # Порошковый Флюс
]
NOT_METAL = ("PF-08", "PF-09", "PF-10")


def post_init_hook(env):
    Product = env["product.product"]
    Product.search([("default_code", "in", NOT_METAL)]).product_tmpl_id.write({"craf_not_metal": True})
    billet = Product.search([("default_code", "=", "XA-09")], limit=1)
    if not billet or env["mrp.bom"].search_count([("product_tmpl_id", "=", billet.product_tmpl_id.id)]):
        return
    lines = []
    for code, qty in RECIPE:
        comp = Product.search([("default_code", "=", code)], limit=1)
        if comp:
            lines.append((0, 0, {"product_id": comp.id, "product_qty": qty, "product_uom_id": comp.uom_id.id}))
    env["mrp.bom"].create({
        "product_tmpl_id": billet.product_tmpl_id.id,
        "product_qty": 1000.0,
        "product_uom_id": billet.uom_id.id,
        "type": "normal",
        "code": "Shixta (namuna)",
        "bom_line_ids": lines,
    })
