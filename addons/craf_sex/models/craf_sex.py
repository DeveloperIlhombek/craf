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
        }

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
        if stage not in STAGE:
            stage = roles["stage"] if roles["stage"] in STAGE else "press"
        dfrom, dto = self._H._period(date_from, date_to)
        Model = self._model(stage)
        docs = Model.search([("date", ">=", dfrom), ("date", "<=", dto)], order="date desc, id desc")
        drafts = Model.search([("state", "=", "draft")], order="date desc, id desc")
        stages = []
        for key, label, model, _loc in STAGES:
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
            "kpi": getattr(self, "_kpi_%s" % stage)(docs.filtered(lambda d: d.state == "done")),
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
            "shift": dict(SHIFTS).get(rec.shift, ""),
        }
        res.update(getattr(self, "_card_%s" % stage)(rec))
        return res

    def _card_press(self, rec):
        loads = rec.basket_load_ids
        return {
            "title": " · ".join(x for x in [rec.equipment_id.sudo().name, rec.section_id.name] if x) or "Press smenasi",
            "sub": "%s dona · %s kg" % (_q(rec.output_pcs), _q(rec.output_kg)) if rec.state == "done" else
            "%s ta korzinka · %s dona" % (len(loads), _q(sum(loads.mapped("pcs_total")))),
            "metric": "chiqish %s%%" % fmt(rec.yield_pct, 1) if rec.state == "done" and rec.yield_pct else "",
            "loads": [self._load_info(l) for l in loads.sorted("id")] if rec.state == "draft" else [],
            "billet": rec.billet_qty, "section_id": rec.section_id.id, "section": rec.section_id.name or "",
        }

    def _card_kimyo(self, rec):
        return {
            "title": "%s ta korzinka" % rec.basket_count,
            "sub": "%s dona · %s kg · %s m²" % (_q(rec.pcs_total), _q(rec.kg_total), _q(rec.area_total)),
            "metric": "kimyo %s kg" % fmt(rec.chem_kg, 2) if rec.chem_kg else "",
            "loads": [self._load_info(l) for l in rec.load_ids] if rec.state == "draft" else [],
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

    def _kpi_kimyo(self, done):
        norm = self.env["craf.mrp.norm"]._get_norm(self.env.company)
        area = sum(done.mapped("area_total"))
        chem = sum(done.mapped("chem_kg"))
        norm_kg = area * sum(norm[f] for _c, f in CHEMS)
        return [
            {"label": "Ishlov", "value": _q(len(done)), "unit": ""},
            {"label": "Korzinkalar", "value": _q(sum(done.mapped("basket_count"))), "unit": "ta"},
            {"label": "Profil", "value": _q(sum(done.mapped("kg_total")), 0), "unit": "kg",
             "sub": "%s dona" % _q(sum(done.mapped("pcs_total")))},
            {"label": "Maydon", "value": _q(area, 0), "unit": "m²"},
            {"label": "Kimyo sarfi", "value": fmt(chem, 1), "unit": "kg",
             "sub": "me'yor %s kg" % fmt(norm_kg, 1) if norm_kg else "",
             "tone": self._tone_over(chem, norm_kg)},
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
    def _load_info(self, load):
        products = [{"id": p.id, "name": p.name, "qty": q, "length": p.craf_length_m}
                    for p, q in load._product_quantities().items()]
        return {
            "id": load.id, "basket_id": load.basket_id.id, "basket": load.basket_id.name,
            "content": load.content or "", "section": load.section_id.name or "",
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
        return {
            "today": fields.Date.to_string(fields.Date.context_today(self)),
            "presses": self._equipment("press"),
            "sections": sections,
            "employees": self._employees(),
            "shifts": [{"key": k, "label": v} for k, v in SHIFTS],
            "billets": [{"id": b.id, "name": b.name, "code": b.default_code,
                         "avail": round(b.with_context(location=press_loc.id).qty_available, 1) if press_loc else 0.0}
                        for b in billets],
            "baskets": [{"id": b.id, "name": b.name, "tare": b.tare_kg, "capacity": b.capacity}
                        for b in self.env["craf.basket"].search([("state", "=", "empty")], order="name")],
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
            "shift": rec.shift, "employee_id": rec.employee_id.id or False,
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
        section = self.env["craf.profile.section"].browse(int(vals.get("section_id") or 0)).exists()
        if not section:
            raise UserError("Matritsani (profil kesimini) tanlang.")
        if rec and rec.basket_load_ids and rec.section_id != section:
            raise UserError("Smenada korzinkalar bor — matritsani o'zgartirib bo'lmaydi. Yangi smena oching.")
        header = {
            "date": vals.get("date") or fields.Date.context_today(self),
            "equipment_id": int(vals["equipment_id"]) if vals.get("equipment_id") else False,
            "section_id": section.id,
            "shift": vals.get("shift") or "1",
            "employee_id": int(vals["employee_id"]) if vals.get("employee_id") else False,
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
        data = {
            "basket_id": int(vals.get("basket_id") or 0) or load.basket_id.id,
            "qty_6": qty_6, "qty_5": qty_5,
            "gross_kg": self._num(vals.get("gross_text"), "Tortilgan og'irlik"),
        }
        if not data["basket_id"]:
            raise UserError("Korzinkani tanlang.")
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
            "load_ids": rec.load_ids.ids, "loads": [self._load_info(l) for l in rec.load_ids],
            "chem": {str(l.product_id.id): _q(l.qty, 2) for l in rec.chem_line_ids},
            "note": rec.note or "",
        }

    @api.model
    def chem_save(self, vals, confirm=False):
        Chem = self.env["craf.chem.treatment"]
        rec = Chem.browse(int(vals["id"])).exists() if vals.get("id") else Chem
        if vals.get("id"):
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
            "employee_id": int(vals["employee_id"]) if vals.get("employee_id") else False,
            "equipment_id": int(vals["equipment_id"]) if vals.get("equipment_id") else False,
            "note": (vals.get("note") or "").strip() or False,
            "load_ids": [Command.set(loads.ids)],
        }
        self._H._moment(header["date"])
        if not rec:
            rec = Chem.create(header)
        else:
            rec.write(header)
        area = rec.area_total
        chem_vals = vals.get("chem") or {}
        lines = [Command.clear()]
        for c in self._chem_norms():
            text = chem_vals.get(str(c["id"]))
            norm_qty = round(area * c["per_m2"], 2)
            qty = norm_qty if text in (None, "") else self._num(text, c["name"])
            lines.append(Command.create({"product_id": c["id"], "qty_norm": norm_qty, "qty": qty}))
        rec.write({"chem_line_ids": lines})
        if confirm:
            self._confirm(rec)
        return {"id": rec.id, "name": rec.name, "state": rec.state}

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
            "employee_id": int(vals["employee_id"]) if vals.get("employee_id") else False,
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
        rec.write({"line_ids": commands, "powder_qty": powder})
        # qadoqlash materiallari: yozilmagan bo'lsa — me'yor × qadoqlangan pachka
        norm = self.env["craf.mrp.norm"]._get_norm(self.env.company)
        packs = sum(rec.line_ids.mapped("out_packs"))
        film = self._num(vals.get("film_text"), "Plyonka")
        tape = self._num(vals.get("tape_text"), "Lenta")
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
                | rec.basket_load_ids.product_6_id | rec.basket_load_ids.product_5_id
        if rec._name == "craf.chem.treatment":
            return rec.chem_line_ids.product_id | rec.load_ids.product_6_id | rec.load_ids.product_5_id
        return rec.line_ids.semi_product_id | rec.line_ids.product_id | rec.powder_product_id | rec.scrap_product_id \
            | rec.film_product_id | rec.tape_product_id

    def _raw_needs(self, rec):
        """Sexga kerak bo'ladigan xom-ashyo (profil emas): quyma, kimyo, kukun — {product: qty}."""
        needs = defaultdict(float)
        if rec._name == "craf.extrusion.shift":
            if rec.billet_qty > EPS:
                needs[rec.billet_product_id] += rec.billet_qty
        elif rec._name == "craf.chem.treatment":
            for line in rec.chem_line_ids.filtered(lambda l: l.qty > EPS):
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
                if line.product_id in rec.basket_load_ids.product_6_id | rec.basket_load_ids.product_5_id:
                    continue
                lines.append({"name": line.product_id.name, "qty": "%s dona" % line.pcs,
                              "note": "%s kg → %s" % (_q(line.kg, 1), line.location_dest_id.name or "")})
            outputs = [("Quyma sarfi", "%s kg" % _q(rec.billet_qty, 1)), ("Profil", "%s kg" % _q(rec.output_kg, 1)),
                       ("Питак", "%s kg" % _q(rec.rest_qty, 1)), ("Brak", "%s kg" % _q(rec.scrap_qty, 1)),
                       ("Chiqish", "%s%%" % fmt(rec.yield_pct, 1)), ("Farq", "%s kg" % _q(rec.loss_qty, 1))]
        elif stage == "kimyo":
            for load in rec.load_ids:
                lines.append({"name": "%s · %s" % (load.basket_id.name, load.content), "qty": "%s dona" % load.pcs_total,
                              "note": "%s kg · %s m²" % (_q(load.net_kg or load.kg_theory, 1), _q(load.area_m2, 1))})
            outputs = [("%s" % l.product_id.name, "%s kg (me'yor %s)" % (fmt(l.qty, 2), fmt(l.qty_norm, 2)))
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
        actions.append("open")
        return {
            "stage": stage, "id": rec.id, "name": rec.name, "state": rec.state,
            "state_label": STATE_LABELS.get(rec.state, rec.state), "title": card["title"],
            "meta": meta, "lines": lines, "outputs": outputs, "actions": actions, "packs": packs,
            "c1": rec.c1_state, "note": rec.note or "",
            "loads": card.get("loads", []), "section_id": card.get("section_id") or False,
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
