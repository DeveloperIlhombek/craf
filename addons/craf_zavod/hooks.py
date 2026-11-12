# Standart sxema (real oqim tartibida): nomi bo'yicha joylashuvlarni xaritaga qo'yadi.
# (tartib, tur, x, y, eni, bo'yi, ko'rsatish) — keyin xaritadagi «Tartiblash» rejimida surib o'zgartiriladi.
LAYOUT = {
    "Литейка": (10, "process", 330, 90, 220, 190, True),
    "Press sexi": (20, "process", 660, 90, 220, 190, True),
    "Kimyoviy ishlov": (25, "process", 990, 90, 220, 190, True),
    "Bo'yash sexi": (30, "process", 1320, 90, 380, 190, True),
    "Qadoqlash": (40, "process", 1320, 760, 200, 170, False),  # xaritada Bo'yash bilan bitta blok
    "Tayyor mahsulot ombori": (50, "finished", 1320, 430, 380, 190, True),
    "Xom-ashyo ombori": (60, "raw", 660, 430, 220, 190, True),
    "Chiqindi": (70, "waste", 30, 430, 190, 190, True),
}


def apply_layout(env, names=None):
    Location = env["stock.location"]
    for name, (seq, kind, x, y, w, h, show) in LAYOUT.items():
        if names and name not in names:
            continue
        for loc in Location.search([("name", "=", name), ("usage", "=", "internal")]):
            loc.write({
                "craf_map_show": show, "craf_map_sequence": seq, "craf_map_kind": kind,
                "craf_map_x": x, "craf_map_y": y, "craf_map_w": w, "craf_map_h": h,
            })


def post_init_hook(env):
    apply_layout(env)
