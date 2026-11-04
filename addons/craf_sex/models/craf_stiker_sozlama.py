"""Stiker sozlamalari sahifasi (telefon birinchi): stiker qoidalari (rang / profil → qalinlik, logo), profil
normalari (kenglik × tomon), stiker turlari, logolar va «Tekshirish» (qaysi stiker necha metr ketadi).

Ruxsat model darajasida (ir.model.access): sex ishchisi (bo'yash xodimi) — faqat o'qiydi; omborchi, direktor va
administrator — to'liq CRUD. Shaxsiy ilovali boshqa xodimlar (kimyo, matritsa) bu sahifani ochmaydi.
"""
from odoo import api, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.craf_production.models.craf_production_mixin import EPS, fmt
from odoo.addons.craf_stiker.models.craf_sticker import ADHESION

KINDS = {
    "choice": "craf.sticker.choice",
    "norm": "craf.sticker.rule",
    "sticker": "craf.sticker",
    "logo": "craf.sticker.logo",
}
STANDARD_WIDTHS = (40, 52, 68)


def _q(value, digits=1):
    value = value or 0.0
    return fmt(value, 0) if abs(value - round(value)) < 1e-9 else fmt(value, digits)


class CrafStikerSozlama(models.AbstractModel):
    _name = "craf.stiker.sozlama"
    _description = "Craf stiker sozlamalari sahifasi"

    # ------------------------------------------------------------------ yordamchi
    def _check(self):
        if self.env.su:
            return
        user = self.env.user
        own = user._craf_own_app()
        if user.share or (own and own != "boyash"):
            raise AccessError("«Stiker sozlamalari» sahifasiga ruxsatingiz yo'q. Rolingizni direktordan so'rang.")

    def _model(self, kind):
        if kind not in KINDS:
            raise UserError("Noma'lum bo'lim: %s" % kind)
        return self.env[KINDS[kind]].with_context(active_test=False)

    def _can_edit(self):
        return all(self.env[model].has_access("write") and self.env[model].has_access("create")
                   for model in KINDS.values())

    @staticmethod
    def _int(value, label, positive=False):
        try:
            number = int(float(str(value if value not in (None, False) else "").replace(",", ".").strip() or 0))
        except ValueError as err:
            raise UserError("%s: raqam bilan yozing." % label) from err
        if positive and number <= 0:
            raise UserError("%s: musbat son yozing." % label)
        return number

    @staticmethod
    def _float(value, label, positive=False):
        try:
            number = float(str(value if value not in (None, False) else "").replace(" ", "").replace(",", ".") or 0)
        except ValueError as err:
            raise UserError("%s: raqam bilan yozing." % label) from err
        if positive and number <= EPS:
            raise UserError("%s: musbat son yozing." % label)
        return number

    @staticmethod
    def _id(value):
        return int(value) if value not in (None, False, "", 0, "0") else False

    # ------------------------------------------------------------------ o'qish
    @api.model
    def get_data(self):
        self._check()
        labels = dict(ADHESION)
        choices = self._model("choice").search([])
        norms = self._model("norm").search([])
        stickers = self._model("sticker").search([])
        logos = self._model("logo").search([])
        used = {product.id for product, _count in self.env["stock.move"].sudo()._read_group(
            [("product_id", "in", stickers.product_id.ids)], ["product_id"], ["__count"])}
        lined = {sticker.id for sticker, _count in self.env["craf.paint.sticker.line"].sudo()._read_group(
            [("sticker_id", "in", stickers.ids)], ["sticker_id"], ["__count"])}
        type_count = {}
        for st in stickers:
            type_count[st.logo_id.id] = type_count.get(st.logo_id.id, 0) + 1
        default_logo = self.env["craf.paint.batch"]._craf_default_sticker_logo()
        widths = sorted(set(STANDARD_WIDTHS) | set(stickers.mapped("width_mm")) | set(norms.mapped("width_mm")))
        return {
            "can_edit": self._can_edit(),
            "adhesions": [{"key": k, "label": v} for k, v in ADHESION],
            "widths": widths,
            "default_logo": {"id": default_logo.id or False, "name": default_logo.name or ""},
            "colors": [{"id": c.id, "name": c.name}
                       for c in self.env["craf.color"].search([("is_painted", "=", True)], order="sequence, name")],
            "sections": [{"id": s.id, "name": s.display_name}
                         for s in self.env["craf.profile.section"].search([], order="name")],
            "logos": [{"id": l.id, "name": l.name, "sequence": l.sequence, "active": l.active,
                       "count": type_count.get(l.id, 0)} for l in logos],
            "choices": [{
                "id": c.id, "sequence": c.sequence, "active": c.active,
                "color_ids": c.color_ids.ids, "colors": c.color_ids.mapped("name"),
                "section_ids": c.section_ids.ids, "sections": c.section_ids.mapped("display_name"),
                "adhesion": c.adhesion or "", "adhesion_label": labels.get(c.adhesion, ""),
                "logo_id": c.logo_id.id or False, "logo": c.logo_id.name or "",
                "note": c.note or "", "summary": c.summary,
            } for c in choices],
            "norms": [{
                "id": n.id, "section_id": n.section_id.id, "section": n.section_id.display_name,
                "width": n.width_mm, "sides": int(n.sides), "sticker_id": n.sticker_id.id or False,
                "sticker": n.sticker_id.name or "", "note": n.note or "",
            } for n in norms],
            "stickers": [{
                "id": s.id, "name": s.name, "logo_id": s.logo_id.id, "logo": s.logo_id.name or "",
                "adhesion": s.adhesion, "adhesion_label": labels.get(s.adhesion, ""), "width": s.width_mm,
                "micron": s.micron or 0, "roll": s.roll_length_m, "min_rolls": round(s.min_rolls or 0.0, 1),
                "qty_rolls": round(s.qty_rolls, 1) if s.active else 0.0, "active": s.active, "note": s.note or "",
                "locked": s.product_id.id in used or s.id in lined,
            } for s in stickers],
        }

    @api.model
    def summary(self):
        """Bo'yash sahifasi (Materiallar) uchun qisqa ko'rinish: faol qoidalar va sonlar."""
        self._check()
        choices = self.env["craf.sticker.choice"].search([])
        return {
            "choices": choices.mapped("summary"),
            "norms": self.env["craf.sticker.rule"].search_count([]),
            "sections": len(self.env["craf.sticker.rule"].search([]).section_id),
            "types": self.env["craf.sticker"].search_count([]),
            "can_edit": self._can_edit(),
        }

    # ------------------------------------------------------------------ yozish
    def _vals_choice(self, vals):
        data = {
            "color_ids": [(6, 0, [int(i) for i in vals.get("color_ids") or []])],
            "section_ids": [(6, 0, [int(i) for i in vals.get("section_ids") or []])],
            "adhesion": vals.get("adhesion") or False,
            "logo_id": self._id(vals.get("logo_id")),
            "sequence": self._int(vals.get("sequence") or 10, "Tartib"),
            "note": (vals.get("note") or "").strip() or False,
            "active": bool(vals.get("active", True)),
        }
        if data["adhesion"] and data["adhesion"] not in dict(ADHESION):
            raise UserError("Noma'lum qalinlik: %s" % data["adhesion"])
        return data

    def _vals_norm(self, vals):
        section = self._id(vals.get("section_id"))
        if not section:
            raise UserError("Profilni (kesim) tanlang.")
        sides = str(vals.get("sides") or "1")
        if sides not in ("1", "2"):
            raise UserError("Tomonlar soni 1 yoki 2 bo'ladi.")
        return {
            "section_id": section,
            "width_mm": self._int(vals.get("width"), "Kenglik", positive=True),
            "sides": sides,
            "sticker_id": self._id(vals.get("sticker_id")),
            "note": (vals.get("note") or "").strip() or False,
        }

    def _vals_sticker(self, vals):
        logo = self._id(vals.get("logo_id"))
        if not logo:
            raise UserError("Logoni tanlang.")
        adhesion = vals.get("adhesion") or "medium"
        if adhesion not in dict(ADHESION):
            raise UserError("Noma'lum qalinlik: %s" % adhesion)
        return {
            "logo_id": logo,
            "adhesion": adhesion,
            "width_mm": self._int(vals.get("width"), "Kenglik", positive=True),
            "micron": self._int(vals.get("micron"), "Qalinlik, mic"),
            "roll_length_m": self._float(vals.get("roll"), "Rulon uzunligi", positive=True),
            "note": (vals.get("note") or "").strip() or False,
            "active": bool(vals.get("active", True)),
        }

    def _vals_logo(self, vals):
        name = (vals.get("name") or "").strip()
        if not name:
            raise UserError("Logo nomini yozing.")
        return {
            "name": name,
            "sequence": self._int(vals.get("sequence") or 10, "Tartib"),
            "active": bool(vals.get("active", True)),
        }

    def _check_unique(self, kind, rec, data):
        """Bazadagi takrorlanmaslik shartlarini oldindan tekshiradi — tushunarli xabar bilan (arxivdagilar ham)."""
        Model = self._model(kind)
        labels = dict(ADHESION)
        if kind == "norm":
            domain = [("section_id", "=", data["section_id"]), ("width_mm", "=", data["width_mm"])]
            message = "Bu profil uchun %s mm norma allaqachon bor — o'shani tahrirlang." % data["width_mm"]
        elif kind == "sticker":
            domain = [("logo_id", "=", data["logo_id"]), ("adhesion", "=", data["adhesion"]),
                      ("width_mm", "=", data["width_mm"])]
            message = "Bunday stiker turi allaqachon bor (%s, %s mm) — o'shani tahrirlang yoki arxivdan qaytaring." % (
                labels[data["adhesion"]], data["width_mm"])
        elif kind == "logo":
            domain = [("name", "=ilike", data["name"])]
            message = "«%s» logosi allaqachon bor (arxivda bo'lishi mumkin)." % data["name"]
        else:
            return
        if Model.search_count(domain + [("id", "!=", rec.id or 0)]):
            raise UserError(message)

    @api.model
    def save(self, kind, vals):
        """Yaratish yoki o'zgartirish — ruxsat model darajasida tekshiriladi (sex ishchisi yoza olmaydi)."""
        self._check()
        Model = self._model(kind)
        rec = Model.browse(int(vals["id"])).exists() if vals.get("id") else Model
        if vals.get("id") and not rec:
            raise UserError("Yozuv topilmadi (o'chirilgan bo'lishi mumkin).")
        data = getattr(self, "_vals_%s" % kind)(vals)
        self._check_unique(kind, rec, data)
        if rec:
            rec.write(data)
        else:
            rec = Model.create(data)
        if kind == "sticker" and vals.get("min_rolls") not in (None, ""):
            rec.min_rolls = self._float(vals.get("min_rolls"), "Minimal qoldiq")
        return {"id": rec.id, "name": rec.display_name}

    @api.model
    def delete(self, kind, rec_id):
        self._check()
        rec = self._model(kind).browse(int(rec_id)).exists()
        if not rec:
            raise UserError("Yozuv topilmadi (o'chirilgan bo'lishi mumkin).")
        if kind == "logo":
            if self._model("sticker").search_count([("logo_id", "=", rec.id)]):
                raise UserError("«%s» logoli stiker turlari bor — o'chirib bo'lmaydi. Logoni arxivlang." % rec.name)
            if self._model("choice").search_count([("logo_id", "=", rec.id)]):
                raise UserError("«%s» logo stiker qoidasida ishlatilgan — avval qoidani o'zgartiring." % rec.name)
        if kind == "sticker" and self.env["craf.paint.sticker.line"].sudo().search_count([("sticker_id", "=", rec.id)]):
            raise UserError("«%s» bo'yash smenalarida ishlatilgan — o'chirib bo'lmaydi. Arxivlang." % rec.name)
        name = rec.display_name
        rec.unlink()
        return {"name": name}

    # ------------------------------------------------------------------ tekshirish
    @api.model
    def preview(self, vals):
        """Rang, profil va uzunlik bo'yicha qaysi stiker necha metr ketadi — bo'yash smenasi bilan bir xil hisob."""
        self._check()
        color = self.env["craf.color"].browse(self._id(vals.get("color_id")) or 0).exists()
        section = self.env["craf.profile.section"].browse(self._id(vals.get("section_id")) or 0).exists()
        if not color or not section:
            raise UserError("Rang va profilni tanlang.")
        length = self._float(vals.get("length") or 6, "Uzunlik", positive=True)
        pcs = self._int(vals.get("pcs") or 1, "Dona", positive=True)
        Logo = self.env["craf.sticker.logo"]
        default_logo = Logo.browse(self._id(vals.get("logo_id")) or 0).exists() \
            or self.env["craf.paint.batch"]._craf_default_sticker_logo()
        labels = dict(ADHESION)
        items = self.env["craf.sticker.rule"]._craf_stickers_for(section, color, default_logo)
        lines, total = [], 0.0
        for it in items:
            meters = pcs * length * it["sides"]
            sticker = it["sticker"]
            total += meters
            lines.append({
                "width": it["width"], "sides": it["sides"], "meters": _q(meters, 1),
                "sticker": sticker.name or "", "explicit": it["explicit"],
                "rolls": _q(meters / sticker.roll_length_m, 3) if sticker and sticker.roll_length_m else "",
                "missing": "" if sticker else "%s %s %s mm — bunday stiker turi yo'q" % (
                    it["logo"].name or "logo tanlanmagan", labels[it["adhesion"]].split(" ")[0], it["width"]),
            })
        adhesion_rule, logo_rule = self.env["craf.sticker.choice"]._craf_match(section, color)
        series = Logo._craf_for_section(section)
        logo = logo_rule.logo_id or series or default_logo
        why = [
            "Qalinlik: %s — %s" % (labels[adhesion_rule.adhesion or "medium"],
                                   ("qoida: %s" % adhesion_rule.summary) if adhesion_rule else "standart (qoida yo'q)"),
            "Logo: %s — %s" % (logo.name or "—", ("qoida: %s" % logo_rule.summary) if logo_rule else (
                "kesim seriyasi" if series else "smena logosi")),
        ]
        if any(it["explicit"] for it in items):
            why.append("Normada aniq stiker tanlangan kenglik — qoidadan qat'i nazar o'sha stiker.")
        return {
            "lines": lines, "why": why, "total": _q(total, 1), "no_norm": not items,
            "title": "%s · %s · %s m × %s dona" % (color.name, section.display_name, _q(length, 1), pcs),
        }
