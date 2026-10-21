"""Server tomondagi ruxsat: Craf sahifalari menyusi yashirilgan foydalanuvchi ularning ma'lumotini
to'g'ridan-to'g'ri so'rov (RPC) bilan ham ololmaydi.

Har bir sahifa modeli uchun: qaysi rollarga ochiq va qaysi ommaviy metodlari himoyalanadi.
Ichki chaqiruvlar (_ bilan boshlanuvchi metodlar) va sudo() tekshirilmaydi.
"""
from odoo import api, models
from odoo.exceptions import AccessError

OMBORCHI = "craf_sex.group_craf_accountant"   # Omborchi (avval «Hisobchi»); Direktor uni meros oladi
WORKER = "craf_sex.group_craf_worker"         # Sex ishchisi; Omborchi va Direktor ham
SELLER = "craf_sotuv.group_craf_seller"
ADMIN = "base.group_system"

PAGES = {
    "craf.dashboard": ("Zavod paneli", (OMBORCHI, ADMIN), ["get_data"]),
    "craf.zavod.xarita": ("Zavod xaritasi", (OMBORCHI, SELLER, ADMIN), ["get_map_data"]),
    "craf.kunlik.hisobot": ("Kunlik hisobot", (OMBORCHI, SELLER, ADMIN), [
        "get_data", "action_mark_c1", "get_sales_rows", "get_calc_products",
        "calc_set_unit", "calc_to_melt", "calc_to_paint"]),
    # Liteyka: ombor mudiri yozadi (sex ishchilari dasturdan foydalanmaydi); sotuvchi xom-ashyo qoldig'ini ko'radi
    "craf.litey.hisobot": ("Литейка", (OMBORCHI, SELLER, ADMIN), [
        "get_data", "get_forecast", "set_min_qty", "documents", "document_detail", "document_action", "form_options",
        "create_receipt", "create_transfer", "count_load", "count_save",
        "material_detail", "material_get", "material_hidden", "material_options",
        "material_remove", "material_restore", "material_save",
        "action_inventory", "action_open_moves"]),
    "craf.sex": ("Sexlar", (WORKER, ADMIN), [
        "get_data", "doc_detail", "doc_action", "basket_save", "basket_delete",
        "press_load", "press_options", "press_save", "chem_load", "chem_options", "chem_save",
        "paint_load", "paint_options", "paint_save"]),
}


class CrafLiteyEditor(models.AbstractModel):
    _inherit = "craf.litey.hisobot"

    @api.model
    def _is_editor(self):
        """Liteyka kirim-chiqimini faqat Omborchi (ombor mudiri) va Direktor yozadi."""
        user = self.env.user
        return user.has_group(OMBORCHI) or user.has_group(ADMIN)


def craf_check_page(env, model_name):
    if env.su:
        return
    title, groups, _methods = PAGES[model_name]
    user = env.user
    if not any(user.has_group(g) for g in groups):
        raise AccessError("«%s» sahifasiga ruxsatingiz yo'q. Rolingizni direktordan so'rang." % title)


def _make_guarded(model_name, method):
    def guarded(self, *args, **kwargs):
        craf_check_page(self.env, model_name)
        return getattr(super(_classes[model_name], self), method)(*args, **kwargs)
    guarded.__name__ = method
    return api.model(guarded)  # asl metodlarning hammasi @api.model


_classes = {}
for _model, (_title, _groups, _methods) in PAGES.items():
    _attrs = {"_inherit": _model, "__module__": __name__}
    _cls = type("CrafAccess_" + _model.replace(".", "_"), (models.AbstractModel,), _attrs)
    _classes[_model] = _cls
    for _m in _methods:
        setattr(_cls, _m, _make_guarded(_model, _m))
