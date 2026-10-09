STAGES = [
    # (maydon, nomi, ketma-ketlik kodi, qayerdan, qayerga, tartib)
    # standart "Ishlab chiqarish" turidan keyin turadi (u sukut bo'yicha qoladi)
    ("foundry_type_id", "Литейка", "LIT", "Литейка", "Press sexi", 30),
    ("press_type_id", "Press", "PRS", "Press sexi", "Bo'yash sexi", 40),
    ("press_pack_type_id", "Press → Qadoqlash", "PRQ", "Press sexi", "Qadoqlash", 41),
    ("paint_type_id", "Bo'yash", "BOY", "Bo'yash sexi", "Qadoqlash", 50),
]


def _loc(env, name, fallback):
    loc = env["stock.location"].search([("name", "=", name), ("usage", "=", "internal")], limit=1)
    return loc or fallback


def post_init_hook(env):
    # Ish buyurtmalari va qo'shimcha mahsulotlar (by-product) ko'rinishi
    user_group = env.ref("base.group_user")
    for xmlid in ("mrp.group_mrp_routings", "mrp.group_mrp_byproducts"):
        group = env.ref(xmlid, raise_if_not_found=False)
        if group:
            user_group._apply_group(group)

    norm = env["craf.mrp.norm"]._get_norm(env.company)
    warehouse = env["stock.warehouse"].search([("company_id", "=", env.company.id)], limit=1)
    PickingType = env["stock.picking.type"]
    vals = {}
    if warehouse:
        for field, name, code, src, dest, seq in STAGES:
            ptype = PickingType.search([("code", "=", "mrp_operation"), ("warehouse_id", "=", warehouse.id),
                                        ("sequence_code", "=", code)], limit=1)
            if not ptype:
                ptype = PickingType.create({
                    "name": name,
                    "code": "mrp_operation",
                    "sequence_code": code,
                    "sequence": seq,
                    "warehouse_id": warehouse.id,
                    "company_id": env.company.id,
                    "default_location_src_id": _loc(env, src, warehouse.lot_stock_id).id,
                    "default_location_dest_id": _loc(env, dest, warehouse.lot_stock_id).id,
                })
            vals[field] = ptype.id
    vals.update({
        "wc_foundry_id": env.ref("craf_mrp.wc_foundry").id,
        "wc_press_id": env.ref("craf_mrp.wc_press_1").id,
        "wc_press_alt_id": env.ref("craf_mrp.wc_press_2").id,
        "wc_paint_id": env.ref("craf_mrp.wc_paint").id,
        "wc_pack_id": env.ref("craf_mrp.wc_pack").id,
    })
    norm.write(vals)
    norm.action_generate_boms()
    _assign_existing(env, norm)


def _assign_existing(env, norm):
    """Avval tasdiqlangan Plavka / Press / Bo'yash buyurtmalarini o'z bosqich turiga o'tkazadi."""
    pack = env["stock.location"].search([("name", "=", "Qadoqlash"), ("usage", "=", "internal")], limit=1)
    for model, field in (("craf.foundry.melt", "foundry_type_id"), ("craf.extrusion.shift", "press_type_id"),
                         ("craf.paint.batch", "paint_type_id")):
        if model not in env:
            continue
        for doc in env[model].search([("production_ids", "!=", False)]):
            for mo in doc.production_ids:
                ptype = norm[field]
                if model == "craf.extrusion.shift" and pack and mo.location_dest_id == pack:
                    ptype = norm.press_pack_type_id
                if ptype and mo.picking_type_id != ptype:
                    env.cr.execute("UPDATE mrp_production SET picking_type_id = %s WHERE id = %s", (ptype.id, mo.id))
    env["mrp.production"].invalidate_model(["picking_type_id"])
