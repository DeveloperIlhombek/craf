from .models.parser import compact

# (xabarda, profil turi, seriya, filtr)
ITEMS = [
    ("L", "L", "", ""), ("T", "T", "", ""), ("Z", "Z", "", ""),
    ("LB", "L", "Бал", ""), ("TB", "T", "Бал", ""), ("ZB", "Z", "Бал", ""),
    ("TE", "T", "Эко|Эконом", ""), ("ZE", "Z", "Эко|Эконом", ""),
    ("TT", "T", "Термо|Бал Термо", ""),
    ("Sh1", "Штапик 104", "", ""), ("Sh2", "Штапик 105", "", ""),
    ("Shtapik 104", "Штапик 104", "", ""), ("Shtapik 105", "Штапик 105", "", ""),
    ("Lambir", "Ламбер", "", ""), ("Lamber", "Ламбер", "", ""), ("Lambr", "Ламбер", "", ""),
    ("Krishka", "Крышка", "", ""), ("Kirishka", "Крышка", "", ""), ("Kryshka", "Крышка", "", ""),
    ("Qopqoq", "Крышка", "", ""),
    ("Prijim", "Прижим", "", ""), ("Prijm", "Прижим", "", ""), ("Prijom", "Прижим", "", ""),
    ("Saydinitel", "Соединитель", "", ""), ("Soydinitel", "Соединитель", "", ""),
    ("Soedinitel", "Соединитель", "", ""), ("Saedinitel", "Соединитель", "", ""),
    ("Opora", "Опора", "", ""),
    ("Chip", "Чип Кулок", "", ""), ("Chip kulok", "Чип Кулок", "", ""),
    ("Kosa", "Коса", "", ""),
    ("Gradus", "Градус 90", "", ""), ("Gradus 90", "Градус 90", "", ""), ("Gr90", "Градус 90", "", ""),
    ("Yolka", "Ёлка", "", ""), ("Yelka", "Ёлка", "", ""), ("Elka", "Ёлка", "", ""),
    ("Samled", "Самлед Техно", "", ""),
]
# (xabarda, seriya, rang xml id, oila, filtr)
GROUPS = [
    ("Kraf", "CRAF", None, "", ""), ("Craf", "CRAF", None, "", ""), ("Kref", "CRAF", None, "", ""),
    ("Alusam", "ALUSAM", None, "", ""), ("Alyusam", "ALUSAM", None, "", ""),
    ("Bal", "Бал", None, "", ""), ("Eko", "Эко|Эконом", None, "", ""), ("Ekonom", "Эконом", None, "", ""),
    ("Termo", "Термо|Бал Термо", None, "", ""),
    ("Oq", "", "craf_nomenklatura.color_9016", "", ""), ("Ok", "", "craf_nomenklatura.color_9016", "", ""),
    ("Oppoq", "", "craf_nomenklatura.color_9016", "", ""), ("Beliy", "", "craf_nomenklatura.color_9016", "", ""),
    ("Belyy", "", "craf_nomenklatura.color_9016", "", ""), ("9016", "", "craf_nomenklatura.color_9016", "", ""),
    ("Antrasid", "", "craf_nomenklatura.color_j306", "", ""),
    ("Antrasit", "", "craf_nomenklatura.color_j306", "", ""),
    ("Antratsit", "", "craf_nomenklatura.color_j306", "", ""),
    ("J306", "", "craf_nomenklatura.color_j306", "", ""),
    ("Matt", "", "craf_nomenklatura.color_7016", "", ""), ("Mat", "", "craf_nomenklatura.color_7016", "", ""),
    ("7016", "", "craf_nomenklatura.color_7016", "", ""),
    ("Dub", "", "craf_nomenklatura.color_8003", "", ""), ("Zolotoy dub", "", "craf_nomenklatura.color_8003", "", ""),
    ("8003", "", "craf_nomenklatura.color_8003", "", ""),
    ("Xom", "", "craf_nomenklatura.color_raw", "", ""),
    ("Bo'yalmagan", "", "craf_nomenklatura.color_raw", "", ""),
    ("Termo yolka", "", None, "Ёлка", "термо"), ("Yolka termo", "", None, "Ёлка", "термо"),
]
LOCATIONS = [("Zavod", None), ("Sklad", None), ("Ombor", None), ("Parnik", "Parnik"), ("Rohat", "Rohat")]


def _sale_points(env):
    Location = env["stock.location"]
    finished = Location.search([("name", "=", "Tayyor mahsulot ombori"), ("usage", "=", "internal")], limit=1)
    if not finished:
        warehouse = env["stock.warehouse"].search([("company_id", "=", env.company.id)], limit=1)
        finished = warehouse.lot_stock_id
    finished.write({"craf_sale_point": True, "craf_sale_label": "Zavod", "craf_sale_sequence": 10})
    points = {"Zavod": finished}
    parent = finished.location_id
    for seq, name in ((20, "Parnik"), (30, "Rohat")):
        loc = Location.with_context(active_test=False).search(
            [("name", "=", name), ("location_id", "=", parent.id)], limit=1)
        vals = {"craf_sale_point": True, "craf_sale_label": name, "craf_sale_sequence": seq, "active": True}
        if loc:
            loc.write(vals)
        else:
            vals.update({"name": name, "location_id": parent.id, "usage": "internal",
                         "company_id": finished.company_id.id or env.company.id})
            if "craf_map_show" in Location._fields:
                vals["craf_map_show"] = False
            loc = Location.create(vals)
        points[name] = loc
    for company in env["res.company"].search([]):
        if not company.craf_sale_location_id:
            company.craf_sale_location_id = finished
    return points


def post_init_hook(env):
    points = _sale_points(env)
    Alias = env["craf.sotuv.alias"].with_context(active_test=False)
    existing = {(a.kind, a.key) for a in Alias.search([])}

    def add(vals):
        key = compact(vals["name"])
        if (vals["kind"], key) in existing:
            return
        existing.add((vals["kind"], key))
        Alias.create(vals)

    for name, stype, series, flt in ITEMS:
        add({"kind": "item", "name": name, "section_type": stype, "series": series or False,
             "filter_words": flt or False})
    for name, series, color_xmlid, family, flt in GROUPS:
        color = env.ref(color_xmlid, raise_if_not_found=False) if color_xmlid else False
        if color_xmlid and not color:
            continue
        add({"kind": "group", "name": name, "series": series or False, "color_id": color.id if color else False,
             "family_type": family or False, "filter_words": flt or False})
    for name, point in LOCATIONS:
        add({"kind": "location", "name": name, "location_id": points[point or "Zavod"].id})
