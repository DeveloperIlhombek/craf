from . import controllers, models, wizard


def _craf_diller_post_init(env):
    """Hisob-faktura berilgan miqdor bo'yicha bo'lsin: aks holda qisman berish va qaytarishda qarz noto'g'ri bo'ladi."""
    env["product.template"].sudo().with_context(active_test=False).search(
        [("sale_ok", "=", True), ("type", "=", "consu"), ("invoice_policy", "!=", "delivery")]
    ).write({"invoice_policy": "delivery"})
