from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

UNITS = [("m3", "m³"), ("kg", "kg"), ("l", "litr")]
EPS = 1e-6


class CrafGazType(models.Model):
    _name = "craf.gaz.type"
    _description = "Gaz turi"
    _order = "sequence, name"

    name = fields.Char("Gaz", required=True)
    code = fields.Char("Formula")
    color = fields.Char("Rang", default="#3BA4E8")
    unit = fields.Selection(UNITS, "O'lchov", default="m3", required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    note = fields.Text("Izoh")
    ballon_ids = fields.One2many("craf.gaz.ballon", "type_id", "Ballonlar")


class CrafGazBallon(models.Model):
    _name = "craf.gaz.ballon"
    _description = "Gaz ballon"
    _order = "type_id, name"

    name = fields.Char("Ballon raqami", required=True)
    type_id = fields.Many2one("craf.gaz.type", "Gaz", required=True, ondelete="restrict")
    color = fields.Char(related="type_id.color")
    unit = fields.Selection(related="type_id.unit")
    capacity = fields.Float("Sig'imi", required=True, default=40.0)
    qty = fields.Float("Qoldiq", readonly=True)
    percent = fields.Float("To'lganlik, %", compute="_compute_level", store=True)
    state = fields.Selection(
        [("empty", "Bo'sh"), ("low", "Kam"), ("ok", "Bor")],
        "Holat", compute="_compute_level", store=True)
    location_id = fields.Many2one("stock.location", "Joyi", domain=[("usage", "=", "internal")])
    note = fields.Text("Izoh")
    active = fields.Boolean(default=True)
    move_ids = fields.One2many("craf.gaz.move", "ballon_id", "Harakatlar")

    _name_uniq = models.Constraint("unique(name)", "Bunday raqamli ballon bor.")

    @api.constrains("capacity")
    def _check_capacity(self):
        for b in self:
            if b.capacity <= 0:
                raise ValidationError("Sig'im 0 dan katta bo'lishi kerak.")

    @api.depends("qty", "capacity")
    def _compute_level(self):
        for b in self:
            p = (b.qty / b.capacity * 100.0) if b.capacity else 0.0
            b.percent = round(max(0.0, min(100.0, p)), 1)
            b.state = "empty" if b.qty <= EPS else ("low" if p < 20 else "ok")

    # ---------- sahifa uchun ----------
    @api.model
    def craf_get_dashboard(self):
        since = fields.Datetime.now() - timedelta(days=30)
        used = {}
        for m in self.env["craf.gaz.move"].search([("kind", "=", "use"), ("date", ">=", since)]):
            used[m.ballon_id.id] = used.get(m.ballon_id.id, 0.0) + m.qty
        unit_label = dict(UNITS)
        ballons = []
        for b in self.search([]):
            ballons.append({
                "id": b.id, "name": b.name, "type_id": b.type_id.id,
                "type_name": b.type_id.name, "formula": b.type_id.code or "",
                "color": b.color or "#3BA4E8", "unit": unit_label.get(b.unit, ""),
                "capacity": b.capacity, "qty": b.qty, "percent": b.percent,
                "state": b.state, "location_id": b.location_id.id or False,
                "location": b.location_id.name or "", "note": b.note or "",
                "used_30": round(used.get(b.id, 0.0), 2),
            })
        types = []
        for t in self.env["craf.gaz.type"].search([]):
            bs = [x for x in ballons if x["type_id"] == t.id]
            types.append({
                "id": t.id, "name": t.name, "code": t.code or "", "color": t.color or "#3BA4E8",
                "unit": t.unit, "unit_label": unit_label.get(t.unit, ""), "note": t.note or "",
                "count": len(bs), "empty": len([x for x in bs if x["state"] == "empty"]),
                "qty": round(sum(x["qty"] for x in bs), 2),
                "capacity": round(sum(x["capacity"] for x in bs), 2),
                "used_30": round(sum(x["used_30"] for x in bs), 2),
            })
        moves = [{
            "id": m.id, "ballon": m.ballon_id.name, "type_name": m.ballon_id.type_id.name,
            "color": m.ballon_id.color or "#3BA4E8", "kind": m.kind, "qty": m.qty,
            "after": m.qty_after, "date": fields.Datetime.to_string(m.date),
            "user": m.user_id.name or "", "note": m.note or "",
            "unit": unit_label.get(m.ballon_id.unit, ""),
        } for m in self.env["craf.gaz.move"].search([], limit=20)]
        locations = [{"id": l.id, "name": l.complete_name} for l in
                     self.env["stock.location"].search([("usage", "=", "internal")])]
        return {"ballons": ballons, "types": types, "moves": moves, "locations": locations}

    @api.model
    def craf_save(self, kind, vals):
        vals = dict(vals or {})
        rec_id = vals.pop("id", False)
        if kind == "type":
            data = {k: vals.get(k) for k in ("name", "code", "color", "unit", "note")}
            if not (data.get("name") or "").strip():
                raise UserError("Gaz nomini yozing.")
            T = self.env["craf.gaz.type"]
            return T.browse(rec_id).write(data) and rec_id if rec_id else T.create(data).id
        if kind == "ballon":
            data = {
                "name": (vals.get("name") or "").strip(),
                "type_id": int(vals.get("type_id") or 0) or False,
                "capacity": float(vals.get("capacity") or 0),
                "location_id": int(vals.get("location_id") or 0) or False,
                "note": vals.get("note") or "",
            }
            if not data["name"] or not data["type_id"]:
                raise UserError("Ballon raqami va gaz turini tanlang.")
            if rec_id:
                b = self.browse(rec_id)
                if data["capacity"] + EPS < b.qty:
                    raise UserError("Sig'im hozirgi qoldiqdan kichik bo'lolmaydi.")
                b.write(data)
            else:
                b = self.create(data)
                start = float(vals.get("qty") or 0)
                if start > 0:
                    self.env["craf.gaz.move"].create({
                        "ballon_id": b.id, "kind": "adjust", "qty": start,
                        "note": "Boshlang'ich qoldiq"})
            return b.id
        if kind == "move":
            m = self.env["craf.gaz.move"].create({
                "ballon_id": int(vals.get("ballon_id")), "kind": vals.get("kind") or "use",
                "qty": float(vals.get("qty") or 0), "note": vals.get("note") or "",
            })
            return m.id
        raise UserError("Noma'lum amal.")

    @api.model
    def craf_delete(self, kind, rec_id):
        if kind == "type":
            t = self.env["craf.gaz.type"].browse(rec_id)
            if t.with_context(active_test=False).ballon_ids:
                raise UserError("Bu gazda ballonlar bor — avval ularni o'chiring.")
            t.unlink()
        elif kind == "ballon":
            b = self.browse(rec_id)
            if b.move_ids:
                b.active = False  # tarix saqlanadi
            else:
                b.unlink()
        elif kind == "move":
            self.env["craf.gaz.move"].browse(rec_id).unlink()
        return True


class CrafGazMove(models.Model):
    _name = "craf.gaz.move"
    _description = "Gaz harakati"
    _order = "date desc, id desc"

    ballon_id = fields.Many2one("craf.gaz.ballon", "Ballon", required=True, ondelete="cascade")
    type_id = fields.Many2one(related="ballon_id.type_id", store=True)
    kind = fields.Selection(
        [("fill", "To'ldirish"), ("use", "Sarf"), ("adjust", "Tuzatish (sanash)")],
        "Amal", required=True, default="use")
    qty = fields.Float("Miqdor", required=True)
    qty_before = fields.Float("Oldin", readonly=True)
    qty_after = fields.Float("Keyin", readonly=True)
    date = fields.Datetime("Sana", default=fields.Datetime.now, required=True)
    user_id = fields.Many2one("res.users", "Kim", default=lambda s: s.env.user)
    note = fields.Char("Izoh")

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        for m in recs:
            b = m.ballon_id
            before = b.qty
            if m.kind != "adjust" and m.qty <= 0:
                raise UserError("Miqdor 0 dan katta bo'lishi kerak.")
            after = {"fill": before + m.qty, "use": before - m.qty}.get(m.kind, m.qty)
            if after < -EPS:
                raise UserError(f"{b.name}: ballonda {before:g} qolgan, {m.qty:g} sarflab bo'lmaydi.")
            if after > b.capacity + EPS:
                raise UserError(f"{b.name}: sig'im {b.capacity:g}, {after:g} gacha to'ldirib bo'lmaydi.")
            m.write({"qty_before": before, "qty_after": after})
            b.qty = after
        return recs

    def unlink(self):
        for m in self.sorted(lambda x: (x.date, x.id), reverse=True):
            last = self.search([("ballon_id", "=", m.ballon_id.id)], limit=1)
            if last != m:
                raise UserError("Faqat ballonning oxirgi harakatini o'chirish mumkin.")
            m.ballon_id.qty = m.qty_before
            super(CrafGazMove, m).unlink()
        return True
