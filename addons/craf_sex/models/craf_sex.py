"""Sexlar sahifasi (Press, Kimyoviy ishlov, Bo'yash va qadoqlash) uchun server tomoni.

Mavjud hujjatlar ishlatiladi (yangi model yo'q):
- Press smenasi  — craf.extrusion.shift (+ korzinka yuklari craf.basket.load)
- Kimyoviy ishlov — craf.chem.treatment
- Bo'yash smenasi — craf.paint.batch (+ omborga topshirish, pachka yorliqlari)
"""
from collections import defaultdict
from datetime import time

from odoo import Command, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, SHIFTS, fmt

STAGES = [
    # kalit, nomi, hujjat modeli, sex joyi
    ("press", "Press", "craf.extrusion.shift", "Press sexi"),
    ("kimyo", "Kimyo", "craf.chem.treatment", "Kimyoviy ishlov"),
    ("boyash", "Bo'yash", "craf.paint.batch", "Bo'yash sexi"),
]
STAGE = {s[0]: s for s in STAGES}
STATE_LABELS = {"draft": "Qoralama", "done": "Bajarildi", "cancel": "Bekor"}
EQUIPMENT_STAGE = {"press": "press", "kimyo": "chem", "boyash": "paint"}
CHEMS = [("XA-03", "chem_ac20"), ("XA-04", "chem_cr51"), ("XA-05", "chem_ac52")]


def _q(value, digits=1):
    value = value or 0.0
    if abs(value - round(value)) < 1e-9:
        return fmt(value, 0)
    return fmt(value, digits)


class CrafSex(models.AbstractModel):
    _name = "craf.sex"
    _description = "Craf sexlar sahifasi (Press, Kimyo, Bo'yash)"

    # ================================================================== yordamchi
    @property
    def _H(self):
        return self.env["craf.litey.hisobot"]

    def _stage(self, stage):
        if stage not in STAGE:
            raise UserError("Noma'lum sex: %s" % stage)
        return STAGE[stage]

    def _model(self, stage):
        return self.env[self._stage(stage)[2]]

    def _loc(self, name):
        return self.env["craf.production.mixin"]._craf_loc(name)

    def _num(self, text, label, allow_empty=True):
        if text in (None, False, ""):
            if allow_empty:
                return 0.0
            raise UserError("%s: miqdorni yozing." % label)
        if isinstance(text, (int, float)):
            return float(text)
        value = self._H._num(text, label)
        return value or 0.0

    def _int(self, value):
        try:
            return max(int(float(str(value or 0).replace(",", ".").replace(" ", ""))), 0)
        except ValueError as err:
            raise UserError("Dona sonini raqam bilan yozing: %s" % value) from err

    def _roles(self):
        user = self.env.user
        director = user.has_group("craf_sex.group_craf_director") or user.has_group("base.group_system")
        accountant = director or user.has_group("craf_sex.group_craf_accountant")
        return {
            "director": director,
            "accountant": accountant,
            "manager": user.has_group("stock.group_stock_manager"),
            "stage": user.craf_work_stage or False,
            # oddiy sex ishchisi (masalan, kimyo xodimi) faqat o'z sexini ko'radi; omborchi va direktor — hammasini
            "own": user.craf_work_stage if user.craf_work_stage in STAGE and not accountant else False,
        }

    @api.model
    def nav_counts(self):
        """Telefondagi pastki panel belgisi: kimyo — kutayotgan korzinkalar, bo'yash — sexdagi bo'yalmagan profillar."""
        own = self.env.user._craf_own_app()
        if own == "boyash":
            semis = [r for r in self._stock("boyash")["rows"] if r["kind"] == "semi" and r["qty"] > 0]
            return {"ish": len(semis)}
        if own == "press":  # ochiq (tasdiqlanmagan) smenalar
            return {"ish": self.env["craf.extrusion.shift"].search_count([("state", "=", "draft")])}
        return {"ish": self.env["craf.basket.load"].search_count(
            [("state", "=", "press"), ("shift_state", "=", "done")])}

    def _materials(self):
        """Bo'yash va qadoqlash materiallari (faqat ko'rish): kukun bo'yoqlar, salofan va lenta, stikerlar.
        Sarf bo'yash hujjatidan avtomatik (stiker — profil uzunligi va tomoni bo'yicha) yechiladi."""
        Batch = self.env["craf.paint.batch"]
        colors = self.env["craf.color"].search([("is_painted", "=", True), ("paint_tmpl_id", "!=", False)])
        Product = self.env["product.product"]
        paints = colors.paint_tmpl_id.product_variant_ids | Product.search(
            [("default_code", "in", ("XA-01", "XA-11", "XA-12"))])
        packs = Product.search([("default_code", "in", ("QM-01", "QM-02"))])
        rows = Batch._craf_material_forecast(paints | packs) if paints | packs else {}
        status_tone = {"neg": "bad", "out": "bad", "low": "bad", "soon": "warn", "ok": "ok", "idle": ""}
        status_label = {"neg": "Manfiy", "out": "Tugagan", "low": "Minimaldan kam", "soon": "Tez tugaydi",
                        "ok": "Yetarli", "idle": "Sarflanmayapti"}

        def row(product):
            r = rows.get(product.id)
            if not r:
                return None
            return {"id": product.id, "name": product.name, "code": product.default_code or "",
                    "qty": round(r["qty"], 2), "in_sex": round(r["in_sex"], 2), "uom": self._uom_label(product),
                    "days": Batch._craf_days_text(r["days_left"]) or "", "avg": round(r["avg"], 2),
                    "tone": status_tone.get(r["status"], ""), "status": status_label.get(r["status"], "")}

        groups = [
            {"key": "paint", "title": "Bo'yoqlar (kukun)", "icon": "fa-tint",
             "rows": [x for x in (row(p) for p in paints.sorted("name")) if x]},
            {"key": "pack", "title": "Salofan va lenta", "icon": "fa-archive",
             "rows": [x for x in (row(p) for p in packs.sorted("default_code")) if x]},
        ]
        if "craf.sticker" in self.env:
            stickers = []
            for st in self.env["craf.sticker"].search([("product_id", "!=", False)]):
                stickers.append({
                    "id": st.id, "name": st.name, "code": st.size_text or "",
                    "qty": round(st.qty_rolls, 1), "in_sex": round(st.in_sex_rolls, 1), "uom": "rulon",
                    "meters": round(st.qty_m), "days": st.days_text or "", "avg": round(st.avg_rolls, 2),
                    "tone": status_tone.get(st.status, ""), "status": status_label.get(st.status, ""),
                })
            groups.append({"key": "sticker", "title": "Stikerlar", "icon": "fa-tag", "rows": stickers,
                           "note": "Stiker sarfi bo'yalgan profil uzunligi va tomoni bo'yicha avtomatik hisoblanadi."})
        return groups

    def _own_employee(self):
        """Shaxsiy ilovali xodim (kimyo, bo'yash) — mas'ul o'zi (sahifada tanlanmaydi)."""
        user = self.env.user
        return (user.employee_id.id or False) if user._craf_own_app() else False

    def _employees(self):
        return [{"id": e.id, "name": e.name, "job": e.job_title or ""}
                for e in self.env["hr.employee"].sudo().search([], order="name")]

    def _equipment(self, stage):
        return [{"id": e.id, "name": e.name} for e in self.env["maintenance.equipment"].sudo().search(
            [("craf_stage", "=", EQUIPMENT_STAGE[stage])], order="name")]

    def _check_draft(self, rec):
        if not rec:
            raise UserError("Hujjat topilmadi (o'chirilgan bo'lishi mumkin).")
        if rec.state != "draft":
            raise UserError("%s qoralama emas — o'zgartirib bo'lmaydi." % rec.name)

    def _uom_label(self, product):
        return self._H._uom(product)

    def _pack_text(self, pcs, per_pack):
        return self.env["product.template"]._craf_packs_text(pcs, per_pack) if per_pack else "%s dona" % _q(pcs)

    # ================================================================== asosiy ma'lumot
    @api.model
    def get_data(self, stage=None, date_from=None, date_to=None):
        roles = self._roles()
        own = roles["own"]
        if own or stage not in STAGE:
            stage = own or (roles["stage"] if roles["stage"] in STAGE else "press")
        dfrom, dto = self._H._period(date_from, date_to)
        Model = self._model(stage)
        docs = Model.search([("date", ">=", dfrom), ("date", "<=", dto)], order="date desc, id desc")
        drafts = Model.search([("state", "=", "draft")], order="date desc, id desc")
        issue_kind = {"kimyo": "kislota", "boyash": "boyash"}.get(stage)
        issues = self.env["craf.chem.issue"].search(
            [("kind", "=", issue_kind), ("date", ">=", dfrom), ("date", "<=", dto), ("state", "=", "done")],
            order="date desc, id desc") if issue_kind else self.env["craf.chem.issue"]
        stages = []
        for key, label, model, _loc in STAGES:
            if own and key != own:
                continue
            stages.append({"key": key, "label": label,
                           "drafts": self.env[model].search_count([("state", "=", "draft")])})
        return {
            "stage": stage,
            "stage_label": STAGE[stage][1],
            "stages": stages,
            "date_from": fields.Date.to_string(dfrom),
            "date_to": fields.Date.to_string(dto),
            "today": fields.Date.to_string(fields.Date.context_today(self)),
            "roles": roles,
            "kpi": (self._kpi_kimyo(docs.filtered(lambda d: d.state == "done"), issues) if stage == "kimyo"
                    else getattr(self, "_kpi_%s" % stage)(docs.filtered(lambda d: d.state == "done"))),
            "issues": [self._issue_card(i) for i in issues],
            "materials": self._materials() if stage == "boyash" else [],
            "sticker_summary": self.env["craf.stiker.sozlama"].summary() if stage == "boyash" else {},
            "days": [self._day_card(x) for x in self.env["craf.paint.day"].search(
                [("date", ">=", dfrom), ("date", "<=", dto), ("state", "=", "done")], order="date desc, id desc")]
            if stage == "boyash" else [],
            "day_drafts": [self._day_card(x) for x in self.env["craf.paint.day"].search(
                [("state", "=", "draft")], order="date desc, id desc")] if stage == "boyash" else [],
            "docs": [self._card(stage, d) for d in docs],
            "drafts": [self._card(stage, d) for d in drafts],
            "baskets": self._baskets(),
            "stock": self._stock(stage),
            "unstocked": self._unstocked() if stage == "boyash" else [],
        }

    # ---------------------------------------------------------------- kartochka
    def _card(self, stage, rec):
        res = {
            "id": rec.id, "name": rec.name, "date": fields.Date.to_string(rec.date),
            "date_label": rec.date.strftime("%d.%m.%Y"), "state": rec.state,
            "state_label": STATE_LABELS.get(rec.state, rec.state), "c1": rec.c1_state,
            "who": rec.employee_id.sudo().name or "", "equipment": rec.equipment_id.sudo().name or "",
            # press: Kunduzgi / Tungi smena nomi (bo'lsa), qolganlarda — 1/2/3-smena
            "shift": (rec.smena_id.name if "smena_id" in rec._fields and rec.smena_id else
                      dict(SHIFTS).get(rec.shift, "")),
        }
        res.update(getattr(self, "_card_%s" % stage)(rec))
        return res

    def _card_press(self, rec):
        loads = rec.basket_load_ids
        return {
            "title": " · ".join(x for x in [rec.smena_id.name, rec.equipment_id.sudo().name, rec.section_id.name]
                                if x) or "Press smenasi",
            "sub": "%s dona · %s kg" % (_q(rec.output_pcs), _q(rec.output_kg)) if rec.state == "done" else
            "%s ta korzinka · %s dona" % (len(loads), _q(sum(loads.mapped("pcs_total")))),
            "metric": "chiqish %s%%" % fmt(rec.yield_pct, 1) if rec.state == "done" and rec.yield_pct else "",
            "loads": [self._load_info(l) for l in loads.sorted("id")] if rec.state == "draft" else [],
            "billet": rec.billet_qty, "section_id": rec.section_id.id, "section": rec.section_id.name or "",
        }

    def _card_kimyo(self, rec):
        return {
            "title": "%s ta korzinka" % rec.basket_count,
            "sub": "%s dona · %s kg · %s m²%s" % (
                _q(rec.pcs_total), _q(rec.kg_total), _q(rec.area_total),
                (" · yaroqsiz %s, kesildi %s" % (rec.brak_pcs, rec.cut_pcs)) if rec.brak_pcs or rec.cut_pcs else ""),
            "metric": "",
            "loads": [self._load_info(l) for l in rec.load_ids] if rec.state == "draft" else [],
            "edit": rec._craf_edit_info() if rec.state == "done" else False,
        }

    def _card_boyash(self, rec):
        return {
            "title": rec.color_id.name or "Bo'yash smenasi",
            "sub": "kirdi %s · bo'yaldi %s · brak %s dona" % (_q(rec.pcs_in), _q(rec.pcs_ok), _q(rec.pcs_defect)),
            "metric": "brak %s%%" % fmt(rec.defect_pct, 1) if rec.pcs_in else "",
            "stocked": bool(rec.stock_picking_id),
            "loads": [self._load_info(l) for l in rec.load_ids] if rec.state == "draft" else [],
        }

    # ---------------------------------------------------------------- KPI
    def _kpi_press(self, done):
        billet = sum(done.mapped("billet_qty"))
        out = sum(done.mapped("output_kg"))
        hours = sum(done.mapped("duration"))
        return [
            {"label": "Smenalar", "value": _q(len(done)), "unit": ""},
            {"label": "Quyma sarfi", "value": _q(billet, 0), "unit": "kg"},
            {"label": "Profil chiqdi", "value": _q(out, 0), "unit": "kg",
             "sub": "%s dona" % _q(sum(done.mapped("output_pcs")))},
            {"label": "Chiqish", "value": fmt(out / billet * 100, 1) if billet else "—", "unit": "%" if billet else "",
             "tone": self._tone(out / billet * 100 if billet else None, 80, 75)},
            {"label": "Питак + brak", "value": _q(sum(done.mapped("rest_qty")) + sum(done.mapped("scrap_qty")), 0),
             "unit": "kg", "sub": "brak %s kg" % _q(sum(done.mapped("scrap_qty")), 0)},
            {"label": "Unumdorlik", "value": _q(out / hours, 0) if hours else "—", "unit": "kg/soat" if hours else ""},
        ]

    def _kpi_kimyo(self, done, issues=None):
        area = sum(done.mapped("area_total"))
        chem = sum((issues or self.env["craf.chem.issue"]).mapped("qty_total"))
        return [
            {"label": "Ishlov", "value": _q(len(done)), "unit": ""},
            {"label": "Korzinkalar", "value": _q(sum(done.mapped("basket_count"))), "unit": "ta"},
            {"label": "Profil", "value": _q(sum(done.mapped("kg_total")), 0), "unit": "kg",
             "sub": "%s dona" % _q(sum(done.mapped("pcs_total")))},
            {"label": "Yaroqsiz / kesildi", "value": "%s / %s" % (_q(sum(done.mapped("brak_pcs"))),
                                                                  _q(sum(done.mapped("cut_pcs")))), "unit": "dona"},
            {"label": "Maydon", "value": _q(area, 0), "unit": "m²"},
            {"label": "Kislota olindi", "value": fmt(chem, 1), "unit": "kg"},
        ]

    def _kpi_boyash(self, done):
        pcs_in = sum(done.mapped("pcs_in"))
        defect = sum(done.mapped("pcs_defect"))
        powder = sum(done.mapped("powder_qty"))
        powder_norm = sum(done.mapped("powder_norm_qty"))
        pct = defect / pcs_in * 100 if pcs_in else None
        return [
            {"label": "Smenalar", "value": _q(len(done)), "unit": ""},
            {"label": "Bo'yaldi", "value": _q(sum(done.mapped("pcs_ok"))), "unit": "dona",
             "sub": "%s kg" % _q(sum(done.mapped("kg_ok")), 0)},
            {"label": "Brak", "value": fmt(pct, 2) if pct is not None else "—", "unit": "%" if pct is not None else "",
             "sub": "%s dona" % _q(defect), "tone": self._tone(pct, 1.5, 2.0, lower_better=True)},
            {"label": "Kukun", "value": fmt(powder, 1), "unit": "kg",
             "sub": "me'yor %s kg" % fmt(powder_norm, 1) if powder_norm else "",
             "tone": self._tone_over(powder, powder_norm)},
            {"label": "Maydon", "value": _q(sum(done.mapped("area_total")), 0), "unit": "m²"},
        ]

    @staticmethod
    def _tone(value, good, bad, lower_better=False):
        if value is None:
            return ""
        if lower_better:
            return "ok" if value <= good else ("bad" if value > bad else "warn")
        return "ok" if value >= good else ("bad" if value < bad else "warn")

    @staticmethod
    def _tone_over(fact, norm):
        if not norm or not fact:
            return ""
        diff = (fact - norm) / norm * 100
        return "ok" if diff <= 5 else ("bad" if diff > 15 else "warn")

    # ---------------------------------------------------------------- korzinkalar
    def _load_info(self, load, exclude_sort=None):
        """exclude_sort — tasdiqlangan kimyoviy ishlovni tahrirlashda: shu hujjatning brak ajratishigacha bo'lgan
        dona (yaroqsiz / kesilgan qayta yoziladi)."""
        quantities = load._product_quantities()
        if exclude_sort and exclude_sort.state == "done":
            for line in exclude_sort.line_ids.filtered(lambda l: l.load_id == load):
                quantities[line.product_id] = quantities.get(line.product_id, 0) + line.qty
                if line.kind == "cut" and line.target_product_id:
                    quantities[line.target_product_id] = quantities.get(line.target_product_id, 0) - line.qty
        products = [{"id": p.id, "name": p.name, "qty": q, "length": p.craf_length_m}
                    for p, q in quantities.items() if q]
        extra = load.extra_line_ids[:1]
        return {
            "id": load.id, "basket_id": load.basket_id.id, "basket": load.basket_id.name,
            "content": load.content or "", "section": load.section_id.name or "",
            "section_id": load.section_id.id or False, "piece_kg": load.piece_kg, "hook": load.hook_kg,
            "stick": load.stick_kg, "tare": load.tare_kg,
            "extra_section_id": extra.section_id.id or False, "extra_qty_6": extra.qty_6 or "",
            "extra_qty_5": extra.qty_5 or "",
            "qty_6": load.qty_6, "qty_5": load.qty_5, "pcs": load.pcs_total,
            "gross": load.gross_kg, "net": load.net_kg, "theory": round(load.kg_theory, 1),
            "kg": round(load.net_kg or load.kg_theory, 1), "diff": round(load.kg_diff, 1),
            "area": round(load.area_m2, 1), "state": load.state, "shift": load.shift_id.name or "",
            "shift_id": load.shift_id.id, "shift_state": load.shift_id.state,
            "date_label": load.date.strftime("%d.%m") if load.date else "", "products": products,
        }

    def _baskets(self):
        Load = self.env["craf.basket.load"]
        filling = Load.search([("state", "=", "press"), ("shift_state", "=", "draft")], order="id")
        waiting = Load.search([("state", "=", "press"), ("shift_state", "=", "done")], order="date, id")
        ready = Load.search([("state", "=", "kimyo")], order="date, id")
        Basket = self.env["craf.basket"]
        return {
            "filling": [self._load_info(l) for l in filling],
            "waiting": [self._load_info(l) for l in waiting],
            "ready": [self._load_info(l) for l in ready],
            "empty": Basket.search_count([("state", "=", "empty")]),
            "total": Basket.search_count([]),
        }

    # ---------------------------------------------------------------- sex qoldig'i
    def _stock(self, stage):
        loc = self._loc(STAGE[stage][3])
        if not loc:
            return {"location": STAGE[stage][3], "rows": []}
        groups = self.env["stock.quant"]._read_group(
            [("location_id", "child_of", loc.id), ("quantity", "!=", 0)], ["product_id"], ["quantity:sum"])
        rows = []
        for product, qty in groups:
            if abs(qty) < 1e-6:
                continue
            tmpl = product.product_tmpl_id
            is_profile = bool(tmpl.craf_section_id)
            rows.append({
                "product_id": product.id, "code": product.default_code or "", "name": product.name,
                "qty": round(qty, 3), "uom": self._uom_label(product),
                "packs": self._pack_text(qty, tmpl.craf_pcs_per_pack) if is_profile and tmpl.craf_pcs_per_pack else "",
                "kg": round(qty * (tmpl.craf_kg_per_pc or 0.0), 1) if is_profile else 0.0,
                "kind": ("painted" if tmpl.craf_color_id.is_painted else "semi") if is_profile else "raw",
            })
        rows.sort(key=lambda r: ({"semi": 0, "painted": 1, "raw": 2}[r["kind"]], r["name"]))
        return {"location": loc.name, "location_id": loc.id, "rows": rows}

    def _unstocked(self):
        batches = self.env["craf.paint.batch"].search(
            [("state", "=", "done"), ("stock_picking_id", "=", False)], order="date, id")
        return [self._card("boyash", b) for b in batches]

    # ================================================================== PRESS
    def _semis_by_section(self):
        raw = self.env["product.template"]._craf_raw_color()
        res = defaultdict(list)
        if not raw:
            return res
        for p in self.env["product.product"].search([("craf_color_id", "=", raw.id), ("craf_section_id", "!=", False)],
                                                    order="craf_length_m desc, default_code"):
            res[p.craf_section_id.id].append({
                "id": p.id, "name": p.name, "code": p.default_code or "", "length": p.craf_length_m,
                "sale_ok": p.sale_ok, "per_pack": p.craf_pcs_per_pack, "kg_pc": round(p.craf_kg_per_pc, 4),
            })
        return res

    @api.model
    def press_options(self):
        press_loc = self._loc("Press sexi")
        semis = self._semis_by_section()
        sections = []
        for s in self.env["craf.profile.section"].search([], order="sequence, name"):
            items = semis.get(s.id, [])
            if not items:
                continue
            sections.append({
                "id": s.id, "name": s.name, "kg_m": s.kg_per_m, "perimeter": s.perimeter_m,
                "has5": any(abs(i["length"] - 5.0) < 1e-6 for i in items),
                "kg6": next((i["kg_pc"] for i in items if abs(i["length"] - 6.0) < 1e-6), round(s.kg_per_m * 6, 4)),
                "kg5": next((i["kg_pc"] for i in items if abs(i["length"] - 5.0) < 1e-6), round(s.kg_per_m * 5, 4)),
                "direct": [i for i in items if i["sale_ok"]],
            })
        billets = self.env["product.product"].search([("default_code", "in", ("XA-09", "XA-02"))], order="default_code desc")
        smenas = self.env["craf.press.smena"].search([])
        return {
            "today": fields.Date.to_string(fields.Date.context_today(self)),
            "presses": self._equipment("press"),
            "sections": sections,
            "employees": self._employees(),
            # Kunduzgi / Tungi smena bo'lsa — raqamli smena (1/2/3) tanlanmaydi
            "shifts": [] if smenas else [{"key": k, "label": v} for k, v in SHIFTS],
            "billets": [{"id": b.id, "name": b.name, "code": b.default_code,
                         "avail": round(b.with_context(location=press_loc.id).qty_available, 1) if press_loc else 0.0}
                        for b in billets],
            "baskets": [{"id": b.id, "name": b.name, "tare": b.tare_kg, "capacity": b.capacity}
                        for b in self.env["craf.basket"].search([("state", "=", "empty")], order="name")],
            # daftardagi smena (Kunduzgi / Tungi) — ish vaqti, press va mas'ul smenadan
            "smenas": [{"id": s.id, "name": s.name, "time": s.time_text or "", "duration": s.duration,
                        "equipment_id": s.equipment_id.id or False}
                       for s in smenas],
            "my_employee": self._own_employee(),
        }

    @api.model
    def press_load(self, shift_id):
        rec = self.env["craf.extrusion.shift"].browse(int(shift_id)).exists()
        if not rec:
            raise UserError("Press smenasi topilmadi.")
        direct = [{"product_id": l.product_id.id, "pcs": l.pcs} for l in rec.line_ids
                  if l.product_id.sale_ok and l.pcs]
        return {
            "id": rec.id, "name": rec.name, "state": rec.state, "date": fields.Date.to_string(rec.date),
            "equipment_id": rec.equipment_id.id or False, "section_id": rec.section_id.id or False,
            "shift": rec.shift, "employee_id": rec.employee_id.id or False, "smena_id": rec.smena_id.id or False,
            "billet_product_id": rec.billet_product_id.id or False,
            "billet_text": _q(rec.billet_qty, 1) if rec.billet_qty else "",
            "rest_text": _q(rec.rest_qty, 1) if rec.rest_qty else "",
            "scrap_text": _q(rec.scrap_qty, 1) if rec.scrap_qty else "",
            "duration": rec.duration, "note": rec.note or "", "direct": direct,
            "loads": [self._load_info(l) for l in rec.basket_load_ids.sorted("id")],
        }

    @api.model
    def press_save(self, vals, confirm=False):
        Shift = self.env["craf.extrusion.shift"]
        rec = Shift.browse(int(vals["id"])).exists() if vals.get("id") else Shift
        if vals.get("id"):
            self._check_draft(rec)
        # matritsa (asosiy profil) ixtiyoriy: har korzinka o'z profilini oladi, tasdiqda eng ko'p chiqqani olinadi
        section = self.env["craf.profile.section"].browse(int(vals.get("section_id") or 0)).exists()
        smena = self.env["craf.press.smena"].browse(int(vals.get("smena_id") or 0)).exists()
        header = {
            "date": vals.get("date") or fields.Date.context_today(self),
            "equipment_id": int(vals["equipment_id"]) if vals.get("equipment_id") else (smena.equipment_id.id or False),
            "section_id": section.id or False,
            "smena_id": smena.id or False,
            "shift": vals.get("shift") or "1",
            "employee_id": int(vals["employee_id"]) if vals.get("employee_id") else self._own_employee(),
            "billet_qty": self._num(vals.get("billet_text"), "Quyma sarfi"),
            "rest_qty": self._num(vals.get("rest_text"), "Press qoldig'i (питак)"),
            "scrap_qty": self._num(vals.get("scrap_text"), "Brak"),
            "duration": float(vals.get("duration") or 0.0),
            "note": (vals.get("note") or "").strip() or False,
        }
        if vals.get("billet_product_id"):
            header["billet_product_id"] = int(vals["billet_product_id"])
        self._H._moment(header["date"])  # kelajak sanasini to'xtatadi
        direct = {}
        for row in vals.get("direct") or []:
            pcs = self._int(row.get("pcs"))
            if row.get("product_id") and pcs:
                direct[int(row["product_id"])] = direct.get(int(row["product_id"]), 0) + pcs
        if not rec:
            rec = Shift.create(header)
        else:
            rec.write(header)
        # korzinkasiz chiqish (sotiladigan bo'yalmagan profil) — qolgan qatorlar tasdiqlashda korzinkalardan yig'iladi
        commands = [Command.unlink(l.id) for l in rec.line_ids]
        commands += [Command.create({"product_id": pid, "pcs": pcs}) for pid, pcs in direct.items()]
        rec.write({"line_ids": commands})
        if confirm:
            self._confirm(rec)
        return {"id": rec.id, "name": rec.name, "state": rec.state}

    @api.model
    def basket_save(self, vals):
        shift = self.env["craf.extrusion.shift"].browse(int(vals.get("shift_id") or 0)).exists()
        self._check_draft(shift)
        Load = self.env["craf.basket.load"]
        load = Load.browse(int(vals["load_id"])).exists() if vals.get("load_id") else Load
        if vals.get("load_id") and (not load or load.shift_id != shift):
            raise UserError("Korzinka yuki topilmadi.")
        qty_6, qty_5 = self._int(vals.get("qty_6")), self._int(vals.get("qty_5"))
        if not qty_6 and not qty_5:
            raise UserError("Korzinkadagi dona sonini yozing (6 m yoki 5 m).")
        Section = self.env["craf.profile.section"]
        # daftardagidek: har korzinka — o'z profili (tanlanmasa, smena matritsasi)
        section = Section.browse(int(vals.get("section_id") or 0)).exists() or load.section_id or shift.section_id
        if not section:
            raise UserError("Profilni tanlang.")
        data = {
            "basket_id": int(vals.get("basket_id") or 0) or load.basket_id.id,
            "section_id": section.id,
            "qty_6": qty_6, "qty_5": qty_5,
            "gross_kg": self._num(vals.get("gross_text"), "Brutto"),
        }
        for key, field, label in (("piece_text", "piece_kg", "KG 1 dona"), ("hook_text", "hook_kg", "Kryuchok"),
                                  ("stick_text", "stick_kg", "Palka"), ("tare_text", "tare_kg", "Korzinka og'irligi")):
            if vals.get(key) not in (None, ""):
                data[field] = self._num(vals.get(key), label)
        if not data["basket_id"]:
            raise UserError("Korzinkani tanlang.")
        # «Профил номи +» — shu korzinkadagi ikkinchi profil
        extra_section = Section.browse(int(vals.get("extra_section_id") or 0)).exists()
        e6, e5 = self._int(vals.get("extra_qty_6")), self._int(vals.get("extra_qty_5"))
        extra = [Command.clear()]
        if extra_section and (e6 or e5):
            extra.append(Command.create({"section_id": extra_section.id, "qty_6": e6, "qty_5": e5}))
        elif extra_section:
            raise UserError("Ikkinchi profil (%s) donasini yozing yoki uni olib tashlang." % extra_section.name)
        data["extra_line_ids"] = extra
        if load:
            load.write(data)
        else:
            load = Load.create(dict(data, shift_id=shift.id))
        return self._load_info(load)

    @api.model
    def basket_delete(self, load_id):
        load = self.env["craf.basket.load"].browse(int(load_id)).exists()
        if not load:
            return True
        if load.shift_id.state != "draft" or load.state != "press":
            raise UserError("Bu korzinka smenasi tasdiqlangan — o'chirib bo'lmaydi.")
        load.unlink()
        return True

    # ================================================================== KIMYO
    def _chem_norms(self):
        norm = self.env["craf.mrp.norm"]._get_norm(self.env.company)
        loc = self._loc("Kimyoviy ishlov")
        res = []
        for code, fname in CHEMS:
            product = self.env["craf.production.mixin"]._craf_product(code)
            if product:
                res.append({"id": product.id, "name": product.name, "code": code, "per_m2": norm[fname],
                            "avail": round(product.with_context(location=loc.id).qty_available, 2) if loc else 0.0})
        return res

    @api.model
    def chem_options(self):
        return {
            "today": fields.Date.to_string(fields.Date.context_today(self)),
            "chems": self._chem_norms(),
            "employees": self._employees(),
            "my_employee": self.env.user.employee_id.id or False,
            "equipment": self._equipment("kimyo"),
            "shifts": [{"key": k, "label": v} for k, v in SHIFTS],
        }

    @api.model
    def chem_load(self, rec_id):
        rec = self.env["craf.chem.treatment"].browse(int(rec_id)).exists()
        if not rec:
            raise UserError("Kimyoviy ishlov hujjati topilmadi.")
        return {
            "id": rec.id, "name": rec.name, "state": rec.state, "date": fields.Date.to_string(rec.date),
            "shift": rec.shift, "employee_id": rec.employee_id.id or False, "equipment_id": rec.equipment_id.id or False,
            "load_ids": rec.load_ids.ids,
            "loads": [self._load_info(l, exclude_sort=rec.sort_id) for l in rec.load_ids],
            "chem": {str(l.product_id.id): _q(l.qty, 2) for l in rec.chem_line_ids},
            "defects": self._chem_defects_map(rec),
            "note": rec.note or "",
            "edit": rec._craf_edit_info() if rec.state == "done" else False,
            "history": rec._craf_edit_history(),
        }

    def _chem_defects_map(self, rec):
        """{"<yuk>_<profil>": {"brak": dona, "cut": dona}} — sahifadagi kiritish maydonlari uchun."""
        res = {}
        for line in rec.defect_line_ids:
            row = res.setdefault("%s_%s" % (line.load_id.id, line.product_id.id), {"brak": "", "cut": ""})
            row[line.kind] = (row[line.kind] or 0) + line.qty
        return res

    def _chem_defect_commands(self, loads, rows):
        """Sahifadan: [{load_id, product_id, brak, cut}] → yaroqsiz / 6 → 5 m qatorlari (korzinkadagi dona bilan tekshiriladi)."""
        commands = [Command.clear()]
        for row in rows or []:
            load = loads.filtered(lambda l, i=int(row.get("load_id") or 0): l.id == i)
            if not load:
                continue
            product = self.env["product.product"].browse(int(row.get("product_id") or 0)).exists()
            have = load._product_quantities().get(product, 0)
            brak, cut = self._int(row.get("brak")), self._int(row.get("cut"))
            if not product or not (brak or cut):
                continue
            if brak + cut > have:
                raise UserError("%s: %s — korzinkada %s dona, yozildi %s." % (
                    load.basket_id.name, product.name, have, brak + cut))
            if cut and abs(product.craf_length_m - 6.0) > EPS:
                raise UserError("«6 m → 5 m» faqat 6 metrlik profil uchun (%s)." % product.name)
            for kind, qty in (("brak", brak), ("cut", cut)):
                if qty:
                    commands.append(Command.create({"load_id": load.id, "product_id": product.id,
                                                    "kind": kind, "qty": qty}))
        return commands

    @api.model
    def chem_save(self, vals, confirm=False):
        Chem = self.env["craf.chem.treatment"]
        rec = Chem.browse(int(vals["id"])).exists() if vals.get("id") else Chem
        editing = bool(rec) and rec.state == "done"
        if editing:
            # tasdiqlangan: 24 soat ichida (xodim) yoki rahbar — eski tasdiq bekor qilinib, qayta tasdiqlanadi
            rec._craf_check_edit()
            before = rec._craf_edit_snapshot()
            since = self._last_move_id()
            self._H._check_lock(self._touched_products(rec), self._H._moment(rec.date), rec.name)
            rec._craf_unconfirm()
            confirm = True
        elif vals.get("id"):
            self._check_draft(rec)
        load_ids = [int(i) for i in vals.get("load_ids") or []]
        Load = self.env["craf.basket.load"]
        loads = Load.browse(load_ids).exists()
        bad = loads.filtered(lambda l: not (l.state == "press" and l.shift_state == "done") and l not in rec.load_ids)
        if bad:
            raise UserError("Bu korzinkalar kimyoga kutmayapti: %s" % ", ".join(bad.mapped("basket_id.name")))
        if not loads:
            raise UserError("Ishlov berilgan korzinkalarni belgilang.")
        header = {
            "date": vals.get("date") or fields.Date.context_today(self),
            "shift": vals.get("shift") or "1",
            "employee_id": int(vals["employee_id"]) if vals.get("employee_id") else self._own_employee(),
            "equipment_id": int(vals["equipment_id"]) if vals.get("equipment_id") else False,
            "note": (vals.get("note") or "").strip() or False,
            "load_ids": [Command.set(loads.ids)],
        }
        self._H._moment(header["date"])
        if not rec:
            rec = Chem.create(header)
        else:
            rec.write(header)
        # kimyo sarfi bu yerda yozilmaydi — «Kislota» bo'limida (craf.chem.issue); eski hujjatlarda yechilgani qoladi
        rec.write({"chem_line_ids": [Command.unlink(l.id) for l in rec.chem_line_ids if not l.move_id],
                   "defect_line_ids": self._chem_defect_commands(rec.load_ids, vals.get("defects"))})
        if confirm:
            self._confirm(rec)
        if editing:
            self._edit_guard(since)
            rec._craf_log_edit(before)
        return {"id": rec.id, "name": rec.name, "state": rec.state, "edited": editing}

    @api.model
    def chem_cancel(self, rec_id):
        """Tasdiqlangan kimyoviy ishlovni o'chirish (24 soat ichida yoki rahbar)."""
        return self._chem_cancel(self.env["craf.chem.treatment"].browse(int(rec_id)).exists())

    def _chem_cancel(self, rec):
        if not rec:
            raise UserError("Hujjat topilmadi (o'chirilgan bo'lishi mumkin).")
        if rec.state != "done":
            raise UserError("%s tasdiqlanmagan — qoralamani «O'chirish» bilan o'chiring." % rec.name)
        rec._craf_check_edit()
        before = rec._craf_edit_snapshot()
        since = self._last_move_id()
        self._H._check_lock(self._touched_products(rec), self._H._moment(rec.date), rec.name)
        rec._craf_cancel_done()
        self._edit_guard(since)
        rec._craf_log_edit(before, kind="cancel")
        return {"result": "void", "name": rec.name, "state": rec.state}

    # ================================================================== KISLOTA
    def _issue_card(self, rec):
        return {
            "id": rec.id, "name": rec.name, "date_label": rec.date.strftime("%d.%m.%Y"),
            "who": rec.employee_id.sudo().name or "", "total": _q(rec.qty_total, 2),
            "lines": [{"name": l.product_id.name, "qty": _q(l.qty, 2), "uom": self._uom_label(l.product_id)}
                      for l in rec.line_ids if l.qty > EPS],
            "note": rec.note or "",
            "edit": rec._craf_edit_info(),
        }

    @api.model
    def issue_options(self):
        """Kislota olish sahifasi: kislotalar va ombordagi qoldig'i."""
        Issue = self.env["craf.chem.issue"]
        loc = Issue._craf_loc(Issue._craf_default_src)
        return {
            "today": fields.Date.to_string(fields.Date.context_today(self)),
            "location": loc.name or "",
            "chems": [{"id": p.id, "name": p.name, "code": p.default_code or "", "uom": self._uom_label(p),
                       "avail": round(p.with_context(location=loc.id).qty_available, 2) if loc else 0.0}
                      for p in Issue._craf_chem_products()],
            "employees": self._employees(),
            "my_employee": self.env.user.employee_id.id or False,
        }

    @api.model
    def mat_issue_options(self):
        """Bo'yash materiallari sarfi: bo'yoqlar, salofan va lenta — zavoddagi qoldig'i bilan."""
        Issue = self.env["craf.chem.issue"]
        rows = []
        for p in Issue._craf_chem_products("boyash"):
            group = "pack" if p.default_code in ("QM-01", "QM-02") else "paint"
            rows.append({"id": p.id, "name": p.name, "code": p.default_code or "", "uom": self._uom_label(p),
                         "avail": round(p.qty_available, 2), "group": group})
        return {
            "today": fields.Date.to_string(fields.Date.context_today(self)),
            "chems": rows,
            "employees": self._employees(),
            "my_employee": self.env.user.employee_id.id or False,
        }

    @api.model
    def mat_issue_save(self, vals):
        """Ombordan olingan bo'yash materiallari: yoziladi va shu zahoti sarfga yechiladi."""
        return self._issue_save("boyash", vals)

    @api.model
    def issue_save(self, vals):
        """Ombordan olingan kislota: yoziladi va shu zahoti ombordan sarfga yechiladi."""
        return self._issue_save("kislota", vals)

    @api.model
    def issue_load(self, issue_id):
        """Kislota yoki bo'yash materiali olishni tahrirlash uchun."""
        return self._issue_load(("kislota", "boyash"), issue_id)

    @api.model
    def issue_cancel(self, issue_id):
        """Kislota yoki bo'yash materiali olishni o'chirish (24 soat ichida yoki rahbar): miqdor omborga qaytadi."""
        return self._issue_cancel(("kislota", "boyash"), issue_id)

    def _issue_get(self, kinds, issue_id):
        rec = self.env["craf.chem.issue"].browse(int(issue_id or 0)).exists()
        if not rec or rec.kind not in kinds:
            raise UserError("Yozuv topilmadi (o'chirilgan bo'lishi mumkin).")
        return rec

    def _issue_load(self, kinds, issue_id):
        rec = self._issue_get(kinds, issue_id)
        return {
            "id": rec.id, "name": rec.name, "kind": rec.kind, "state": rec.state,
            "date": fields.Date.to_string(rec.date), "employee_id": rec.employee_id.id or False,
            "note": rec.note or "",
            "qty": {str(l.product_id.id): _q(l.qty, 2) for l in rec.line_ids if l.qty > EPS},
            "edit": rec._craf_edit_info() if rec.state == "done" else False,
            "history": rec._craf_edit_history(),
        }

    def _issue_edit(self, kind, vals, lines, date):
        """Tasdiqlangan olishni tahrirlash: eski yechim omborga qaytariladi, yangisi yechiladi (bitta tranzaksiya)."""
        rec = self._issue_get((kind,), vals["id"])
        if rec.state != "done":
            raise UserError("%s bekor qilingan — tahrirlab bo'lmaydi." % rec.name)
        rec._craf_check_edit()
        before = rec._craf_edit_snapshot()
        since = self._last_move_id()
        self._H._check_lock(rec.line_ids.product_id, self._H._moment(rec.date), rec.name)
        rec._craf_unpost()
        data = {"date": date, "note": (vals.get("note") or "").strip() or False,
                "line_ids": [Command.clear()] + lines}
        if not self.env.user._craf_own_app() and vals.get("employee_id"):
            data["employee_id"] = int(vals["employee_id"])
        rec.write(data)
        self._H._check_lock(rec.line_ids.product_id, self._H._moment(date), rec.name)
        rec.action_done()
        self._edit_guard(since)
        rec._craf_log_edit(before)
        return {"id": rec.id, "name": rec.name, "total": _q(rec.qty_total, 2), "edited": True}

    def _issue_cancel(self, kinds, issue_id):
        rec = self._issue_get(kinds, issue_id)
        if rec.state != "done":
            raise UserError("%s allaqachon bekor qilingan." % rec.name)
        rec._craf_check_edit()
        before = rec._craf_edit_snapshot()
        since = self._last_move_id()
        self._H._check_lock(rec.line_ids.product_id, self._H._moment(rec.date), rec.name)
        rec._craf_unpost()
        rec.state = "cancel"
        self._edit_guard(since)
        rec._craf_log_edit(before, kind="cancel")
        return {"result": "cancel", "name": rec.name}

    def _issue_save(self, kind, vals):
        Issue = self.env["craf.chem.issue"]
        lines = []
        for c in Issue._craf_chem_products(kind):
            qty = self._num((vals.get("qty") or {}).get(str(c.id)), c.name)
            if qty > EPS:
                lines.append(Command.create({"product_id": c.id, "qty": qty}))
        if not lines:
            raise UserError("Olingan miqdorni yozing.")
        date = vals.get("date") or fields.Date.context_today(self)
        if vals.get("id"):
            return self._issue_edit(kind, vals, lines, date)
        moment = self._H._moment(date)
        rec = Issue.create({
            "kind": kind,
            "date": date,
            "employee_id": int(vals["employee_id"]) if vals.get("employee_id") else self._own_employee(),
            "note": (vals.get("note") or "").strip() or False,
            "line_ids": lines,
        })
        self._H._check_lock(rec.line_ids.product_id, moment, rec.name)
        rec.action_done()
        return {"id": rec.id, "name": rec.name, "total": _q(rec.qty_total, 2)}

    # ================================================================== KUNLIK BO'YASH (daftardagidek)
    def _day_card(self, day):
        return {
            "id": day.id, "name": day.name, "state": day.state, "date_label": day.date.strftime("%d.%m.%Y"),
            "lines": [{"text": text, "color": color} for text, color in day._craf_lines_text()],
            "powders": [{"color": p.color_id.name, "qty": _q(p.qty, 2)} for p in day.powder_ids if p.qty > EPS],
            "packs": day.packs_total, "pcs": day.pcs_total, "kg": _q(day.kg_total, 0),
            "who": day.employee_id.sudo().name or "",
            "edit": day._craf_edit_info() if day.state == "done" else False,
        }

    @staticmethod
    def _len_key(length):
        return ("%g" % float(length or 0)).replace(".", ",")

    @api.model
    def day_options(self):
        """Kunlik bo'yash formasi: profillar (uzunliklari bilan), ranglar, stikerlar va mahsulot xaritasi —
        {kesim|uzunlik|rang|logo: tayyor mahsulot} (Alusam stikerli L → «L … ALUSAM», bo'lsa)."""
        Tmpl = self.env["product.template"]
        raw = Tmpl._craf_raw_color()
        loc = self._loc("Bo'yash sexi")
        logos = self.env["craf.sticker.logo"].search([])
        brand_series = {(l.name or "").strip().lower() for l in logos}
        colors = self.env["craf.color"].search([("is_painted", "=", True)], order="sequence, name")
        norm = self.env["craf.mrp.norm"]._get_norm(self.env.company)
        templates = Tmpl.search([("craf_section_id", "!=", False), ("craf_length_m", ">", 0)])
        index = {}
        for t in templates:
            index[(t.craf_section_id.id, round(t.craf_length_m, 1), t.craf_color_id.id)] = t
        # brend kesimlar: (profil turi, seriya) → kesim (L + ALUSAM → «L ALUSAM»)
        brands = {}
        for sec in templates.craf_section_id:
            series = (sec.series or "").strip().lower()
            if series in brand_series and sec.profile_type:
                brands[(sec.profile_type, series)] = sec
        stock = {}
        semis = templates.filtered(lambda t: t.craf_color_id == raw).product_variant_id
        if loc and semis:
            for product, qty in self.env["stock.quant"]._read_group(
                    [("location_id", "child_of", loc.id), ("product_id", "in", semis.ids)],
                    ["product_id"], ["quantity:sum"]):
                stock[product.id] = qty
        sections, products, semi_stock = [], {}, {}
        for sec in templates.filtered(lambda t: t.craf_color_id == raw).craf_section_id.sorted(lambda s: (s.sequence, s.name)):
            if (sec.series or "").strip().lower() in brand_series:
                continue  # brend kesim alohida tanlanmaydi — stiker orqali
            lengths = sorted({round(t.craf_length_m, 1) for t in templates
                              if t.craf_section_id == sec and t.craf_color_id == raw}, reverse=True)
            sections.append({"id": sec.id, "name": sec.display_name, "lengths": lengths,
                             "perimeter": sec.perimeter_m or 0.0})
            for length in lengths:
                semi = index.get((sec.id, length, raw.id))
                semi_stock["%s|%s" % (sec.id, self._len_key(length))] = round(stock.get(
                    semi.product_variant_id.id, 0.0)) if semi else 0
                for color in colors:
                    for logo in logos | self.env["craf.sticker.logo"]:
                        tmpl = None
                        if logo and not (sec.series or "").strip():
                            brand = brands.get((sec.profile_type, (logo.name or "").strip().lower()))
                            if brand:
                                tmpl = index.get((brand.id, length, color.id))
                        tmpl = tmpl or index.get((sec.id, length, color.id))
                        if tmpl:
                            products["%s|%s|%s|%s" % (sec.id, self._len_key(length), color.id, logo.id or 0)] = {
                                "id": tmpl.product_variant_id.id, "name": tmpl.name,
                                "per_pack": tmpl.craf_pcs_per_pack or (semi.craf_pcs_per_pack if semi else 0),
                                "kg_pc": round(semi.craf_kg_per_pc if semi else tmpl.craf_kg_per_pc, 4),
                            }
        default_logo = self.env["craf.paint.batch"]._craf_default_sticker_logo()
        return {
            "today": fields.Date.to_string(fields.Date.context_today(self)),
            "sections": sections,
            "colors": [{
                "id": c.id, "name": c.name, "label": c.name + (" · 1376" if (c.code or "").upper() == "J306" else ""),
                "g_m2": c.craf_powder_norm or 120.0,
                "powder": c.paint_tmpl_id.name or "",
                "avail": round(c.paint_tmpl_id.product_variant_id.qty_available, 1) if c.paint_tmpl_id else 0.0,
            } for c in colors],
            "logos": [{"id": l.id, "name": l.name} for l in logos],
            "default_logo": default_logo.id or False,
            "products": products,
            "semi_stock": semi_stock,
            "employees": self._employees(),
            "my_employee": self.env.user.employee_id.id or False,
            "recent": self._day_recent_sections(),
        }

    def _day_recent_sections(self):
        """Oxirgi kunlarda ko'p yozilgan profillar — formada tez tanlash uchun."""
        lines = self.env["craf.paint.day.line"].search([], order="id desc", limit=60)
        seen = []
        for line in lines:
            if line.section_id.id not in seen:
                seen.append(line.section_id.id)
        return seen[:6]

    @api.model
    def day_load(self, day_id):
        day = self.env["craf.paint.day"].browse(int(day_id)).exists()
        if not day:
            raise UserError("Kunlik yozuv topilmadi (o'chirilgan bo'lishi mumkin).")
        return {
            "id": day.id, "name": day.name, "state": day.state, "date": fields.Date.to_string(day.date),
            "employee_id": day.employee_id.id or False, "note": day.note or "",
            "lines": [{
                "section_id": l.section_id.id, "length": l.length_m, "color_id": l.color_id.id,
                "logo_id": l.logo_id.id or False, "packs_text": l.packs_text or (str(l.packs) if l.packs else ""),
                "extra": l.extra or "",
            } for l in day.line_ids],
            "powders": {str(p.color_id.id): _q(p.qty, 2) for p in day.powder_ids if p.qty > EPS},
            "edit": day._craf_edit_info() if day.state == "done" else False,
            "history": day._craf_edit_history(),
            # tahrirda: eski tasdiq bekor qilinganda sexga qaytadigan bo'yalmagan profil — {kesim|uzunlik: dona}
            "semi_back": self._day_semi_back(day) if day.state == "done" else {},
        }

    def _day_semi_back(self, day):
        res = {}
        for line in day.line_ids:
            k = "%s|%s" % (line.section_id.id, self._len_key(line.length_m))
            res[k] = res.get(k, 0) + line.pcs
        return res

    @api.model
    def day_save(self, vals, confirm=False):
        """Kunlik bo'yash: saqlash (qoralama) yoki tasdiqlash (bo'yash smenalari yaratiladi, omborga — darhol)."""
        from .craf_paint_day import parse_packs
        Day = self.env["craf.paint.day"]
        day = Day.browse(int(vals["id"])).exists() if vals.get("id") else Day
        editing = bool(day) and day.state == "done"
        if vals.get("id") and (not day or day.state not in ("draft", "done")):
            raise UserError("Bu kunlik yozuv bekor qilingan yoki o'chirilgan — o'zgartirib bo'lmaydi.")
        lines = []
        for row in vals.get("lines") or []:
            packs = parse_packs(row.get("packs_text"))
            extra = self._int(row.get("extra"))
            if not row.get("section_id") and not packs and not extra:
                continue  # bo'sh qator
            if not row.get("section_id"):
                raise UserError("Har qatorda profilni tanlang.")
            if not row.get("color_id"):
                raise UserError("Har qatorda rangni tanlang.")
            if not (packs or extra):
                raise UserError("Har qatorda pachka sonini yozing.")
            lines.append(Command.create({
                "section_id": int(row["section_id"]), "length_m": float(row.get("length") or 6),
                "color_id": int(row["color_id"]), "logo_id": int(row["logo_id"]) if row.get("logo_id") else False,
                "packs_text": (row.get("packs_text") or "").strip() or False, "packs": packs, "extra": extra,
            }))
        if not lines:
            raise UserError("Qadoqlangan profillarni yozing (profil, rang, pachka).")
        used_colors = {int(c.get("color_id")) for c in vals.get("lines") or [] if c.get("color_id")}
        powders = [Command.create({"color_id": int(cid), "qty": self._num(qty, "Bo'yoq sarfi")})
                   for cid, qty in (vals.get("powders") or {}).items()
                   if int(cid) in used_colors and str(qty or "").strip()]
        data = {
            "date": vals.get("date") or fields.Date.context_today(self),
            "employee_id": int(vals["employee_id"]) if vals.get("employee_id") else self._own_employee(),
            "note": (vals.get("note") or "").strip() or False,
            "line_ids": [Command.clear()] + lines,
            "powder_ids": [Command.clear()] + powders,
        }
        self._H._moment(data["date"])
        if editing:
            # tasdiqlangan: 24 soat ichida (xodim) yoki rahbar — eski tasdiq bekor qilinib, qayta tasdiqlanadi
            day._craf_check_edit()
            before = day._craf_edit_snapshot()
            since = self._last_move_id()
            self._day_check_lock(day)
            day._craf_unconfirm()
            confirm = True
        if day:
            day.write(data)
        else:
            day = Day.create(data)
        if confirm:
            day.action_confirm()
        if editing:
            self._edit_guard(since)
            day._craf_log_edit(before)
        return {"id": day.id, "name": day.name, "state": day.state, "edited": editing,
                "batches": ", ".join(day.batch_ids.mapped("name"))}

    def _day_check_lock(self, day):
        """Eski sanadagi harakatlar qaytariladi — shu sanadan keyin qoldiq sanalgan bo'lsa to'xtatadi."""
        moment = self._H._moment(day.date)
        for batch in day.batch_ids.filtered(lambda b: b.state == "done"):
            self._H._check_lock(self._touched_products(batch), moment, day.name)

    @api.model
    def day_action(self, day_id, action):
        day = self.env["craf.paint.day"].browse(int(day_id)).exists()
        if not day:
            raise UserError("Kunlik yozuv topilmadi (o'chirilgan bo'lishi mumkin).")
        name = day.name
        if action == "delete" and day.state == "done":
            action = "cancel"  # tasdiqlangani o'chirilmaydi — bekor qilinadi (ombor qaytariladi, tarix qoladi)
        if action == "delete":
            day.unlink()
            return {"result": "deleted", "name": name}
        if action == "cancel":
            if day.state != "done":
                raise UserError("%s tasdiqlanmagan." % name)
            day._craf_check_edit()
            before = day._craf_edit_snapshot()
            since = self._last_move_id()
            self._day_check_lock(day)
            day._craf_cancel_done()
            self._edit_guard(since)
            day._craf_log_edit(before, kind="cancel")
            return {"result": "cancel", "name": name}
        raise UserError("Bu amal mumkin emas.")

    # ================================================================== BO'YASH
    @api.model
    def paint_options(self):
        loc = self._loc("Bo'yash sexi")
        norm = self.env["craf.mrp.norm"]._get_norm(self.env.company)
        colors = []
        for c in self.env["craf.color"].search([("is_painted", "=", True)], order="name"):
            powder = c.paint_tmpl_id.product_variant_id
            colors.append({
                "id": c.id, "name": c.name, "powder_id": powder.id or False, "powder": powder.name or "",
                "pkg_kg": powder.product_tmpl_id.craf_pkg_kg if powder else 0.0,
                "pkg_name": (powder.product_tmpl_id.craf_pkg_name or "quti") if powder else "",
                "avail": round(powder.with_context(location=loc.id).qty_available, 2) if powder and loc else 0.0,
            })
        # bo'yalmagan profillar: sexdagi qoldiq va har rang uchun bo'yalgan juftligi
        Tmpl = self.env["product.template"]
        raw = Tmpl._craf_raw_color()
        semis = self.env["product.product"].search([("craf_color_id", "=", raw.id), ("craf_section_id", "!=", False)],
                                                   order="default_code") if raw else self.env["product.product"]
        painted = Tmpl.search([("craf_section_id", "in", semis.craf_section_id.ids), ("craf_color_id.is_painted", "=", True)])
        index = {(t.craf_section_id.id, round(t.craf_length_m, 3), t.craf_color_id.id): t for t in painted}
        stock = {}
        if loc:
            for product, qty in self.env["stock.quant"]._read_group(
                    [("location_id", "child_of", loc.id), ("product_id", "in", semis.ids)], ["product_id"], ["quantity:sum"]):
                stock[product.id] = qty
        semi_rows = []
        for s in semis:
            variants = {}
            for c in colors:
                t = index.get((s.craf_section_id.id, round(s.craf_length_m, 3), c["id"]))
                if t:
                    variants[str(c["id"])] = {"id": t.product_variant_id.id, "name": t.name,
                                              "per_pack": t.craf_pcs_per_pack or s.craf_pcs_per_pack}
            semi_rows.append({
                "id": s.id, "name": s.name, "code": s.default_code or "", "avail": round(stock.get(s.id, 0.0)),
                "per_pack": s.craf_pcs_per_pack, "kg_pc": round(s.craf_kg_per_pc, 4),
                "area_pc": round(s.craf_length_m * (s.craf_section_id.perimeter_m or 0.0), 4), "variants": variants,
            })
        return {
            "today": fields.Date.to_string(fields.Date.context_today(self)),
            "colors": colors, "semis": semi_rows, "powder_g_m2": norm["powder_g_m2"],
            "pack_materials": self._pack_materials_info(loc, norm),
            "employees": self._employees(), "equipment": self._equipment("boyash"),
            "my_employee": self.env.user.employee_id.id or False,
            "shifts": [{"key": k, "label": v} for k, v in SHIFTS],
        }

    def _pack_materials_info(self, loc, norm):
        H = self.env["craf.production.mixin"]
        res = []
        for key, code, per_pack in (("film", "QM-01", norm.film_kg_per_pack), ("tape", "QM-02", norm.tape_m_per_pack)):
            product = H._craf_product(code)
            if not product:
                continue
            res.append({"key": key, "id": product.id, "name": product.name, "uom": self._uom_label(product),
                        "per_pack": per_pack,
                        "avail": round(product.with_context(location=loc.id).qty_available, 2) if loc else 0.0})
        return res

    @api.model
    def paint_load(self, rec_id):
        rec = self.env["craf.paint.batch"].browse(int(rec_id)).exists()
        if not rec:
            raise UserError("Bo'yash smenasi topilmadi.")
        return {
            "id": rec.id, "name": rec.name, "state": rec.state, "date": fields.Date.to_string(rec.date),
            "shift": rec.shift, "color_id": rec.color_id.id or False, "employee_id": rec.employee_id.id or False,
            "equipment_id": rec.equipment_id.id or False, "load_ids": rec.load_ids.ids,
            "loads": [self._load_info(l) for l in rec.load_ids],
            "lines": [{"semi_id": l.semi_product_id.id, "pcs_in": l.pcs_in or "", "defect": l.pcs_defect or "",
                       "packs": l.out_packs or "", "extra": l.out_extra or ""} for l in rec.line_ids],
            "powder_text": _q(rec.powder_qty, 2) if rec.powder_qty else "",
            "powder_bags": rec.powder_bags or "", "note": rec.note or "",
            "film_text": _q(rec.film_qty, 2) if rec.film_qty else "",
            "tape_text": _q(rec.tape_qty, 1) if rec.tape_qty else "",
        }

    @api.model
    def paint_save(self, vals, confirm=False):
        Batch = self.env["craf.paint.batch"]
        rec = Batch.browse(int(vals["id"])).exists() if vals.get("id") else Batch
        if vals.get("id"):
            self._check_draft(rec)
        color = self.env["craf.color"].browse(int(vals.get("color_id") or 0)).exists()
        if not color:
            raise UserError("Rangni tanlang.")
        loads = self.env["craf.basket.load"].browse([int(i) for i in vals.get("load_ids") or []]).exists()
        bad = loads.filtered(lambda l: l.state != "kimyo" and l not in rec.load_ids)
        if bad:
            raise UserError("Bu korzinkalar bo'yashga tayyor emas: %s" % ", ".join(bad.mapped("basket_id.name")))
        lines = []
        for row in vals.get("lines") or []:
            if not row.get("semi_id"):
                continue
            pcs_in = self._int(row.get("pcs_in"))
            defect = self._int(row.get("defect"))
            packs = self._int(row.get("packs"))
            extra = self._int(row.get("extra"))
            if not (pcs_in or packs or extra):
                continue
            lines.append({"semi_product_id": int(row["semi_id"]), "pcs_in": pcs_in, "pcs_defect": defect,
                          "out_packs": packs, "out_extra": extra})
        if not lines:
            raise UserError("Kamida bitta profil qatorini yozing (kirdi yoki qadoqlandi).")
        powder = self._num(vals.get("powder_text"), "Kukun")
        bags = float(str(vals.get("powder_bags") or 0).replace(",", ".") or 0)
        header = {
            "date": vals.get("date") or fields.Date.context_today(self),
            "shift": vals.get("shift") or "1",
            "color_id": color.id,
            "employee_id": int(vals["employee_id"]) if vals.get("employee_id") else self._own_employee(),
            "equipment_id": int(vals["equipment_id"]) if vals.get("equipment_id") else False,
            "note": (vals.get("note") or "").strip() or False,
            "load_ids": [Command.set(loads.ids)],
            "powder_bags": bags,
        }
        self._H._moment(header["date"])
        if not rec:
            rec = Batch.create(header)
        else:
            rec.write(header)
        if bags and not powder and rec.powder_pkg_kg:
            powder = round(bags * rec.powder_pkg_kg, 2)
        commands = [Command.clear()]
        for line in lines:
            # qadoqlangan berilsa va kirdi berilmasa — kirdi = qadoqlandi + brak
            commands.append(Command.create(line))
        own_issue = self.env.user._craf_own_app() == "boyash"
        rec.write({"line_ids": commands, "powder_qty": 0.0 if own_issue else powder})
        # qadoqlash materiallari: yozilmagan bo'lsa — me'yor × qadoqlangan pachka
        norm = self.env["craf.mrp.norm"]._get_norm(self.env.company)
        packs = sum(rec.line_ids.mapped("out_packs"))
        film = self._num(vals.get("film_text"), "Plyonka")
        tape = self._num(vals.get("tape_text"), "Lenta")
        if own_issue:
            # bo'yash xodimi bo'yoq, salofan va lentani ombordan olganda yozadi (Materiallar → sarf) — smenada yechilmaydi;
            # stiker — avtomatik (profil uzunligi va tomoni bo'yicha)
            rec.write({"film_qty": 0.0, "tape_qty": 0.0})
        else:
            rec.write({
                "film_qty": film if (vals.get("film_text") or "").strip() else round(packs * norm.film_kg_per_pack, 2),
                "tape_qty": tape if (vals.get("tape_text") or "").strip() else round(packs * norm.tape_m_per_pack, 1),
            })
        for line in rec.line_ids:
            if line.pcs_packed and not line.pcs_in:
                line.write({"pcs_in": line.pcs_packed + (line.pcs_defect or 0), "pcs_in_auto": True})
        if confirm:
            self._confirm(rec)
        return {"id": rec.id, "name": rec.name, "state": rec.state}

    # ================================================================== hujjat
    def _touched_products(self, rec):
        if rec._name == "craf.extrusion.shift":
            return rec.billet_product_id | rec.rest_product_id | rec.scrap_product_id | rec.line_ids.product_id \
                | rec.basket_load_ids.product_6_id | rec.basket_load_ids.product_5_id                 | rec.basket_load_ids.extra_line_ids.product_6_id | rec.basket_load_ids.extra_line_ids.product_5_id
        if rec._name == "craf.chem.treatment":
            return rec.chem_line_ids.product_id | rec.defect_line_ids.product_id                 | self.env["craf.production.mixin"]._craf_product("PF-07")                 | rec.load_ids.product_6_id | rec.load_ids.product_5_id                 | rec.load_ids.extra_line_ids.product_6_id | rec.load_ids.extra_line_ids.product_5_id
        return rec.line_ids.semi_product_id | rec.line_ids.product_id | rec.powder_product_id | rec.scrap_product_id \
            | rec.film_product_id | rec.tape_product_id

    def _raw_needs(self, rec):
        """Sexga kerak bo'ladigan xom-ashyo (profil emas): quyma, kimyo, kukun — {product: qty}."""
        needs = defaultdict(float)
        if rec._name == "craf.extrusion.shift":
            if rec.billet_qty > EPS:
                needs[rec.billet_product_id] += rec.billet_qty
        elif rec._name == "craf.chem.treatment":
            for line in rec.chem_line_ids.filtered(lambda l: l.qty > EPS and not l.move_id):
                needs[line.product_id] += line.qty
        else:
            if rec.powder_qty > EPS and rec.powder_product_id:
                needs[rec.powder_product_id] += rec.powder_qty
            for line in rec.chem_line_ids.filtered(lambda l: l.qty > EPS):
                needs[line.product_id] += line.qty
            for product, qty in rec._craf_pack_materials():
                needs[product] += qty
        return {p: q for p, q in needs.items() if p and p.is_storable and not p.craf_section_id}

    def _auto_pull(self, rec):
        """Sexda yetmagan xom-ashyo (kukun, kimyo, quyma) boshqa ichki joydan — avval Xom-ashyo omboridan —
        avtomatik ko'chiriladi (Литейка dagi kabi). Butun zavodda ham yetmasa — aniq xabar."""
        src = rec.location_src_id
        needs = self._raw_needs(rec)
        if not needs or not src:
            return self.env["stock.picking"]
        missing = []
        for product, qty in needs.items():
            have = product.qty_available
            if qty - have > EPS:
                missing.append("• %s: kerak %s, zavodda bor %s %s" % (
                    product.display_name, _q(qty, 2), _q(have, 2), self._uom_label(product)))
        if missing:
            raise UserError("Qoldiq yetarli emas:\n%s\n\nAvval kirim yoki sanash bilan qoldiqni to'g'rilang." %
                            "\n".join(missing))
        raw_store = self._loc("Xom-ashyo ombori")
        inside = self.env["stock.location"].search([("id", "child_of", src.id)]).ids
        plan = defaultdict(list)
        for product, qty in needs.items():
            short = qty - product.with_context(location=src.id).qty_available
            if short <= EPS:
                continue
            by_loc = defaultdict(float)
            for quant in self.env["stock.quant"].search([
                    ("product_id", "=", product.id), ("location_id.usage", "=", "internal"),
                    ("location_id", "not in", inside), ("quantity", ">", 0),
                    ("company_id", "in", [rec.company_id.id, False])]):
                by_loc[quant.location_id] += quant.quantity
            for loc, avail in sorted(by_loc.items(), key=lambda kv: (kv[0] != raw_store, -kv[1])):
                take = min(short, avail)
                if take > EPS:
                    plan[loc].append((product, take))
                    short -= take
                if short <= EPS:
                    break
        pickings = self.env["stock.picking"]
        Docs = self._H
        for loc, items in plan.items():
            warehouse = src.warehouse_id or loc.warehouse_id or self.env["stock.warehouse"].search(
                [("company_id", "=", rec.company_id.id)], limit=1)
            picking = self.env["stock.picking"].create({
                "picking_type_id": warehouse.int_type_id.id,
                "location_id": loc.id, "location_dest_id": src.id, "origin": rec.name,
                "move_ids": [Command.create({
                    "product_id": p.id, "product_uom_qty": q, "product_uom": p.uom_id.id,
                    "location_id": loc.id, "location_dest_id": src.id, "origin": rec.name,
                }) for p, q in items],
            })
            Docs._validate_picking(picking)
            pickings |= picking
        if pickings:
            rec.message_post(body="Avto ko'chirildi (sexda yetmagan xom-ashyo): %s" % ", ".join(pickings.mapped("name")))
            if "picking_ids" in rec._fields:
                rec.picking_ids = [Command.link(p.id) for p in pickings]
        return pickings

    # ================================================================== TAHRIRLASH (24 soat)
    def _last_move_id(self):
        return self.env["stock.move"].sudo().search([], order="id desc", limit=1).id or 0

    def _edit_guard(self, since):
        """Tahrir (eski harakat qaytarilib, yangisi yozilgach) ombordagi qoldiqni manfiy qilib qo'ysa — to'xtatadi:
        masalan, tayyor mahsulot sotilgan yoki 5 m profil bo'yalgan. Chiqindi (Литейка) joylari tekshirilmaydi."""
        moves = self.env["stock.move"].sudo().search([("id", ">", since), ("state", "=", "done")])
        delta = defaultdict(float)
        for m in moves:
            if m.location_id.usage == "internal":
                delta[(m.product_id, m.location_id)] -= m.product_qty
            if m.location_dest_id.usage == "internal":
                delta[(m.product_id, m.location_dest_id)] += m.product_qty
        waste = self._loc("Литейка") | self._loc("Chiqindi")
        Quant = self.env["stock.quant"].sudo()
        bad = []
        for (product, loc), change in delta.items():
            if change >= -EPS or loc in waste:
                continue
            qty = sum(Quant.search([("product_id", "=", product.id), ("location_id", "=", loc.id)]).mapped("quantity"))
            if qty < -EPS:
                bad.append("%s — %s: %s %s" % (loc.name, product.display_name, _q(qty, 2), self._uom_label(product)))
        if bad:
            raise UserError("Tahrirlab bo'lmaydi — ombordagi qoldiq manfiy bo'lib qoladi (mahsulot keyingi bosqichga "
                            "o'tgan yoki sotilgan bo'lishi mumkin):\n" + "\n".join(bad))

    def _confirm(self, rec):
        """O'tgan sanadagi hujjat: shu sanadan keyin qoldiq sanalgan bo'lsa — to'xtatadi (ikki marta yozilmasin).
        Sexda yetmagan xom-ashyo boshqa joydan avtomatik ko'chiriladi."""
        moment = self._H._moment(rec.date)
        self._H._check_lock(self._touched_products(rec), moment, rec.name)
        self._auto_pull(rec)
        rec.action_done()

    def _rec(self, stage, rec_id):
        rec = self._model(stage).browse(int(rec_id)).exists()
        if not rec:
            raise UserError("Hujjat topilmadi (o'chirilgan bo'lishi mumkin).")
        return rec

    @api.model
    def doc_detail(self, stage, rec_id):
        rec = self._rec(stage, rec_id)
        card = self._card(stage, rec)
        meta, lines, outputs = [], [], []
        meta += [m for m in [("Sana", rec.date.strftime("%d.%m.%Y")), ("Smena", card["shift"]),
                             ("Uskuna", card["equipment"]), ("Mas'ul", card["who"])] if m[1]]
        if stage == "press":
            meta += [("Matritsa", rec.section_id.name), ("Quyma", rec.billet_product_id.display_name)]
            if rec.melt_ids:
                meta.append(("Quyma partiyasi", ", ".join(rec.melt_ids.mapped("name"))))
            for load in rec.basket_load_ids.sorted("id"):
                lines.append({"name": "%s · %s" % (load.basket_id.name, load.content),
                              "qty": "%s dona" % load.pcs_total,
                              "note": "%s kg (nazariy %s)" % (_q(load.net_kg or load.kg_theory, 1), _q(load.kg_theory, 1))})
            for line in rec.line_ids.filtered(lambda l: l.pcs):
                loads = rec.basket_load_ids
                if line.product_id in (loads.product_6_id | loads.product_5_id | loads.extra_line_ids.product_6_id
                                       | loads.extra_line_ids.product_5_id):
                    continue
                lines.append({"name": line.product_id.name, "qty": "%s dona" % line.pcs,
                              "note": "%s kg → %s" % (_q(line.kg, 1), line.location_dest_id.name or "")})
            outputs = [("Quyma sarfi", "%s kg" % _q(rec.billet_qty, 1)), ("Profil", "%s kg" % _q(rec.output_kg, 1)),
                       ("Питак", "%s kg" % _q(rec.rest_qty, 1)), ("Otxod (brak profil)", "%s kg" % _q(rec.scrap_qty, 1)),
                       ("Chiqish", "%s%%" % fmt(rec.yield_pct, 1)), ("Farq", "%s kg" % _q(rec.loss_qty, 1))]
        elif stage == "kimyo":
            for load in rec.load_ids:
                lines.append({"name": "%s · %s" % (load.basket_id.name, load.content), "qty": "%s dona" % load.pcs_total,
                              "note": "%s kg · %s m²" % (_q(load.net_kg or load.kg_theory, 1), _q(load.area_m2, 1))})
            kinds = {"brak": "yaroqsiz", "cut": "6 → 5 m kesildi"}
            for line in rec.defect_line_ids:
                lines.append({"name": "%s · %s" % (line.load_id.basket_id.name, line.product_id.name),
                              "qty": "%s dona" % line.qty, "note": "%s, %s kg Liteykaga" % (kinds[line.kind], _q(line.kg, 1))})
            if rec.sort_id:
                meta.append(("Brak ajratish", rec.sort_id.name))
            outputs = [("Yaroqsiz", "%s dona" % rec.brak_pcs), ("6 → 5 m kesildi", "%s dona" % rec.cut_pcs)]
            outputs += [("%s" % l.product_id.name, "%s kg (me'yor %s)" % (fmt(l.qty, 2), fmt(l.qty_norm, 2)))
                        for l in rec.chem_line_ids]
            outputs.append(("Maydon", "%s m²" % _q(rec.area_total, 1)))
        else:
            meta.append(("Rang", rec.color_id.name))
            if rec.load_ids:
                meta.append(("Korzinkalar", ", ".join(rec.load_ids.mapped("basket_id.name"))))
            for line in rec.line_ids:
                lines.append({"name": line.product_id.name or line.semi_product_id.name,
                              "qty": "%s dona" % line.pcs_ok,
                              "note": "kirdi %s, brak %s%s" % (line.pcs_in, line.pcs_defect,
                                                               (", qadoqlandi %s" % line.packs_text) if line.pcs_packed else "")})
            outputs = [("Bo'yaldi", "%s dona · %s kg" % (_q(rec.pcs_ok), _q(rec.kg_ok, 1))),
                       ("Brak", "%s dona (%s%%)" % (_q(rec.pcs_defect), fmt(rec.defect_pct, 2))),
                       ("Kukun", "%s kg (me'yor %s)" % (fmt(rec.powder_qty, 2), fmt(rec.powder_norm_qty, 2))),
                       ("Plyonka", "%s %s" % (fmt(rec.film_qty, 2), self._uom_label(rec.film_product_id) if rec.film_product_id else "")),
                       ("Lenta", "%s %s" % (fmt(rec.tape_qty, 1), self._uom_label(rec.tape_product_id) if rec.tape_product_id else "")),
                       ("Maydon", "%s m²" % _q(rec.area_total, 1))]
            if rec.stock_picking_id:
                meta.append(("Omborga topshirildi", rec.stock_picking_id.name))
        if rec.production_ids:
            meta.append(("Ishlab chiqarish", ", ".join(rec.production_ids.mapped("name"))))
        pulls = self.env["stock.picking"].search([("origin", "=", rec.name), ("picking_type_code", "=", "internal"),
                                                  ("location_dest_id", "=", rec.location_src_id.id)])
        if pulls:
            meta.append(("Avto ko'chirish", ", ".join(pulls.mapped("name"))))
        if rec.c1_state == "done":
            meta.append(("1C", "kiritildi %s%s" % (
                self._H._local(rec.c1_date) if rec.c1_date else "", (", " + rec.c1_user_id.name) if rec.c1_user_id else "")))
        roles = self._roles()
        packs = self.env["craf.pack"].search_count([("origin", "=", rec.name)]) if rec.state == "done" else 0
        edit = rec._craf_edit_info() if stage in ("kimyo", "press") and rec.state == "done" else False
        actions = []
        if rec.state == "draft":
            actions += ["edit", "done", "cancel", "delete"]
            if stage == "press":
                actions.append("basket")
        elif rec.state == "cancel":
            actions += ["draft", "delete"]
        else:
            if stage == "boyash" and not rec.stock_picking_id:
                actions.append("to_stock")
            if stage in ("boyash", "press") and rec._craf_pack_items():
                actions.append("labels")
            if roles["accountant"]:
                actions.append("c1_undo" if rec.c1_state == "done" else "c1")
            if edit and edit["can"]:
                # press: «Tahrirlash» smenani qoralamaga qaytaradi (korzinkalar alohida tuzatiladi)
                actions += ["reopen"] if stage == "press" else ["edit", "void"]
        if not roles["own"]:
            actions.append("open")
        return {
            "stage": stage, "id": rec.id, "name": rec.name, "state": rec.state,
            "state_label": STATE_LABELS.get(rec.state, rec.state), "title": card["title"],
            "meta": meta, "lines": lines, "outputs": outputs, "actions": actions, "packs": packs,
            "c1": rec.c1_state, "note": rec.note or "",
            "loads": card.get("loads", []), "section_id": card.get("section_id") or False,
            "edit": edit, "history": rec._craf_edit_history() if stage in ("kimyo", "press") else [],
        }

    @api.model
    def doc_action(self, stage, rec_id, action):
        rec = self._rec(stage, rec_id)
        name = rec.name
        if action == "done":
            self._check_draft(rec)
            self._confirm(rec)
        elif action == "cancel":
            rec.action_cancel()
        elif action == "draft":
            rec.action_draft()
        elif action == "void":
            if stage != "kimyo":
                raise UserError("Bu amal faqat kimyoviy ishlov uchun.")
            return self._chem_cancel(rec)
        elif action == "reopen":
            if stage != "press" or rec.state != "done":
                raise UserError("Bu amal faqat tasdiqlangan press smenasi uchun.")
            since = self._last_move_id()
            self._H._check_lock(self._touched_products(rec), self._H._moment(rec.date), rec.name)
            rec._craf_edit_reopen()
            self._edit_guard(since)
        elif action == "delete":
            if rec.state not in ("draft", "cancel"):
                raise UserError("Faqat qoralama yoki bekor qilingan hujjat o'chiriladi.")
            rec.unlink()
            return {"result": "deleted", "name": name}
        elif action in ("c1", "c1_undo"):
            if not self._roles()["accountant"]:
                raise UserError("1C belgisini omborchi qo'yadi.")
            rec.action_c1_done() if action == "c1" else rec.action_c1_reset()
        elif action == "to_stock":
            if stage != "boyash":
                raise UserError("Bu amal faqat bo'yash smenasi uchun.")
            rec.action_send_to_stock()
            return {"result": action, "name": name, "picking": rec.stock_picking_id.name}
        elif action == "labels":
            act = rec.action_make_packs()
            # kompaniyada hujjat ko'rinishi tanlanmagan bo'lsa, Odoo avval sozlash oynasini qaytaradi — yorliqqa
            # tashqi ko'rinish kerak emas, to'g'ridan-to'g'ri hisobotning o'zini qaytaramiz
            if isinstance(act, dict) and act.get("res_model") == "base.document.layout":
                act = (act.get("context") or {}).get("report_action") or act
            return {"result": action, "name": name, "action": act}
        else:
            raise UserError("Bu amal mumkin emas.")
        return {"result": action, "name": name, "state": rec.state if rec.exists() else False}
