from . import models

# Namuna o'ramlar (haqiqiy qiymatlar bilan almashtiriladi): kod -> (nomi, 1 o'ram kg)
PACKAGES = {
    "XA-01": ("quti", 20.0), "XA-06": ("quti", 20.0), "XA-07": ("quti", 20.0), "XA-08": ("quti", 20.0),
    "XA-03": ("kanistr", 25.0), "XA-04": ("kanistr", 25.0), "XA-05": ("kanistr", 25.0),
    "PF-08": ("qop", 25.0), "PF-09": ("qop", 25.0), "PF-10": ("qop", 25.0),
}


def post_init_hook(env):
    Product = env["product.product"]
    for code, (name, kg) in PACKAGES.items():
        product = Product.search([("default_code", "=", code)], limit=1)
        if product and not product.craf_pkg_kg:
            product.product_tmpl_id.write({"craf_pkg_name": name, "craf_pkg_kg": kg})
