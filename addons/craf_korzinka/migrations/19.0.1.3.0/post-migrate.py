"""2026-10-23: kimyoviy ishlov alohida yuritilmaydi — press chiqishi to'g'ri Bo'yash sexiga.
«Kimyoviy ishlov» joyidagi bo'yalmagan profillar Bo'yash sexiga ko'chiriladi, korzinka yuklari joyi qayta hisoblanadi."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Loc = env["stock.location"]
    kimyo = Loc.search([("name", "=", "Kimyoviy ishlov"), ("usage", "=", "internal")], limit=1)
    boyash = Loc.search([("name", "=", "Bo'yash sexi"), ("usage", "=", "internal")], limit=1)
    if kimyo and boyash:
        quants = env["stock.quant"].search([("location_id", "=", kimyo.id), ("quantity", ">", 0),
                                            ("product_id.craf_section_id", "!=", False)])
        Move = env["stock.move"]
        for quant in quants:
            move = Move.create({
                "product_id": quant.product_id.id, "product_uom_qty": quant.quantity,
                "product_uom": quant.product_id.uom_id.id, "location_id": kimyo.id,
                "location_dest_id": boyash.id, "origin": "Kimyoviy ishlov bekor qilindi → Bo'yash sexi",
                "company_id": quant.company_id.id or env.company.id,
            })
            move._action_confirm()
            move.quantity = quant.quantity
            move.picked = True
            move._action_done()
    loads = env["craf.basket.load"].search([("state", "in", ("press", "kimyo"))])
    env.add_to_compute(loads._fields["location_id"], loads)
    loads._recompute_recordset(["location_id"])
