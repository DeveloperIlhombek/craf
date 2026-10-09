from . import controllers, models

MIN_QTY = {
    # namuna minimal qoldiqlar (kg) — haqiqiy qiymatlar bilan almashtiriladi
    "PF-01": 3000, "PF-13": 1500, "PF-03": 1000, "PF-15": 1000, "PF-02": 20, "PF-04": 50, "PF-05": 60,
    "PF-08": 40, "XA-02": 5000, "XA-03": 50, "XA-04": 40, "XA-05": 30,
    "XA-01": 100, "XA-06": 150, "XA-07": 150, "XA-08": 100,
}


def post_init_hook(env):
    Product = env["product.product"]
    for code, qty in MIN_QTY.items():
        product = Product.search([("default_code", "=", code)], limit=1)
        if product and not product.craf_min_qty:
            product.product_tmpl_id.craf_min_qty = qty
