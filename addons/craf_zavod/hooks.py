# Standart sxema (real oqim tartibida): nomi bo'yicha joylashuvlarni xaritaga qo'yadi.
# (tartib, tur, x, y, eni, bo'yi, ko'rsatish) — keyin xaritadagi «Tartiblash» rejimida surib o'zgartiriladi.
LAYOUT = {
    "Литейка": (10, "process", 330, 90, 230, 190, True),
    "Press sexi": (20, "process", 670, 90, 230, 190, True),
    "Kimyoviy ishlov": (25, "process", 670, 700, 230, 170, False),
    "Bo'yash sexi": (30, "process", 1010, 90, 230, 190, True),
    "Qadoqlash": (40, "process", 1350, 90, 200, 190, True),
    "Tayyor mahsulot ombori": (50, "finished", 1010, 430, 540, 190, True),
    "Xom-ashyo ombori": (60, "raw", 330, 430, 230, 190, True),
    "Chiqindi": (70, "waste", 30, 430, 190, 190, True),
}


def apply_layout(env):
    Location = env["stock.location"]
    for name, (seq, kind, x, y, w, h, show) in LAYOUT.items():
        for loc in Location.search([("name", "=", name), ("usage", "=", "internal")]):
            loc.write({
                "craf_map_show": show, "craf_map_sequence": seq, "craf_map_kind": kind,
                "craf_map_x": x, "craf_map_y": y, "craf_map_w": w, "craf_map_h": h,
            })


def post_init_hook(env):
    apply_layout(env)
