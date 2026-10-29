"""Liteyka sozlamalari: smenalar, qirindi/otxod me'yorlari, угар chegaralari, sukut joylar va namuna retsept.

Bitta kompaniyaga bitta sozlama yozuvi (craf.litey.settings.get()). Yangi plavka shu qiymatlar bilan ochiladi,
ishchi kerak bo'lsa plavkaning o'zida o'zgartiradi.
"""
from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import UserError


class CrafLiteyShift(models.Model):
    _name = "craf.litey.shift"
    _description = "Liteyka smenasi"
    _order = "sequence, id"

    name = fields.Char("Smena nomi", required=True, translate=False,
                       help="Masalan: Kunduzgi, Tungi yoki brigadir nomi bilan «Botir smenasi»")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    time_from = fields.Float("Boshlanishi", help="Soat: 8.0 = 08:00. Yangi plavkada shu vaqt oralig'idagi smena "
                                                 "avtomatik tanlanadi.")
    time_to = fields.Float("Tugashi", help="Tungi smena uchun tugash boshlanishdan kichik bo'lishi mumkin (20 → 8).")
    employee_id = fields.Many2one("hr.employee", string="Mas'ul (sukut)",
                                  help="Shu smena tanlansa plavkaning mas'uli shu bo'ladi")
    note = fields.Char("Izoh")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    settings_id = fields.Many2one("craf.litey.settings", ondelete="cascade",
                                  default=lambda self: self.env["craf.litey.settings"].get())

    def _contains(self, hour):
        self.ensure_one()
        a, b = self.time_from, self.time_to
        if a == b:
            return False
        return a <= hour < b if a < b else (hour >= a or hour < b)

    @api.model
    def _craf_current(self):
        """Hozirgi vaqtga mos smena (topilmasa — birinchisi)."""
        shifts = self.search([("company_id", "in", [self.env.company.id, False])])
        tz = self.env.context.get("tz") or self.env.user.tz or "Asia/Tashkent"
        now = fields.Datetime.context_timestamp(self.with_context(tz=tz), fields.Datetime.now())
        hour = now.hour + now.minute / 60.0
        for shift in shifts:
            if shift._contains(hour):
                return shift
        return shifts[:1]


class CrafLiteyRecipeLine(models.Model):
    _name = "craf.litey.recipe.line"
    _description = "Liteyka namuna retsepti qatori"
    _order = "sequence, id"

    settings_id = fields.Many2one("craf.litey.settings", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        "product.product", string="Material", required=True,
        domain=[("is_storable", "=", True), ("craf_section_id", "=", False)])
    uom_name = fields.Char(related="product_id.uom_id.name", string="Birlik")
    is_metal = fields.Boolean("Metall", compute="_compute_is_metal")
    qty = fields.Float("Miqdor (asos uchun)", digits=(16, 2),
                       help="Retsept asosi (masalan 1000 kg stalba) uchun kerak bo'lgan miqdor")
    share_pct = fields.Float("Ulush, %", compute="_compute_share", digits=(16, 1))

    @api.depends("product_id")
    def _compute_is_metal(self):
        for line in self:
            line.is_metal = not line.product_id.craf_not_metal

    @api.depends("qty", "settings_id.recipe_line_ids.qty")
    def _compute_share(self):
        for line in self:
            metal = sum(l.qty for l in line.settings_id.recipe_line_ids if not l.product_id.craf_not_metal)
            line.share_pct = line.qty / metal * 100.0 if metal and line.is_metal else 0.0


class CrafLiteySettings(models.Model):
    _name = "craf.litey.settings"
    _description = "Liteyka sozlamalari"
    _rec_name = "company_id"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company,
                                 ondelete="cascade")

    # --- stalba va chiqindi me'yorlari
    chip_per_billet = fields.Float(
        "Qirindi, 1 stalba uchun (kg)", digits=(16, 2),
        help="Stalbaning boshi va oxirini kesishda chiqadigan qirindi. Plavkada «Stalba soni» yozilganda "
             "qirindi = soni × shu qiymat bo'lib avtomatik qo'yiladi (keyin o'zgartirish mumkin).")
    cut_waste_per_billet = fields.Float(
        "Сталба отход, 1 stalba uchun (kg)", digits=(16, 2),
        help="Kesib tashlangan bosh va oxir bo'laklari. Plavkada soni × shu qiymat avtomatik qo'yiladi.")
    billet_length = fields.Float("Stalba uzunligi, m (sukut)", digits=(16, 2))
    billet_auto_fill = fields.Boolean(
        "Stalba soni bo'yicha otxod va qirindini avtomatik to'ldirish", default=True)
    chip_product_id = fields.Many2one(
        "product.product", string="Qirindi mahsuloti",
        default=lambda self: self.env["product.product"].search([("default_code", "=", "PF-20")], limit=1))
    chip_to_reuse = fields.Boolean(
        "Qirindi Liteykaga qaytadi (qayta eritiladi)", default=True,
        help="O'chirilsa qirindi «Chiqindi» joyiga tushadi.")

    # --- pech
    equipment_id = fields.Many2one("maintenance.equipment", string="Asosiy pech",
                                   domain=[("craf_stage", "=", "foundry")])
    temperature = fields.Integer("Harorat, °C (sukut)", default=740)
    billet_location_id = fields.Many2one("stock.location", string="Stalba qayerga",
                                         domain=[("usage", "=", "internal")])
    reuse_location_id = fields.Many2one("stock.location", string="Qayta eritiladigan otxod qayerga",
                                        domain=[("usage", "=", "internal")])

    # --- угар
    ugar_ok = fields.Float("Угар me'yori, % (yashil)", default=3.0, digits=(16, 2))
    ugar_max = fields.Float("Угар chegarasi, % (bundan yuqori — izoh shart)", default=5.0, digits=(16, 2))
    require_note_warn = fields.Boolean("Sariq holatda ham izoh talab qilinsin")

    # --- namuna retsept
    recipe_base_qty = fields.Float("Retsept asosi, kg stalba", default=1000.0, digits=(16, 1))
    plan_qty = fields.Float("Reja: stalba, kg (sukut)", default=2000.0, digits=(16, 1),
                            help="«Namuna retseptdan» bosilganda retsept shu miqdorga ko'paytiriladi")
    shift_ids = fields.One2many("craf.litey.shift", "settings_id", string="Smenalar",
                                context={"active_test": False})
    recipe_line_ids = fields.One2many("craf.litey.recipe.line", "settings_id", string="Namuna retsept")
    recipe_fill_mode = fields.Selection(
        [("plan", "Faqat reja ustuniga (haqiqiyni ishchi yozadi)"),
         ("both", "Reja va haqiqiy ustunlarga")],
        string="Retsept qayerga yoziladi", default="plan", required=True)
    recipe_metal_total = fields.Float("Metall jami", compute="_compute_recipe_totals", digits=(16, 1))
    recipe_total = fields.Float("Jami", compute="_compute_recipe_totals", digits=(16, 1))

    _company_uniq = models.Constraint("unique(company_id)", "Har bir kompaniyada bitta Liteyka sozlamasi bo'ladi.")

    @api.depends("recipe_line_ids.qty", "recipe_line_ids.product_id")
    def _compute_recipe_totals(self):
        for rec in self:
            rec.recipe_total = sum(rec.recipe_line_ids.mapped("qty"))
            rec.recipe_metal_total = sum(l.qty for l in rec.recipe_line_ids if not l.product_id.craf_not_metal)

    @api.constrains("ugar_ok", "ugar_max")
    def _check_ugar(self):
        for rec in self:
            if rec.ugar_ok < 0 or rec.ugar_max < rec.ugar_ok:
                raise UserError("Угар chegarasi me'yordan katta yoki teng bo'lishi kerak.")

    @api.model
    def get(self):
        rec = self.sudo().search([("company_id", "=", self.env.company.id)], limit=1)
        if not rec:
            rec = self.sudo().create({"company_id": self.env.company.id})
            rec._fill_defaults()
        return rec

    def _fill_defaults(self):
        """Birinchi ochilishda: retsept — mavjud «Shixta (namuna)» BoM dan, joylar — mixin sukutlaridan."""
        Melt = self.env["craf.foundry.melt"]
        for rec in self:
            vals = {}
            if not rec.billet_location_id:
                vals["billet_location_id"] = Melt._craf_loc("Press sexi").id
            if not rec.reuse_location_id:
                vals["reuse_location_id"] = Melt._craf_loc("Литейка").id
            if not rec.equipment_id:
                vals["equipment_id"] = Melt._craf_default_equipment().id
            if not rec.recipe_line_ids:
                bom = Melt._default_bom()
                if bom:
                    factor = rec.recipe_base_qty / (bom.product_qty or 1.0)
                    vals["recipe_line_ids"] = [Command.create({
                        "sequence": i, "product_id": l.product_id.id, "qty": round(l.product_qty * factor, 2),
                    }) for i, l in enumerate(bom.bom_line_ids, 1)]
            if vals:
                rec.write({k: v for k, v in vals.items() if v})

    # ---------------------------------------------------------------- tugmalar
    def action_recipe_from_history(self):
        """Oxirgi 30 kundagi tasdiqlangan plavkalar o'rtachasi bo'yicha retsept (asosga keltiriladi)."""
        self.ensure_one()
        since = fields.Date.context_today(self) - timedelta(days=30)
        melts = self.env["craf.foundry.melt"].search([("state", "=", "done"), ("date", ">=", since)])
        billet = sum(melts.mapped("billet_qty"))
        if not melts or billet <= 0:
            raise UserError("Oxirgi 30 kunda tasdiqlangan plavka yo'q.")
        qty = {}
        for line in melts.line_ids:
            qty[line.product_id] = qty.get(line.product_id, 0.0) + line.qty
        factor = self.recipe_base_qty / billet
        rows = sorted(((p, q) for p, q in qty.items() if q > 0), key=lambda pq: (pq[0].craf_melt_seq or 999))
        self.recipe_line_ids = [Command.clear()] + [Command.create({
            "sequence": i, "product_id": p.id, "qty": round(q * factor, 2)}) for i, (p, q) in enumerate(rows, 1)]
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "success", "message": "%s ta plavka (%s kg stalba) bo'yicha retsept tuzildi." % (
                len(melts), round(billet)), "next": {"type": "ir.actions.client", "tag": "soft_reload"}}}

    def action_recipe_to_bom(self):
        """Retseptni Odoo «Shixta (namuna)» BoM iga yozish (MRP rejalashtirish ham shu nisbatni ishlatsin)."""
        self.ensure_one()
        Melt = self.env["craf.foundry.melt"]
        bom = Melt._default_bom()
        billet = Melt._craf_product("XA-09")
        if not billet:
            raise UserError("Stalba mahsuloti (XA-09) topilmadi.")
        lines = [Command.create({"product_id": l.product_id.id, "product_qty": l.qty})
                 for l in self.recipe_line_ids if l.qty > 0]
        if bom:
            bom.write({"product_qty": self.recipe_base_qty, "bom_line_ids": [Command.clear()] + lines})
        else:
            self.env["mrp.bom"].create({
                "product_tmpl_id": billet.product_tmpl_id.id, "product_qty": self.recipe_base_qty,
                "code": "Shixta (namuna)", "bom_line_ids": lines})
        return {"type": "ir.actions.client", "tag": "display_notification", "params": {
            "type": "success", "message": "Retsept BoM ga yozildi."}}

    @api.model
    def action_open(self):
        rec = self.get()
        return {
            "type": "ir.actions.act_window", "name": "Liteyka sozlamalari", "res_model": self._name,
            "res_id": rec.id, "view_mode": "form", "target": "current",
            "context": {"form_view_initial_mode": "edit"},
        }
