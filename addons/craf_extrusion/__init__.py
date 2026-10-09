from . import models


def post_init_hook(env):
    env["product.template"]._craf_ensure_semi_products()
