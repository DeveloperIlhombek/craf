# Prototip uchun standart sxema: nomi bo'yicha joylashuvlarni xaritaga qo'yadi
LAYOUT = {
    "Xom-ashyo ombori": (10, "raw", 40, 70, 250, 190),
    "Литейка": (20, "process", 350, 70, 230, 190),
    "Press sexi": (30, "process", 640, 70, 230, 190),
    "Bo'yash sexi": (40, "process", 930, 70, 250, 190),
    "Qadoqlash": (50, "process", 930, 360, 250, 200),
    "Tayyor mahsulot ombori": (60, "finished", 350, 360, 520, 200),
    "Chiqindi": (70, "waste", 40, 360, 250, 200),
}


def post_init_hook(env):
    Location = env["stock.location"]
    for name, (seq, kind, x, y, w, h) in LAYOUT.items():
        for loc in Location.search([("name", "=", name), ("usage", "=", "internal")]):
            loc.write({
                "craf_map_show": True, "craf_map_sequence": seq, "craf_map_kind": kind,
                "craf_map_x": x, "craf_map_y": y, "craf_map_w": w, "craf_map_h": h,
            })
