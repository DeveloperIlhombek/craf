"""Yuklovchi «Berildi» bosgan har bir yuklash (reys) — va uni tahrirlash (2026-11-09 qarori).

Yuklovchi o'zi bergan yuklashni «Berildi» dan keyin 4 soat ichida tahrirlaydi: har mahsulotdan qancha berilgani
(kam yoki ko'p) va mashina raqami. Sotuv rahbari / administrator (craf_sex o'rnatilgan bo'lsa omborchi va direktor
ham) — har doim. Tahrir bitta tranzaksiyada:
  * kamaydi  → farq mijozdan o'sha joyga qaytariladi (kirim, to_refund) — hisob-faktura bo'lsa qaytarish fakturasi;
               buyurtmada qolgan (navbatdagi) qism bo'lsa, farq unga qo'shiladi (keyin yuklanadi);
  * ko'paydi → farq o'sha joydan qo'shimcha beriladi (chiqim) — navbatdagi qolgan qismdan ayriladi; hisob-faktura.
Har tahrir — yuklash tarixida (edit_history), buyurtma chatterida va (craf_sex) «Tahrirlash jurnali»da.
"""
import json
from datetime import timedelta

from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError

from .sale_order_line import packs_text

EPS = 1e-6
TRIP_EDIT_HOURS = 4


class CrafLoadTrip(models.Model):
    _name = "craf.load.trip"
    _description = "Yuklash (berilgan reys)"
    _order = "date desc, id desc"

    name = fields.Char("Yuklash", compute="_compute_name", store=True)
    order_id = fields.Many2one("sale.order", "Buyurtma", required=True, index=True, ondelete="cascade",
                               readonly=True)
    partner_id = fields.Many2one(related="order_id.partner_id", string="Mijoz", store=True)
    user_id = fields.Many2one("res.users", "Yuklovchi", required=True, index=True, readonly=True,
                              default=lambda s: s.env.user)
    date = fields.Datetime("Berildi", required=True, index=True, readonly=True, default=fields.Datetime.now)
    truck = fields.Char("Mashina", readonly=True)
    move_ids = fields.Many2many("stock.move", "craf_load_trip_move_rel", "trip_id", "move_id",
                                string="Berilgan harakatlar", readonly=True)
    edit_move_ids = fields.Many2many("stock.move", "craf_load_trip_edit_move_rel", "trip_id", "move_id",
                                     string="Tahrir harakatlari", readonly=True,
                                     help="Tahrirda yozilgan qo'shimcha chiqim (ko'p) va qaytarish (kam) harakatlari.")
    photo_ids = fields.Many2many("ir.attachment", "craf_load_trip_photo_rel", "trip_id", "attachment_id",
                                 string="Rasmlar", readonly=True)
    edit_count = fields.Integer("Tahrirlar soni", readonly=True)
    edit_history = fields.Text("Tahrirlar tarixi", readonly=True, default="[]",
                               help="JSON: [{date, who, manager, changes: [..]}]")

    @api.depends("order_id.name", "date")
    def _compute_name(self):
        for trip in self:
            local = self.env["craf.sotuv"]._utc_to_local_str(trip.date, "%d.%m %H:%M") if trip.date else ""
            trip.name = "%s · %s" % (trip.order_id.name or "", local)

    # ------------------------------------------------------------------ ruxsat
    def _craf_trip_manager_groups(self):
        return ["sales_team.group_sale_manager", "base.group_system"]

    def _craf_trip_is_manager(self):
        user = self.env.user
        return any(user.has_group(g) for g in self._craf_trip_manager_groups())

    def _craf_trip_edit_info(self):
        """{can, manager, left, left_short, until, reason}"""
        self.ensure_one()
        S = self.env["craf.sotuv"]
        info = {"can": False, "manager": False, "left": "", "left_short": "", "until": "", "reason": ""}
        if self._craf_trip_is_manager():
            info.update(can=True, manager=True)
            return info
        if self.user_id != self.env.user:
            info["reason"] = "Bu yuklashni %s bergan — tahrirlash uchun sotuv rahbariga murojaat qiling." % (
                self.user_id.name or "boshqa xodim")
            return info
        deadline = self.date + timedelta(hours=TRIP_EDIT_HOURS)
        info["until"] = S._utc_to_local_str(deadline, "%d.%m %H:%M")
        seconds = (deadline - fields.Datetime.now()).total_seconds()
        if seconds <= 0:
            info["reason"] = ("Berilganiga %d soatdan oshdi (%s gacha edi) — endi faqat sotuv rahbari tahrirlaydi."
                              % (TRIP_EDIT_HOURS, info["until"]))
            return info
        minutes = max(int(seconds // 60), 1)
        hours, mins = divmod(minutes, 60)
        info["can"] = True
        info["left"] = ("%d soat %d daqiqa" % (hours, mins)) if hours else "%d daqiqa" % mins
        info["left_short"] = ("%d soat" % hours) if hours else "%d daq" % mins
        return info

    def _craf_trip_check_edit(self):
        info = self._craf_trip_edit_info()
        if not info["can"]:
            raise AccessError(info["reason"])
        return info

    # ------------------------------------------------------------------ qatorlar
    def _craf_trip_qty(self):
        """{(sale.order.line, joy): dona} — tahrirlar bilan birga hozir shu yuklashda berilgani."""
        self.ensure_one()
        res = {}
        for move in (self.move_ids | self.edit_move_ids).filtered(lambda m: m.state == "done" and m.sale_line_id):
            qty = move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
            if move.location_dest_id.usage == "customer":
                key, sign = (move.sale_line_id, move.location_id), 1
            elif move.location_id.usage == "customer":
                key, sign = (move.sale_line_id, move.location_dest_id), -1
            else:
                continue
            res[key] = res.get(key, 0.0) + sign * qty
        return res

    def _craf_trip_lines(self):
        self.ensure_one()
        lines = []
        for (sl, loc), qty in sorted(self._craf_trip_qty().items(),
                                     key=lambda kv: (kv[0][0].sequence, kv[0][0].id, kv[0][1].id)):
            per = sl.product_id.craf_pcs_per_pack
            lines.append({
                "key": "%s-%s" % (sl.id, loc.id),
                "line_id": sl.id,
                "location_id": loc.id,
                "location": loc._craf_sale_label(),
                "product": self.env["craf.sotuv"]._product_info(sl.product_id),
                "qty": qty,
                "qty_text": packs_text(max(qty, 0), per),
                "ordered": sl.product_uom_qty,
                "ordered_text": packs_text(sl.product_uom_qty, per),
            })
        return lines

    def _craf_trip_snapshot(self):
        self.ensure_one()
        res = {"Mashina": self.truck or ""}
        for (sl, loc), qty in self._craf_trip_qty().items():
            res["%s (%s)" % (sl.product_id.display_name, loc._craf_sale_label())] = packs_text(
                max(qty, 0), sl.product_id.craf_pcs_per_pack)
        return res

    def _craf_trip_history(self):
        self.ensure_one()
        try:
            return json.loads(self.edit_history or "[]")
        except ValueError:
            return []

    # ------------------------------------------------------------------ tahrir
    def _craf_trip_edit(self, quantities, truck=None):
        """quantities: {(sale.order.line, joy): yangi dona}; truck — yangi mashina raqami (None — o'zgarmaydi)."""
        self.ensure_one()
        info = self._craf_trip_check_edit()
        so = self.order_id.sudo()
        if so.state != "sale":
            raise UserError("%s: buyurtma tasdiqlangan holatda emas (%s)." % (so.name, so.state))
        before = self._craf_trip_snapshot()
        current = self._craf_trip_qty()
        less, more = {}, {}
        for key, new in quantities.items():
            sl, loc = key
            if key not in current:
                raise UserError("Bu qator shu yuklashda yo'q — ro'yxatni yangilang.")
            if new < 0:
                raise UserError("Manfiy miqdor bo'lmaydi.")
            diff = new - current[key]
            if diff < -EPS:
                less[key] = -diff
            elif diff > EPS:
                more[key] = diff
        trip = self.sudo()
        if less:
            trip._craf_trip_less(so, less)
        if more:
            trip._craf_trip_more(so, more)
        if truck is not None:
            truck = (truck or "").strip().upper() or False
            if truck != (self.truck or False):
                if not truck:
                    raise UserError("Mashina raqami bo'sh bo'lmasin.")
                trip.truck = truck
                if (so.craf_truck or False) == (before.get("Mashina") or False):
                    so.craf_truck = truck
        after = self._craf_trip_snapshot()
        changes = []
        for key in list(before) + [k for k in after if k not in before]:
            old, new = before.get(key) or "", after.get(key) or ""
            if old != new:
                changes.append("%s: %s → %s" % (key, old or "—", new or "—"))
        if not changes:
            return False
        if less or more:
            so._craf_trip_sync_state()
        S = self.env["craf.sotuv"]
        history = self._craf_trip_history()
        history.insert(0, {"date": S._utc_to_local_str(fields.Datetime.now(), "%d.%m.%Y %H:%M"),
                           "who": self.env.user.name, "manager": info["manager"], "changes": changes})
        trip.write({"edit_history": json.dumps(history, ensure_ascii=False), "edit_count": self.edit_count + 1})
        title = "Berilgan yuklash tahrirlandi (%s)" % (
            "rahbar" if info["manager"] else "%d soat ichida" % TRIP_EDIT_HOURS)
        so.message_post(body=Markup("<br/>").join(
            [Markup("<b>%s</b> — %s") % (title, self.name)] + changes))
        self._craf_trip_log(before, changes, info["manager"])
        so._craf_notify("edit", "Berilgan yuklash tahrirlandi",
                        "%s · %s — %s: %s" % (so.name, so.partner_id.name, self.env.user.name, "; ".join(changes)),
                        users=so.user_id | so.create_uid | self.user_id, ntype="warning")
        return True

    def _craf_trip_log(self, before, changes, manager):
        """craf_sex «Tahrirlash jurnali»ga yozadi."""
        return True

    def _craf_trip_less(self, so, less):
        """Kam berildi: farq mijozdan o'sha joyga qaytadi; navbatdagi qolgan qism bo'lsa — unga qo'shiladi."""
        customer = self.env.ref("stock.stock_location_customers")
        by_loc = {}
        for (sl, loc), qty in less.items():
            by_loc.setdefault(loc, []).append((sl, qty))
        for loc, rows in by_loc.items():
            warehouse = loc.warehouse_id or so.warehouse_id
            moves = []
            for sl, qty in rows:
                origin = (self.move_ids | self.edit_move_ids).filtered(
                    lambda m: m.sale_line_id == sl and m.state == "done" and m.location_id == loc
                    and m.location_dest_id.usage == "customer")[-1:]
                moves.append(Command.create({
                    "product_id": sl.product_id.id,
                    "product_uom_qty": qty,
                    "product_uom": sl.product_id.uom_id.id,
                    "location_id": customer.id,
                    "location_dest_id": loc.id,
                    "sale_line_id": sl.id,
                    "to_refund": True,
                    "origin_returned_move_id": origin.id or False,
                    "partner_id": so.partner_shipping_id.id,
                }))
            picking = self.env["stock.picking"].create({
                "picking_type_id": warehouse.in_type_id.id,
                "location_id": customer.id,
                "location_dest_id": loc.id,
                "partner_id": so.partner_shipping_id.id,
                "origin": "Tahrir (kam) %s" % so.name,
                "move_ids": moves,
            })
            self._craf_trip_validate(picking)
            self.edit_move_ids = [Command.link(m.id) for m in picking.move_ids]
            so._craf_after_return(picking)
        # navbatdagi qolgan qism bo'lsa — kam berilgani unga qo'shiladi (keyin yuklanadi)
        open_moves = so._craf_open_pickings().move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        for (sl, _loc), qty in less.items():
            move = open_moves.filtered(lambda m: m.sale_line_id == sl)[:1]
            if move:
                add = move.product_id.uom_id._compute_quantity(qty, move.product_uom)
                move.product_uom_qty += add

    def _craf_trip_more(self, so, more):
        """Ko'p berildi: farq o'sha joydan qo'shimcha chiqim; navbatdagi qolgan qismdan ayriladi."""
        customer = self.env.ref("stock.stock_location_customers")
        if not so.company_id.craf_sale_allow_negative:
            short = []
            for (sl, loc), qty in more.items():
                product = sl.product_id
                if not product.is_storable:
                    continue
                have = product.with_context(location=loc.id).qty_available
                if product.uom_id.compare(qty, have) > 0:
                    per = product.craf_pcs_per_pack
                    short.append("• %s — %s: qo'shimcha %s, omborda %s" % (
                        product.display_name, loc._craf_sale_label(), packs_text(qty, per),
                        packs_text(max(have, 0), per)))
            if short:
                raise UserError("Qoldiq yetmaydi:\n%s" % "\n".join(short))
        # navbatdagi qolgan qismdan ayiramiz (o'sha mahsulot ikkinchi marta berilmasin)
        open_moves = so._craf_open_pickings().move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
        for (sl, _loc), qty in more.items():
            rest = qty
            for move in open_moves.filtered(lambda m: m.sale_line_id == sl):
                if rest <= EPS:
                    break
                have = move.product_uom._compute_quantity(move.product_uom_qty, move.product_id.uom_id)
                take = min(have, rest)
                rest -= take
                if have - take <= EPS:
                    self.env["craf.load.alloc"].sudo().search([("move_id", "=", move.id)]).unlink()
                    move._action_cancel()
                else:
                    move._do_unreserve()
                    move.product_uom_qty = move.product_id.uom_id._compute_quantity(have - take, move.product_uom)
                    move._action_assign()
        by_loc = {}
        for (sl, loc), qty in more.items():
            by_loc.setdefault(loc, []).append((sl, qty))
        for loc, rows in by_loc.items():
            warehouse = loc.warehouse_id or so.warehouse_id
            picking = self.env["stock.picking"].create({
                "picking_type_id": warehouse.out_type_id.id,
                "location_id": loc.id,
                "location_dest_id": customer.id,
                "partner_id": so.partner_shipping_id.id,
                "origin": "Tahrir (ko'p) %s" % so.name,
                "move_ids": [Command.create({
                    "product_id": sl.product_id.id,
                    "product_uom_qty": qty,
                    "product_uom": sl.product_id.uom_id.id,
                    "location_id": loc.id,
                    "location_dest_id": customer.id,
                    "sale_line_id": sl.id,
                    "partner_id": so.partner_shipping_id.id,
                }) for sl, qty in rows],
            })
            self._craf_trip_validate(picking)
            self.edit_move_ids = [Command.link(m.id) for m in picking.move_ids]
        so._craf_auto_invoice()

    def _craf_trip_validate(self, picking):
        picking.action_confirm()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking.with_context(skip_backorder=True, skip_sms=True,
                             picking_ids_not_to_backorder=picking.ids).button_validate()
        if picking.state != "done":
            raise UserError("%s bajarilmadi (%s)." % (picking.name, picking.state))


class SaleOrder(models.Model):
    _inherit = "sale.order"

    craf_trip_ids = fields.One2many("craf.load.trip", "order_id", string="Yuklashlar", readonly=True)

    def _craf_auto_invoice(self):
        """Hisob-faktura — craf_pul moduli (o'rnatilmagan bo'lsa hech narsa qilmaydi)."""
        return True

    def _craf_trip_sync_state(self):
        """Tahrirdan keyin: qolgan qism tugagan bo'lsa — «Berildi», paydo bo'lgan bo'lsa — navbatda."""
        self.ensure_one()
        has_open = bool(self._craf_open_pickings().move_ids.filtered(lambda m: m.state not in ("done", "cancel")))
        if has_open and self.craf_load_state == "done":
            self.craf_load_state = "queue"
        elif not has_open and self.craf_load_state in ("queue", "loading"):
            self.craf_load_state = "done"


class CrafSotuv(models.AbstractModel):
    _inherit = "craf.sotuv"

    def _given_trips(self):
        """Yuklash sahifasidagi «Berilganlar»: o'zi bergan (oxirgi 24 soat), rahbar — hammaniki."""
        Trip = self.env["craf.load.trip"].sudo()
        since = fields.Datetime.now() - timedelta(hours=24)
        domain = [("date", ">=", since), ("order_id.state", "=", "sale")]
        if not Trip._craf_trip_is_manager():
            domain.append(("user_id", "=", self.env.user.id))
        return Trip.search(domain, limit=40)

    def _trip_card(self, trip):
        info = trip._craf_trip_edit_info()
        lines = trip._craf_trip_lines()
        return {
            "id": trip.id,
            "order_id": trip.order_id.id,
            "name": trip.order_id.name,
            "partner": trip.partner_id.name or "",
            "time": self._utc_to_local_str(trip.date, "%H:%M"),
            "day": self._utc_to_local_str(trip.date, "%d.%m"),
            "loader": trip.user_id.name or "",
            "is_mine": trip.user_id == self.env.user,
            "truck": trip.truck or "",
            "edit_count": trip.edit_count,
            "edit": info,
            "lines": [{"product": l["product"]["name"], "text": l["qty_text"]} for l in lines if l["qty"] > EPS],
        }

    @api.model
    def load_queue(self):
        res = super().load_queue()
        res["given"] = [self._trip_card(t) for t in self._given_trips()]
        return res

    def _load_trip(self, trip_id):
        self._check_loader()
        trip = self.env["craf.load.trip"].sudo().browse(int(trip_id or 0)).exists()
        if not trip:
            raise UserError("Yuklash topilmadi.")
        if trip.user_id != self.env.user and not trip._craf_trip_is_manager():
            raise AccessError("Bu yuklashni boshqa xodim bergan.")
        return trip

    @api.model
    def given_trip(self, trip_id):
        trip = self._load_trip(trip_id)
        card = self._trip_card(trip)
        card["lines"] = trip._craf_trip_lines()
        card["history"] = trip._craf_trip_history()
        card["photos"] = [{"id": a.id, "url": "/craf/sotuv/photo/%s" % a.id,
                           "thumb": "/craf/sotuv/photo/%s?size=256" % a.id} for a in trip.photo_ids]
        return card

    @api.model
    def given_save(self, trip_id, rows=None, truck=None):
        """rows: [{line_id, location_id, packs, extra}]"""
        trip = self._load_trip(trip_id)
        current = {(sl.id, loc.id): (sl, loc) for sl, loc in trip._craf_trip_qty()}
        quantities = {}
        for row in rows or []:
            key = current.get((int(row.get("line_id") or 0), int(row.get("location_id") or 0)))
            if not key:
                raise UserError("Bu qator shu yuklashda yo'q — ro'yxatni yangilang.")
            per = key[0].product_id.craf_pcs_per_pack
            packs, extra = int(row.get("packs") or 0), int(row.get("extra") or 0)
            if packs < 0 or extra < 0:
                raise UserError("Manfiy miqdor bo'lmaydi.")
            if packs and not per:
                raise UserError("%s: «dona / pachka» kiritilmagan — donada yozing." % key[0].product_id.display_name)
            quantities[key] = packs * per + extra
        changed = trip._craf_trip_edit(quantities, truck=truck)
        res = self.given_trip(trip.id)
        res["changed"] = changed
        return res

    @api.model
    def load_done(self, order_id, rest="backorder"):
        res = super().load_done(order_id, rest=rest)
        trip = self.env["craf.load.trip"].sudo().search(
            [("order_id", "=", int(order_id)), ("user_id", "=", self.env.user.id)], limit=1)
        res["trip_id"] = trip.id or False
        return res
