from . import controllers, models


def _craf_pul_post_init(env):
    env["craf.pul"]._setup()
