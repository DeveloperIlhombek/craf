from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Yuklanayotgan buyurtmalarda «Yuklandi» belgilangan qatorlar joy bo'yicha rejaga o'tkaziladi."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Alloc = env["craf.load.alloc"]
    orders = env["sale.order"].search([("craf_load_state", "in", ("queue", "loading"))])
    for order in orders:
        for move in order._craf_open_pickings().move_ids.filtered(
                lambda m: m.state not in ("done", "cancel") and m.picked and m.quantity > 0):
            if not Alloc.search_count([("move_id", "=", move.id)]):
                Alloc.create({"move_id": move.id, "order_id": order.id, "location_id": move.location_id.id,
                              "qty": move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)})
            move.picked = False
