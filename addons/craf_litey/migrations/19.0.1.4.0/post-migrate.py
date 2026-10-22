"""2026-10-23: «Brak profil otxod» (PF-07) va «Briket otxod (vtorichka)» (PF-16) — bitta material.

Liteykada ombor mudiri ikkalasini bitta maydonga yozadi (Excel: «брак профил атхот Briket Ft»).
PF-07 nomi «Brak profil + briket otxod» bo'ladi va PF-16 ning Liteyka ro'yxatidagi o'rnini oladi;
PF-16 qoldig'i (bo'lsa) PF-07 ga o'tkaziladi va PF-16 Liteyka ro'yxatidan chiqariladi.
Eski korzinka yuklarida kryuchok/palka yozilmagan — netto o'zgarmasligi uchun ular 0 qilinadi.
"""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Product = env["product.product"].with_context(active_test=False)
    brak = Product.search([("default_code", "=", "PF-07")], limit=1)
    briket = Product.search([("default_code", "=", "PF-16")], limit=1)
    if not brak:
        return
    vals = {"name": "Brak profil + briket otxod", "craf_litey_name": "брак профил атхот Briket Ft"}
    if briket:
        vals.update({"craf_litey_seq": briket.craf_litey_seq or brak.craf_litey_seq,
                     "craf_melt_seq": briket.craf_melt_seq or brak.craf_melt_seq})
    brak.product_tmpl_id.write(vals)
    for lang in env["res.lang"].search([]).mapped("code"):  # nom tarjimalari (uz_UZ va boshqalar)
        brak.product_tmpl_id.with_context(lang=lang).write({"name": vals["name"]})
    if briket:
        Quant = env["stock.quant"]
        for quant in Quant.search([("product_id", "=", briket.id), ("location_id.usage", "=", "internal"),
                                   ("quantity", "!=", 0)]):
            qty, loc = quant.quantity, quant.location_id
            inv = briket.property_stock_inventory
            for product, src, dst in ((briket, loc, inv), (brak, inv, loc)) if qty > 0 else (
                    (briket, inv, loc), (brak, loc, inv)):
                move = env["stock.move"].create({
                    "product_id": product.id, "product_uom_qty": abs(qty), "product_uom": product.uom_id.id,
                    "location_id": src.id, "location_dest_id": dst.id, "is_inventory": True,
                    "origin": "Brak + briket birlashtirildi (PF-16 → PF-07)", "company_id": loc.company_id.id or env.company.id,
                })
                move._action_confirm()
                move.quantity = abs(qty)
                move.picked = True
                move._action_done()
        briket.product_tmpl_id.write({"craf_litey_hidden": True})
    if "hook_kg" in env["craf.basket.load"]._fields:
        env["craf.basket.load"].search([]).write({"hook_kg": 0.0, "stick_kg": 0.0})
