from . import models, wizard

# stiker.xlsx (2026-10-24) — real qoldiq, rulon: (logo, yopishqoqlik, kenglik mm) -> rulon
# 4-qator (CRAF High 52 mm): foydalanuvchi tasdig'i bilan «Umumiy rulonlar» = 768
INITIAL_ROLLS = {
    ("CRAF", "medium", 40): 8880, ("CRAF", "medium", 52): 2128, ("CRAF", "high", 40): 8020,
    ("CRAF", "high", 52): 768, ("CRAF", "medium", 68): 1848, ("CRAF", "high", 68): 144,
    ("Alusam", "medium", 40): 2200, ("Alusam", "medium", 52): 1104, ("Alusam", "medium", 68): 756,
    ("Alusam", "high", 40): 2500, ("Alusam", "high", 52): 1008, ("Alusam", "high", 68): 696,
    ("Crose", "medium", 40): 1440, ("Crose", "medium", 52): 544, ("Crose", "medium", 68): 312,
    ("Crose", "high", 40): 460, ("Crose", "high", 52): 200, ("Crose", "high", 68): 115,
    ("Alrom", "medium", 40): 840, ("Alrom", "medium", 52): 368, ("Alrom", "medium", 68): 212,
    ("Alrom", "high", 40): 320, ("Alrom", "high", 52): 140, ("Alrom", "high", 68): 80,
}


def post_init_hook(env):
    # Antratsit ranglariga High (80 mic) stiker
    env["craf.color"].search(["|", "|", ("code", "in", ("J306", "1376")), ("name", "ilike", "Антрацит"),
                              ("name", "ilike", "antrasit")]).write({"craf_sticker_adhesion": "high"})
    # boshlang'ich qoldiq — faqat hali qoldig'i yo'q stikerlarga
    counts = {}
    for sticker in env["craf.sticker"].search([]):
        rolls = INITIAL_ROLLS.get((sticker.logo_id.name, sticker.adhesion, sticker.width_mm))
        if rolls and not sticker.qty_m:
            counts[sticker] = rolls
    if counts:
        env["craf.sticker"]._craf_apply_count(counts, "stiker.xlsx boshlang'ich qoldiq")
