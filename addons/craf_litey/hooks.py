# Литейка qatorlari: (kod, Excel dagi nomi, hisobot tartibi, daftar tartibi, asosiy joy)
# Tartib foydalanuvchining Excel jadvali (Лист1) va ishchi daftari bo'yicha.
LITEY_ROWS = [
    ("XA-09", "Литейка балка", 10, 0, "Press sexi"),
    ("XA-02", "Русал", 20, 0, "Press sexi"),
    ("PF-01", "Алюминий А8", 30, 90, "Литейка"),
    ("PF-09", "Талк", 40, 250, "Литейка"),
    ("PF-05", "Кремний", 50, 130, "Литейка"),
    ("PF-04", "Магний", 60, 140, "Литейка"),
    ("PF-02", "Титан", 70, 150, "Литейка"),
    # 75 — "Ишлаб чикарилган литейка" (plavkalardan, hisobotda hisoblanadi)
    ("PF-08", "Порошок Флюс", 80, 210, "Литейка"),
    ("PF-16", "Брикет отход(вторичка)", 90, 10, "Литейка"),
    ("PF-06", "Питак отход(вторичка)", 100, 30, "Литейка"),
    ("PF-17", "Брикет отход(русал)", 110, 100, "Литейка"),
    ("PF-18", "Питак отход(русал)", 120, 110, "Литейка"),
    ("PF-12", "Сталба Отход", 130, 50, "Литейка"),
    ("PF-11", "Литейка Отход", 140, 60, "Литейка"),
    ("PF-13", "Бухоро чушка Юмшок", 150, 40, "Литейка"),
    ("PF-15", "Бухоро чушка Банка", 160, 70, "Литейка"),
    ("PF-03", "Бухоро чушка Сим", 170, 80, "Литейка"),
    ("LS-02", "Пробка", 180, 230, "Литейка"),
    ("PF-14", "Алюминевый Шлак", 185, 0, "Chiqindi"),
    ("LS-03", "Стекловата", 190, 240, "Литейка"),
    ("LS-01", "Керамический Фильтр", 200, 220, "Литейка"),
    ("PF-07", "Брак Профиль Отход", 210, 20, "Литейка"),
    ("PF-19", "Алюминий Диск", 220, 120, "Литейка"),
    ("PF-10", "Огнеупорный Бетон", 230, 0, "Литейка"),
]

RENAMES = {
    "PF-13": "Бухоро Чушка Юмшоқ",          # foydalanuvchi: Профил = Юмшоқ (13.10.2026)
    "PF-06": "Питак Отход (вторичка)",
}
NOT_METAL = ("PF-08", "PF-09", "PF-10", "LS-01", "LS-02", "LS-03")


def post_init_hook(env):
    Product = env["product.product"].with_context(active_test=False)
    Location = env["stock.location"]
    for code, name in RENAMES.items():
        Product.search([("default_code", "=", code)]).product_tmpl_id.write({"name": name})
    Product.search([("default_code", "in", NOT_METAL)]).product_tmpl_id.write({"craf_not_metal": True})
    for code, excel_name, seq, melt_seq, loc_name in LITEY_ROWS:
        tmpl = Product.search([("default_code", "=", code)], limit=1).product_tmpl_id
        if not tmpl:
            continue
        loc = Location.search([("name", "=", loc_name), ("usage", "=", "internal")], limit=1)
        tmpl.write({
            "craf_litey_name": excel_name,
            "craf_litey_seq": seq,
            "craf_melt_seq": melt_seq,
            "craf_litey_location_id": loc.id or False,
        })
    craf_setup_settings(env)


def craf_setup_settings(env):
    """19.0.1.5.0: Liteyka sozlamalari, qirindi (PF-20) va nomli smenalar; eski plavkalarga smena biriktirish."""
    Product = env["product.product"].with_context(active_test=False)
    chip = Product.search([("default_code", "=", "PF-20")], limit=1)
    litey = env["stock.location"].search([("name", "=", "Литейка"), ("usage", "=", "internal")], limit=1)
    if chip and litey and not chip.craf_litey_location_id:
        chip.product_tmpl_id.craf_litey_location_id = litey
    cfg = env["craf.litey.settings"].get()
    if chip and not cfg.chip_product_id:
        cfg.chip_product_id = chip
    Shift = env["craf.litey.shift"].with_context(active_test=False)
    shifts = Shift.search([], order="sequence, id")
    if shifts:
        shifts.filtered(lambda s: not s.settings_id).write({"settings_id": cfg.id})
        day, night = shifts[0], shifts[1:2] or shifts[0]
        Melt = env["craf.foundry.melt"].with_context(active_test=False)
        for code, shift in (("1", day), ("2", night), ("3", night)):
            Melt.search([("shift_id", "=", False), ("shift", "=", code)]).write({"shift_id": shift.id})
