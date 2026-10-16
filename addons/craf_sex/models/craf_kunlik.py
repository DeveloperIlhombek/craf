"""Hisobchi kunlik yakuni: kunlik hisobotga xom-ashyo kirimi (yetkazib beruvchidan / qaytarish) va
inventarizatsiya farqlari qo'shiladi; ombor hujjatlari va sanash hujjatlari ham 1C belgisi oladi."""
import re
from collections import OrderedDict

from odoo import api, fields, models

C1_STATES = [("new", "1C ga kiritilmagan"), ("done", "1C ga kiritildi")]


class CrafC1Mixin(models.AbstractModel):
    _name = "craf.c1.mixin"
    _description = "1C ga kiritilganlik belgisi"

    c1_state = fields.Selection(C1_STATES, string="1C", default="new", required=True, copy=False, index=True,
                                tracking=True)
    c1_date = fields.Datetime("1C ga kiritilgan vaqt", readonly=True, copy=False)
    c1_user_id = fields.Many2one("res.users", "1C ga kiritgan", readonly=True, copy=False)

    def _craf_c1_ready(self):
        """Hujjat 1C ga kiritishga tayyor (bajarilgan)."""
        self.ensure_one()
        return self.state == "done"

    def action_c1_done(self):
        self.filtered(lambda r: r._craf_c1_ready() and r.c1_state != "done").write({
            "c1_state": "done", "c1_date": fields.Datetime.now(), "c1_user_id": self.env.user.id})
        return True

    def action_c1_reset(self):
        self.write({"c1_state": "new", "c1_date": False, "c1_user_id": False})
        return True


class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = ["stock.picking", "craf.c1.mixin"]


class CrafLiteyCount(models.Model):
    _name = "craf.litey.count"
    _inherit = ["craf.litey.count", "craf.c1.mixin"]


class CrafKunlikHisobot(models.AbstractModel):
    _inherit = "craf.kunlik.hisobot"

    # ------------------------------------------------------------------ kirim
    def _supply_moves(self, start, end):
        return self.env["stock.move"].search([
            ("state", "=", "done"), ("date", ">=", start), ("date", "<", end),
            "|", "&", ("location_id.usage", "=", "supplier"), ("location_dest_id.usage", "=", "internal"),
            "&", ("location_id.usage", "=", "internal"), ("location_dest_id.usage", "=", "supplier"),
        ])

    def _supply(self, start, end):
        moves = self._supply_moves(start, end)
        came, back = OrderedDict(), OrderedDict()
        for m in moves:
            qty = m.product_uom._compute_quantity(m.quantity, m.product_id.uom_id)
            self._add(came if m.location_id.usage == "supplier" else back, m.product_id, qty)
        docs = []
        for p in moves.picking_id.sorted(lambda p: (p.date_done or p.scheduled_date, p.id)):
            is_return = p.location_dest_id.usage == "supplier"
            docs.append({
                "model": "stock.picking", "id": p.id,
                "name": " · ".join(filter(None, [p.name, p.craf_vehicle, p.partner_id.name])),
                "state": "done", "state_label": "Qaytarildi" if is_return else "Qabul qilindi", "c1": p.c1_state,
                "who": p.partner_id.name or "", "shift": "",
            })
        rows_in, rows_back = self._rows(came), self._rows(back)
        extra = []
        partners = moves.picking_id.partner_id
        if partners:
            extra.append("Yetkazib beruvchilar: %s" % ", ".join(partners.mapped("name")))
        kg = sum(r["kg"] for r in rows_in)
        if kg:
            extra.append("Jami kirim: %s kg" % f"{kg:,.0f}".replace(",", " "))
        no_partner = moves.picking_id.filtered(lambda p: not p.partner_id)
        if no_partner:
            extra.append("Yetkazib beruvchisi yozilmagan: %s ta" % len(no_partner))
        return {
            "key": "kirim", "title": "Xom-ashyo kirimi (yetkazib beruvchidan)", "model": "stock.picking",
            "action": False, "docs": docs, "used": rows_back, "made": rows_in, "waste": [], "extra": extra,
            "used_label": "Yetkazib beruvchiga qaytarildi", "made_label": "Qabul qilindi",
            "done_count": len(docs), "draft_count": 0,
        }

    # ------------------------------------------------------------------ inventarizatsiya
    def _inventory(self, day, start, end):
        moves = self.env["stock.move"].search([
            ("state", "=", "done"), ("is_inventory", "=", True), ("date", ">=", start), ("date", "<", end)])
        plus, minus = OrderedDict(), OrderedDict()
        for m in moves:
            qty = m.product_uom._compute_quantity(m.quantity, m.product_id.uom_id)
            self._add(plus if m.location_dest_id.usage == "internal" else minus, m.product_id, qty)
        Count = self.env["craf.litey.count"]
        counts = Count.search([("state", "=", "done"), "|", ("move_ids", "in", moves.ids), ("date", "=", day)],
                              order="id")
        docs = [{
            "model": "craf.litey.count", "id": c.id, "name": c.name, "state": "done", "state_label": "Bajarildi",
            "c1": c.c1_state, "who": c.user_id.name or "", "shift": "",
        } for c in counts]
        drafts = Count.search_count([("state", "=", "draft"), ("date", "=", day)])
        extra = []
        loose = moves - counts.move_ids
        if loose:
            extra.append("Hujjatsiz tuzatish (Inventarizatsiya → Fizik inventarizatsiya): %s ta harakat" % len(loose))
        return {
            "key": "sanash", "title": "Inventarizatsiya — sanash farqlari", "model": "craf.litey.count",
            "action": False, "docs": docs, "used": self._rows(minus), "made": self._rows(plus), "waste": [],
            "used_label": "Kamomad (hisobdan chiqdi)", "made_label": "Ortiqcha (hisobga kirdi)",
            "extra": extra, "done_count": len(counts), "draft_count": drafts,
        }

    # ------------------------------------------------------------------ 1C belgisi
    def _c1_records(self, day):
        """Shu kunning 1C ga kiritiladigan ombor hujjatlari: kirim/qaytarish, omborga topshirish,
        buyurtmasiz chiqimlar va sanash hujjatlari."""
        start, end = self._day_bounds(day)
        pickings = self._supply_moves(start, end).picking_id
        stock = self._to_stock(start, end)
        pickings |= self.env["stock.picking"].browse([d["id"] for d in stock["docs"]])
        if hasattr(self, "_sale_moves"):
            pickings |= self._sale_moves(start, end).filtered(lambda m: not m.sale_line_id).picking_id
        inv = self._inventory(day, start, end)
        counts = self.env["craf.litey.count"].browse([d["id"] for d in inv["docs"]])
        return pickings.filtered(lambda p: p.state == "done"), counts

    @api.model
    def get_data(self, day=None):
        data = super().get_data(day)
        day = self._parse_day(data["date"])
        start, end = self._day_bounds(day)
        deps = data["departments"]
        supply = self._supply(start, end)
        deps.insert(0, supply)
        deps.append(self._inventory(day, start, end))
        # ombor hujjatlariga 1C belgisi
        pickings, counts = self._c1_records(day)
        state = {p.id: p.c1_state for p in pickings}
        for dep in deps:
            for doc in dep["docs"]:
                if doc["model"] == "stock.picking" and doc["id"] in state:
                    doc["c1"] = state[doc["id"]]
            dep["title"] = "%s. %s" % (deps.index(dep) + 1, re.sub(r"^\d+\.\s*", "", dep["title"]))
        data["c1_new"] += len(pickings.filtered(lambda p: p.c1_state == "new")) \
            + len(counts.filtered(lambda c: c.c1_state == "new"))
        return data

    @api.model
    def action_mark_c1(self, day=None):
        count = super().action_mark_c1(day)
        pickings, counts = self._c1_records(self._parse_day(day))
        pickings, counts = pickings.filtered(lambda p: p.c1_state == "new"), counts.filtered(lambda c: c.c1_state == "new")
        pickings.action_c1_done()
        counts.action_c1_done()
        return count + len(pickings) + len(counts)
