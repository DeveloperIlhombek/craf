"""Matritsa xodimi sahifasi (telefon birinchi) uchun server tomoni: matritsalar, Ammiak va Azot ballonlari sarfi,
kaustik soda olish, qoldiqlar."""
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt

GAS_REFS = ("craf_gaz.gaz_ammiak", "craf_gaz.gaz_azot")
GAS_NAMES = ("Ammiak", "Azot")


def _q(value, digits=1):
    value = value or 0.0
    return fmt(value, 0) if abs(value - round(value)) < 1e-9 else fmt(value, digits)


class CrafMatritsa(models.AbstractModel):
    _name = "craf.matritsa"
    _description = "Craf matritsa xodimi sahifasi"

    # ------------------------------------------------------------------ yordamchi
    def _check(self):
        """Sahifa: matritsa xodimi, omborchi, direktor va administrator."""
        user = self.env.user
        if self.env.su or user.has_group("base.group_system") or user.has_group("craf_sex.group_craf_accountant") \
                or (user.craf_work_stage == "matritsa" and user.has_group("craf_sex.group_craf_worker")):
            return
        raise AccessError("«Matritsa» sahifasiga ruxsatingiz yo'q. Rolingizni direktordan so'rang.")

    @property
    def _H(self):
        return self.env["craf.litey.hisobot"]

    def _num(self, text, label):
        if text in (None, False, ""):
            return 0.0
        if isinstance(text, (int, float)):
            return float(text)
        return self._H._num(text, label) or 0.0

    def _gas_types(self):
        types = self.env["craf.gaz.type"]
        for ref in GAS_REFS:
            types |= self.env.ref(ref, raise_if_not_found=False) or types.browse()
        if not types:
            types = types.search([("name", "in", GAS_NAMES)])
        return types

    def _soda_location(self):
        Issue = self.env["craf.chem.issue"]
        return Issue._craf_loc(Issue._craf_default_src)

    # ------------------------------------------------------------------ asosiy
    @api.model
    def get_data(self):
        self._check()
        today = fields.Date.context_today(self)
        # matritsalar
        matrices = self.env["craf.matrix"].search([])
        rows, by_section = [], {}
        for m in matrices:
            rows.append({
                "id": m.id, "name": m.name, "section_id": m.section_id.id, "section": m.section_id.name,
                "state": m.state, "note": m.note or "", "broken_note": m.broken_note or "",
                "broken_date": m.broken_date.strftime("%d.%m.%Y") if m.broken_date else "",
                # rasm: kichigi ro'yxatda, kattasi ko'rish uchun; unique — keshlangan eski rasm chiqmasin
                "image": bool(m.image_128),
                "unique": fields.Datetime.to_string(m.write_date).replace(" ", "").replace("-", "").replace(":", ""),
                "edit": m._craf_edit_info(),
            })
            s = by_section.setdefault(m.section_id.id, {"id": m.section_id.id, "name": m.section_id.name,
                                                        "total": 0, "ok": 0, "broken": 0})
            s["total"] += 1
            s[m.state] += 1
        sections = sorted(by_section.values(), key=lambda s: s["name"] or "")
        # gaz (Ammiak, Azot)
        since = fields.Datetime.now() - timedelta(days=30)
        Move = self.env["craf.gaz.move"]
        gas = []
        for t in self._gas_types():
            ballons = self.env["craf.gaz.ballon"].search([("type_id", "=", t.id)])
            used = {}
            for mv in Move.search([("type_id", "=", t.id), ("kind", "=", "use"), ("date", ">=", since)]):
                used[mv.ballon_id.id] = used.get(mv.ballon_id.id, 0.0) + mv.qty
            unit = dict(t._fields["unit"].selection).get(t.unit, "")
            gas.append({
                "id": t.id, "name": t.name, "formula": t.code or "", "color": t.color or "#3BA4E8", "unit": unit,
                "qty": round(sum(ballons.mapped("qty")), 2), "capacity": round(sum(ballons.mapped("capacity")), 2),
                "used_30": round(sum(used.values()), 2),
                "ballons": [{"id": b.id, "name": b.name, "qty": round(b.qty, 2), "capacity": b.capacity,
                             "percent": b.percent, "state": b.state, "used_30": round(used.get(b.id, 0.0), 2),
                             "location": b.location_id.name or ""} for b in ballons],
            })
        tz_moves = Move.search([("type_id", "in", self._gas_types().ids), ("kind", "=", "use")], limit=15)
        gas_moves = [{
            "id": mv.id, "ballon": mv.ballon_id.name, "type": mv.type_id.name, "color": mv.type_id.color or "#3BA4E8",
            "qty": _q(mv.qty, 2), "after": _q(mv.qty_after, 2),
            "unit": dict(mv.type_id._fields["unit"].selection).get(mv.type_id.unit, ""),
            "date": fields.Datetime.context_timestamp(self, mv.date).strftime("%d.%m %H:%M"),
            "who": mv.user_id.name or "", "note": mv.note or "",
            "ballon_id": mv.ballon_id.id, "type_id": mv.type_id.id, "qty_raw": mv.qty,
            "edit": mv._craf_edit_info(),
        } for mv in tz_moves]
        # kaustik soda
        Issue = self.env["craf.chem.issue"]
        issues = Issue.search([("kind", "=", "soda"), ("state", "=", "done"),
                               ("date", ">=", today - timedelta(days=60))], order="date desc, id desc")
        month = Issue.search([("kind", "=", "soda"), ("state", "=", "done"), ("date", ">=", today.replace(day=1))])
        loc = self._soda_location()
        soda = []
        for p in Issue._craf_chem_products("soda"):
            soda.append({"id": p.id, "name": p.name, "code": p.default_code or "", "uom": self._H._uom(p),
                         "avail": round(p.with_context(location=loc.id).qty_available, 2) if loc else 0.0,
                         "total": round(p.qty_available, 2)})
        return {
            "today": fields.Date.to_string(today),
            "matrices": rows,
            "sections": sections,
            "kpi": {"total": len(matrices), "ok": len(matrices.filtered(lambda m: m.state == "ok")),
                    "broken": len(matrices.filtered(lambda m: m.state == "broken"))},
            "gas": gas,
            "gas_moves": gas_moves,
            "soda": soda,
            "soda_location": loc.name or "",
            "soda_month": _q(sum(month.mapped("qty_total")), 2),
            "issues": [{
                "id": i.id, "name": i.name, "date_label": i.date.strftime("%d.%m.%Y"),
                "who": i.employee_id.sudo().name or "", "total": _q(i.qty_total, 2), "note": i.note or "",
                "edit": i._craf_edit_info(),
            } for i in issues],
            "can_manage": self.env.user.has_group("craf_sex.group_craf_accountant")
            or self.env.user.has_group("base.group_system"),
        }

    @api.model
    def nav_counts(self):
        """Pastki panel belgilari: yaroqsiz matritsalar, bo'sh yoki kam qolgan ballonlar."""
        self._check()
        low = self.env["craf.gaz.ballon"].search_count([("type_id", "in", self._gas_types().ids),
                                                        ("state", "in", ("empty", "low"))])
        return {"matritsa": self.env["craf.matrix"].search_count([("state", "=", "broken")]), "gaz": low}

    @api.model
    def form_options(self):
        self._check()
        return {
            "today": fields.Date.to_string(fields.Date.context_today(self)),
            "sections": [{"id": s.id, "name": s.display_name}
                         for s in self.env["craf.profile.section"].search([], order="name")],
            "employees": [{"id": e.id, "name": e.name} for e in self.env["hr.employee"].sudo().search([], order="name")],
            "my_employee": self.env.user.employee_id.id or False,
        }

    # ------------------------------------------------------------------ matritsa
    @api.model
    def matrix_save(self, vals):
        self._check()
        Matrix = self.env["craf.matrix"]
        name = (vals.get("name") or "").strip()
        section = int(vals.get("section_id") or 0)
        if not name or not section:
            raise UserError("Matritsa raqami va profilini (kesim) tanlang.")
        data = {"name": name, "section_id": section, "note": (vals.get("note") or "").strip() or False}
        # rasm: yangi yuklangan (base64, sahifada kichraytirilgan) yoki o'chirildi
        if vals.get("image"):
            data["image_1920"] = vals["image"]
        elif vals.get("image_clear"):
            data["image_1920"] = False
        rec = Matrix.browse(int(vals["id"])).exists() if vals.get("id") else Matrix
        if vals.get("id") and not rec:
            raise UserError("Matritsa topilmadi (o'chirilgan bo'lishi mumkin).")
        if Matrix.search_count([("name", "=", name), ("id", "!=", rec.id or 0)]):
            raise UserError("«%s» raqamli matritsa allaqachon bor." % name)
        if rec:
            # o'zi kiritganini 24 soat ichida (xodim) yoki rahbar; holatni (yaroqli / yaroqsiz) hamma vaqt belgilaydi
            rec._craf_check_edit()
            before = rec._craf_edit_snapshot()
            rec.write(data)
            extra = ["Rasm: yangilandi"] if vals.get("image") else (["Rasm: o'chirildi"] if vals.get("image_clear") else [])
            rec._craf_log_edit(before, extra=extra)
        else:
            rec = Matrix.create(data)
        return {"id": rec.id, "name": rec.name}

    @api.model
    def matrix_load(self, matrix_id):
        """Matritsa formasi: tahrirlash muddati va tahrirlar tarixi."""
        self._check()
        rec = self.env["craf.matrix"].browse(int(matrix_id)).exists()
        if not rec:
            raise UserError("Matritsa topilmadi.")
        return {"edit": rec._craf_edit_info(), "history": rec._craf_edit_history()}

    @api.model
    def matrix_state(self, matrix_id, state, note=False):
        self._check()
        rec = self.env["craf.matrix"].browse(int(matrix_id)).exists()
        if not rec:
            raise UserError("Matritsa topilmadi.")
        if state == "broken":
            rec.action_mark_broken((note or "").strip() or False)
        else:
            rec.action_mark_ok()
        return {"id": rec.id, "state": rec.state}

    # ------------------------------------------------------------------ gaz
    @api.model
    def gaz_use(self, ballon_id, qty, note=False):
        """Ballondan sarf (faqat Ammiak va Azot)."""
        self._check()
        ballon = self.env["craf.gaz.ballon"].browse(int(ballon_id)).exists()
        if not ballon or ballon.type_id not in self._gas_types():
            raise UserError("Ballon topilmadi.")
        amount = self._num(qty, "Sarf")
        if amount <= EPS:
            raise UserError("Sarf miqdorini yozing.")
        self.env["craf.gaz.move"].create({"ballon_id": ballon.id, "kind": "use", "qty": amount,
                                          "note": (note or "").strip() or False})
        return {"ballon": ballon.name, "qty": _q(amount, 2), "left": _q(ballon.qty, 2)}

    def _gas_move(self, move_id):
        mv = self.env["craf.gaz.move"].browse(int(move_id)).exists()
        if not mv or mv.kind != "use" or mv.type_id not in self._gas_types():
            raise UserError("Gaz sarfi topilmadi (o'chirilgan bo'lishi mumkin).")
        mv._craf_check_edit()
        return mv

    @api.model
    def gaz_edit(self, move_id, qty, note=False):
        """Gaz sarfini tuzatish (24 soat ichida yoki rahbar): ballon qoldig'i qayta hisoblanadi."""
        self._check()
        mv = self._gas_move(move_id)
        amount = self._num(qty, "Sarf")
        if amount <= EPS:
            raise UserError("Sarf miqdorini yozing (o'chirish uchun «O'chirish» tugmasi).")
        before = mv._craf_edit_snapshot()
        mv.craf_change(qty=amount, note=(note or "").strip())
        mv._craf_log_edit(before)
        return {"ballon": mv.ballon_id.name, "qty": _q(amount, 2), "left": _q(mv.ballon_id.qty, 2)}

    @api.model
    def gaz_delete(self, move_id):
        """Gaz sarfini o'chirish (24 soat ichida yoki rahbar): miqdor ballonga qaytadi."""
        self._check()
        mv = self._gas_move(move_id)
        ballon = mv.ballon_id
        mv._craf_log_edit(mv._craf_edit_snapshot(), kind="cancel")
        mv.craf_change(remove=True)
        return {"ballon": ballon.name, "left": _q(ballon.qty, 2)}

    # ------------------------------------------------------------------ kaustik soda
    @api.model
    def soda_load(self, issue_id):
        self._check()
        return self.env["craf.sex"]._issue_load(("soda",), issue_id)

    @api.model
    def soda_cancel(self, issue_id):
        """Kaustik soda olishni o'chirish (24 soat ichida yoki rahbar): miqdor omborga qaytadi."""
        self._check()
        return self.env["craf.sex"]._issue_cancel(("soda",), issue_id)

    @api.model
    def soda_save(self, vals):
        """Ombordan olingan kaustik soda: yoziladi va shu zahoti ombordan sarfga yechiladi (id bo'lsa — tahrir)."""
        self._check()
        return self.env["craf.sex"]._issue_save("soda", vals)
