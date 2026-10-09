import random

# Kimyoviy ishlov qo'shilgandan keyingi xarita joylashuvi: (tartib, tur, x, y, w, h)
LAYOUT = {
    "Xom-ashyo ombori": (10, "raw", 40, 70, 188, 190),
    "Литейка": (20, "process", 288, 70, 188, 190),
    "Press sexi": (30, "process", 536, 70, 188, 190),
    "Kimyoviy ishlov": (35, "process", 784, 70, 188, 190),
    "Bo'yash sexi": (40, "process", 1032, 70, 188, 190),
    "Qadoqlash": (50, "process", 1032, 360, 188, 200),
    "Tayyor mahsulot ombori": (60, "finished", 288, 360, 684, 200),
    "Chiqindi": (70, "waste", 40, 360, 188, 200),
}


def post_init_hook(env):
    Location = env["stock.location"]
    warehouse = env["stock.warehouse"].search([("company_id", "=", env.company.id)], limit=1)
    kimyo = Location.search([("name", "=", "Kimyoviy ishlov"), ("usage", "=", "internal")], limit=1)
    if not kimyo and warehouse:
        kimyo = Location.create({
            "name": "Kimyoviy ishlov",
            "usage": "internal",
            "location_id": warehouse.view_location_id.id,
        })
    for name, (seq, kind, x, y, w, h) in LAYOUT.items():
        for loc in Location.search([("name", "=", name), ("usage", "=", "internal")]):
            loc.write({
                "craf_map_show": True, "craf_map_sequence": seq, "craf_map_kind": kind,
                "craf_map_x": x, "craf_map_y": y, "craf_map_w": w, "craf_map_h": h,
            })

    # Press bosqichi endi profillarni kimyoviy ishlovga beradi
    norm = env["craf.mrp.norm"]._get_norm(env.company)
    if kimyo and norm.press_type_id:
        norm.press_type_id.default_location_dest_id = kimyo
    norm.wc_chem_id = env.ref("craf_korzinka.wc_chem")
    norm.action_generate_boms()

    # Namuna korzinkalar (prototip): K-001 … K-030
    Basket = env["craf.basket"]
    if not Basket.search_count([]):
        rnd = random.Random(42)
        Basket.create([{"name": "K-%03d" % i, "tare_kg": rnd.choice([38, 40, 42, 45, 48, 50]), "capacity": 120}
                       for i in range(1, 31)])
        env.ref("craf_korzinka.seq_craf_basket").number_next = 31
