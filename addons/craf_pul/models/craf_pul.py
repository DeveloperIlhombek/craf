"""Craf → Pul: narxlar, to'lovlar, qarzlar (telefon sahifasi uchun API)."""
import re
from collections import defaultdict
from datetime import timedelta

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError

from odoo.addons.craf_litey.models.craf_foundry_melt import parse_sum

from .account import PAY_METHODS
from .sale_order import PRICE_MIN

# (to'lov usuli, kod, nomi, turi)
JOURNALS = [
    ("naqd", "NAQD", "Naqd pul", "cash"),
    ("plastik", "PLAS", "Plastik (terminal)", "bank"),
    ("bank", "BNK1", "Bank o'tkazma", "bank"),
]
METHOD_LABEL = dict(PAY_METHODS)
KINDS = {"customer": "asset_receivable", "supplier": "liability_payable"}
LIVE_PAYMENT = ("in_process", "paid")
# namuna narxlar, 1 kg uchun (faqat narxi yo'q mahsulotlarga, direktor bosganda)
DEMO_KG = {"Bo'yalmagan": 45000, "7016 MATT": 56000, "8003 Золотой Дуб": 58000}
DEMO_KG_DEFAULT = 52000


def _money(value):
    return "{:,.0f}".format(value or 0.0).replace(",", " ")


def _short(value):
    """Qisqa summa: 14,2 mln; 950 ming."""
    v = abs(value or 0.0)
    for limit, div, unit in ((1e9, 1e9, "mlrd"), (1e6, 1e6, "mln"), (1e4, 1e3, "ming")):
        if v >= limit:
            text = ("%.1f" % (v / div)).rstrip("0").rstrip(".") if div > 1e3 else "%.0f" % (v / div)
            return "%s %s" % (text.replace(".", ","), unit)
    return _money(v)


class CrafPul(models.AbstractModel):
    _name = "craf.pul"
    _description = "Craf: pul — narx, to'lov, qarz"

    # ================================================================== rollar
    def _roles(self):
        user = self.env.user
        system = user.has_group("base.group_system")
        return {
            "accountant": system or user.has_group("craf_sex.group_craf_accountant"),
            "manager": system or user.has_group("craf_sex.group_craf_director"),
        }

    def _need(self, role="accountant"):
        if not self._roles()[role]:
            raise AccessError("Bu amal faqat %s uchun." % ("omborchi va direktor" if role == "accountant" else "direktor"))

    # ================================================================== sozlash
    def _has_journal_items(self, company):
        return bool(self.env["account.move.line"].sudo().search_count([("company_id", "=", company.id)], limit=1))

    @api.model
    def _setup(self):
        """O'rnatishda va «Sozlash» da: so'm, kassalar, soliqsiz narx, berilgan miqdor bo'yicha hisob-faktura."""
        company = self.env.company
        uzs = self.env.ref("base.UZS", raise_if_not_found=False)
        if uzs:
            # Odoo da so'm belgisi «лв» — o'zbekcha «so'm», summadan keyin
            uzs.sudo().write({"active": True, "symbol": "so'm", "position": "after"})
        if uzs and company.currency_id != uzs and not self._has_journal_items(company):
            company.sudo().currency_id = uzs
        self._setup_journals(company)
        company.sudo().write({"account_sale_tax_id": False, "account_purchase_tax_id": False,
                              # narxlar endi Pul → Narxlar dan: sotuvda narx hisoblanadi
                              "craf_sale_use_price": True})
        Tmpl = self.env["product.template"].sudo().with_context(active_test=False)
        Tmpl.search(["|", ("taxes_id", "!=", False), ("supplier_taxes_id", "!=", False)]).write(
            {"taxes_id": [Command.clear()], "supplier_taxes_id": [Command.clear()]})
        lines = self.env["sale.order.line"].sudo().search(
            [("tax_ids", "!=", False), ("invoice_status", "!=", "invoiced"), ("state", "!=", "cancel")])
        for order in lines.order_id:
            locked = order._craf_unlocked()
            lines.filtered(lambda l: l.order_id == order).write({"tax_ids": [Command.clear()]})
            if locked:
                locked.action_lock()
        Tmpl.search([("sale_ok", "=", True), ("type", "=", "consu"), ("invoice_policy", "!=", "delivery")]).write(
            {"invoice_policy": "delivery"})
        self.env["ir.default"].sudo().set("product.template", "invoice_policy", "delivery")
        return True

    def _setup_journals(self, company):
        Journal = self.env["account.journal"].sudo()
        for method, code, name, jtype in JOURNALS:
            if Journal.search_count([("company_id", "=", company.id), ("craf_pay_method", "=", method)]):
                continue
            journal = Journal.search([("company_id", "=", company.id), ("code", "=", code), ("type", "=", jtype)],
                                     limit=1)
            if not journal and method == "bank":
                journal = Journal.search([("company_id", "=", company.id), ("type", "=", "bank"),
                                          ("craf_pay_method", "=", False)], order="id", limit=1)
            if not journal:
                journal = Journal.create({"name": name, "code": code, "type": jtype, "company_id": company.id})
            journal.write({"craf_pay_method": method, "name": name})
            for code_lang in self.env["res.lang"].search([]).mapped("code"):
                journal.with_context(lang=code_lang).name = name

    @api.model
    def setup_info(self):
        company = self.env.company
        uzs = self.env.ref("base.UZS", raise_if_not_found=False)
        Move = self.env["account.move"].sudo()
        return {
            "currency": company.currency_id.name,
            "uzs": bool(uzs) and company.currency_id == uzs,
            "moves": Move.search_count([("company_id", "=", company.id)]),
            "posted": Move.search_count([("company_id", "=", company.id), ("state", "=", "posted")]),
        }

    @api.model
    def setup_run(self):
        """Direktor: sozlashni qayta tekshirish (kassalar, soliqsiz narx, sotuvda narx)."""
        self._need("manager")
        self._setup()
        return self.setup_info()

    @api.model
    def setup_switch_currency(self):
        """Kompaniya valyutasini so'mga o'tkazadi. Faqat qoralama yozuvlar bo'lsa — ular o'chiriladi."""
        self._need("manager")
        info = self.setup_info()
        if info["uzs"]:
            return info
        if info["posted"]:
            raise UserError("%s ta tasdiqlangan buxgalteriya yozuvi bor — valyutani o'zgartirib bo'lmaydi. "
                            "Ularni Hisob-faktura bo'limida bekor qilib, qoralamaga qaytaring." % info["posted"])
        company = self.env.company
        drafts = self.env["account.move"].sudo().search([("company_id", "=", company.id)])
        drafts.unlink()
        uzs = self.env.ref("base.UZS")
        uzs.sudo().active = True
        company.sudo().currency_id = uzs
        self._setup()
        return self.setup_info()

    # ================================================================== yordamchi
    def _company(self):
        return self.env.company

    def _currency(self):
        cur = self._company().currency_id
        return {"name": cur.name, "symbol": cur.symbol or cur.name}

    def _parse_amount(self, text, label="Summa"):
        raw = re.sub(r"\s", "", str(text if text is not None else "")).replace(",", ".")
        if not raw:
            raise UserError("%s: kiriting." % label)
        try:
            value = parse_sum(raw)
        except UserError as err:
            raise UserError("%s: %s" % (label, err)) from None
        if value is None or value <= 0:
            raise UserError("%s: musbat son kiriting." % label)
        return round(value, 2)

    def _day(self, value, label="Sana"):
        today = fields.Date.context_today(self)
        day = fields.Date.to_date(value) if value else today
        if day > today:
            raise UserError("%s: kelajak sanasi bo'lishi mumkin emas." % label)
        return day

    def _period(self, date_from, date_to):
        today = fields.Date.context_today(self)
        start = fields.Date.to_date(date_from) if date_from else today.replace(day=1)
        end = fields.Date.to_date(date_to) if date_to else today
        if start > end:
            start, end = end, start
        return start, end

    def _aml_domain(self, account_type):
        return [("account_id.account_type", "=", account_type), ("parent_state", "=", "posted"),
                ("company_id", "=", self._company().id), ("partner_id", "!=", False)]

    @api.model
    def _reconcile_partner(self, partner, account_type):
        """Hamkorning ochiq qarz va to'lovlari eng eskisidan boshlab yopiladi (avans keyingi hisob-fakturaga)."""
        partner = partner.commercial_partner_id
        if not partner:
            return
        lines = self.env["account.move.line"].sudo().search(
            self._aml_domain(account_type) + [("partner_id", "=", partner.id), ("reconciled", "=", False),
                                              ("amount_residual", "!=", 0)], order="date, id")
        for account in lines.account_id:
            group = lines.filtered(lambda l: l.account_id == account)
            if group.filtered(lambda l: l.amount_residual > 0) and group.filtered(lambda l: l.amount_residual < 0):
                group.reconcile()

    def _balances(self, account_type):
        """{partner: (qoldiq, oxirgi sana)}; mijoz uchun + — bizga qarz, yetkazib beruvchi uchun + — bizning qarz."""
        sign = 1 if account_type == "asset_receivable" else -1
        rows = self.env["account.move.line"]._read_group(
            self._aml_domain(account_type), ["partner_id"], ["balance:sum", "date:max"])
        return {partner: (sign * balance, last) for partner, balance, last in rows}

    def _journals(self):
        return self.env["account.journal"].search(
            [("company_id", "=", self._company().id), ("craf_pay_method", "!=", False)],
            order="craf_pay_method desc, id")

    def _journal_balance(self, journal):
        """Kassa / hisob qoldig'i: to'lovlar (pul tomoni) va bank ko'chirmalari."""
        AML = self.env["account.move.line"]
        domain = [("journal_id", "=", journal.id), ("parent_state", "=", "posted"),
                  ("account_id.account_type", "not in", ("asset_receivable", "liability_payable"))]
        pay = AML._read_group(domain + [("move_id.origin_payment_id", "!=", False)], [], ["balance:sum"])[0][0]
        other = AML._read_group(domain + [("move_id.origin_payment_id", "=", False),
                                          ("account_id", "=", journal.default_account_id.id)],
                                [], ["balance:sum"])[0][0] if journal.default_account_id else 0.0
        return (pay or 0.0) + (other or 0.0)

    def _payment_row(self, pay):
        method = pay.journal_id.craf_pay_method
        return {
            "id": pay.id, "name": pay.name or "", "date": fields.Date.to_string(pay.date),
            "partner": pay.partner_id.name or "", "partner_id": pay.partner_id.id,
            "kind": "in" if pay.payment_type == "inbound" else "out",
            "partner_type": pay.partner_type, "method": method or "", "method_label": METHOD_LABEL.get(method, pay.journal_id.name),
            "journal": pay.journal_id.name, "amount": pay.amount, "memo": pay.memo or "",
            "state": pay.state, "c1": pay.c1_state, "user": pay.create_uid.name or "",
        }

    def _kg_of_lines(self, lines):
        kgm = self.env.ref("uom.product_uom_kgm", raise_if_not_found=False)
        kg = 0.0
        for line in lines:
            product = line.product_id
            if not product:
                continue
            qty = line.quantity
            if product.uom_id == kgm:
                kg += qty
            else:
                kg += qty * (product.craf_kg_per_pc or 0.0)
        return kg

    # ================================================================== sahifa
    @api.model
    def get_data(self, date_from=False, date_to=False):
        start, end = self._period(date_from, date_to)
        company = self._company()
        cust = self._balances("asset_receivable")
        supp = self._balances("liability_payable")
        Pay = self.env["account.payment"]
        payments = Pay.search([("company_id", "=", company.id), ("date", ">=", start), ("date", "<=", end),
                               ("state", "in", LIVE_PAYMENT)], order="date desc, id desc")
        income = sum(p.amount for p in payments if p.payment_type == "inbound")
        outgo = sum(p.amount for p in payments if p.payment_type == "outbound")
        by_method = defaultdict(float)
        for p in payments.filtered(lambda p: p.payment_type == "inbound"):
            by_method[p.journal_id.craf_pay_method or "boshqa"] += p.amount
        Move = self.env["account.move"]
        invoices = Move.search([("company_id", "=", company.id), ("state", "=", "posted"),
                                ("move_type", "in", ("out_invoice", "out_refund", "in_invoice", "in_refund")),
                                ("invoice_date", ">=", start), ("invoice_date", "<=", end)])
        sales = sum(m.amount_total_signed for m in invoices if m.move_type in ("out_invoice", "out_refund"))
        buys = -sum(m.amount_total_signed for m in invoices if m.move_type in ("in_invoice", "in_refund"))
        sale_kg = sum(self._kg_of_lines(m.invoice_line_ids) * (1 if m.move_type == "out_invoice" else -1)
                      for m in invoices if m.move_type in ("out_invoice", "out_refund"))

        debtors = {p: v for p, v in cust.items() if v[0] > 0.5}
        creditors = {p: v for p, v in supp.items() if v[0] > 0.5}
        sub_method = " · ".join("%s %s" % (METHOD_LABEL.get(k, k).lower().split()[0], _short(v))
                                for k, v in by_method.items() if v)
        kpi = [
            {"label": "Mijozlar qarzi", "value": sum(v[0] for v in debtors.values()), "money": True,
             "sub": "%s ta mijoz" % len(debtors), "tone": "bad" if debtors else ""},
            {"label": "Bizning qarz", "value": sum(v[0] for v in creditors.values()), "money": True,
             "sub": "%s ta yetkazib beruvchiga" % len(creditors), "tone": "warn" if creditors else ""},
            {"label": "Tushum", "value": income, "money": True, "sub": sub_method, "tone": "ok" if income else ""},
            {"label": "To'landi", "value": outgo, "money": True, "sub": "%s ta to'lov" % len(
                payments.filtered(lambda p: p.payment_type == "outbound"))},
            {"label": "Sotuv", "value": sales, "money": True, "sub": "%s kg" % _money(sale_kg) if sale_kg else ""},
            {"label": "Xarid", "value": buys, "money": True, "sub": ""},
        ]

        def partner_rows(balances, rank_field):
            rows = []
            for partner, (balance, last) in balances.items():
                if abs(balance) < 0.5:
                    continue
                rows.append({"id": partner.id, "name": partner.name or "", "phone": partner.phone or "",
                             "balance": round(balance, 2), "last": fields.Date.to_string(last) if last else ""})
            rows.sort(key=lambda r: (-r["balance"], r["name"]))
            return rows

        # narxsiz berilgan + modul o'rnatilishidan oldin berilib, hisob-faktura qilinmagan buyurtmalar
        noprice = self.env["sale.order"].search([
            ("state", "=", "sale"), "|", ("craf_price_missing", "=", True),
            "&", ("craf_given_date", "!=", False), ("invoice_status", "=", "to invoice"),
        ], order="craf_given_date desc")
        unbilled = self._unbilled_receipts()
        roles = self._roles()
        return {
            "today": fields.Date.to_string(fields.Date.context_today(self)),
            "date_from": fields.Date.to_string(start), "date_to": fields.Date.to_string(end),
            "currency": self._currency(), "setup": self.setup_info(), "roles": roles,
            "kpi": kpi,
            "journals": [{"id": j.id, "name": j.name, "method": j.craf_pay_method,
                          "balance": round(self._journal_balance(j), 2)} for j in self._journals()],
            "customers": partner_rows(cust, "customer_rank"),
            "suppliers": partner_rows(supp, "supplier_rank"),
            "payments": [self._payment_row(p) for p in payments],
            "noprice": [{
                "id": o.id, "name": o.name, "partner": o.partner_id.name or "",
                "date": fields.Date.to_string(fields.Date.context_today(self, o.craf_given_date)) if o.craf_given_date else "",
                "truck": o.craf_truck or "", "lines": len(o._craf_lines_to_invoice()),
            } for o in noprice],
            "unbilled": unbilled,
            "prices_missing": self.env["product.template"].search_count(
                [("sale_ok", "=", True), ("type", "=", "consu"), ("list_price", "<=", PRICE_MIN)]),
        }

    def _unbilled_receipts(self, limit_days=180):
        since = fields.Datetime.now() - timedelta(days=limit_days)
        pickings = self.env["stock.picking"].search([
            ("state", "=", "done"), ("location_id.usage", "=", "supplier"), ("location_dest_id.usage", "=", "internal"),
            ("date_done", ">=", since), "|", ("craf_bill_id", "=", False), ("craf_bill_id.state", "=", "cancel"),
        ], order="date_done desc")
        rows = []
        for p in pickings:
            if not p._craf_is_supply() or p.return_ids.filtered(lambda r: r.state == "done"):
                continue
            moves = p._craf_supply_moves()
            rows.append({
                "id": p.id, "name": p.name, "vehicle": p.craf_vehicle or "", "partner": p.partner_id.name or "",
                "date": fields.Date.to_string(p._craf_day()),
                "kg": round(self._kg_of_lines(moves), 1),
                "missing": p._craf_bill_missing(),
                "amount": round(sum(m.quantity * (m.craf_price or 0.0) for m in moves), 2),
            })
        return rows

    # ================================================================== hamkor (akt sverka)
    def _line_label(self, line):
        move = line.move_id
        pay = move.origin_payment_id
        if pay:
            method = METHOD_LABEL.get(pay.journal_id.craf_pay_method, pay.journal_id.name)
            what = "To'lov" if pay.payment_type == ("inbound" if pay.partner_type == "customer" else "outbound") \
                else "Qaytarilgan pul"
            return "%s · %s%s" % (what, method, (" · " + pay.memo) if pay.memo else "")
        kg = self._kg_of_lines(move.invoice_line_ids)
        kg_text = " · %s kg" % _money(kg) if kg else ""
        if move.move_type == "out_invoice":
            orders = move.invoice_line_ids.sale_line_ids.order_id
            truck = ", ".join(filter(None, orders.mapped("craf_truck")))
            return "Sotuv %s%s%s" % (move.invoice_origin or "", kg_text, (" · " + truck) if truck else "")
        if move.move_type == "out_refund":
            return "Qaytarish (mijoz)%s" % kg_text
        if move.move_type == "in_invoice":
            return "Kirim %s%s" % (move.ref or move.invoice_origin or "", kg_text)
        if move.move_type == "in_refund":
            return "Qaytarish (yetkazib beruvchiga)%s" % kg_text
        return move.ref or line.name or move.name

    @api.model
    def partner_detail(self, partner_id, kind="customer", date_from=False, date_to=False):
        partner = self.env["res.partner"].browse(int(partner_id)).exists().commercial_partner_id
        if not partner:
            raise UserError("Hamkor topilmadi.")
        account_type = KINDS.get(kind, "asset_receivable")
        sign = 1 if account_type == "asset_receivable" else -1
        today = fields.Date.context_today(self)
        start = fields.Date.to_date(date_from) if date_from else today - timedelta(days=89)
        end = fields.Date.to_date(date_to) if date_to else today
        lines = self.env["account.move.line"].search(
            self._aml_domain(account_type) + [("partner_id", "=", partner.id)], order="date, id")
        opening = sign * sum(l.balance for l in lines if l.date < start)
        running = opening
        rows, plus, minus = [], 0.0, 0.0
        for line in lines.filtered(lambda l: start <= l.date <= end):
            amount = sign * line.balance
            running += amount
            if amount >= 0:
                plus += amount
            else:
                minus -= amount
            pay = line.move_id.origin_payment_id
            rows.append({
                "id": line.id, "move_id": line.move_id.id, "payment_id": pay.id or False,
                "date": fields.Date.to_string(line.date), "name": pay.name if pay else line.move_id.name,
                "label": self._line_label(line), "amount": round(amount, 2), "balance": round(running, 2),
                "residual": round(sign * line.amount_residual, 2),
            })
        current = sign * sum(lines.mapped("balance"))
        rows.reverse()
        return {
            "partner": {"id": partner.id, "name": partner.name, "phone": partner.phone or "",
                        "vat": partner.vat or ""},
            "kind": kind, "date_from": fields.Date.to_string(start), "date_to": fields.Date.to_string(end),
            "opening": round(opening, 2), "closing": round(running, 2), "current": round(current, 2),
            "plus": round(plus, 2), "minus": round(minus, 2), "rows": rows,
            "currency": self._currency(), "roles": self._roles(),
        }

    # ================================================================== to'lov
    @api.model
    def payment_options(self, partner_type="customer"):
        account_type = KINDS.get(partner_type, "asset_receivable")
        balances = self._balances(account_type)
        rank = "customer_rank" if partner_type == "customer" else "supplier_rank"
        partners = self.env["res.partner"].search([(rank, ">", 0)], limit=500)
        seen = {}
        for p in list(balances) + list(partners):
            p = p.commercial_partner_id
            if p.id not in seen:
                seen[p.id] = {"id": p.id, "name": p.name or "", "balance": round(balances.get(p, (0.0, None))[0], 2)}
        rows = sorted(seen.values(), key=lambda r: (-(r["balance"] > 0.5), r["name"].lower()))
        return {
            "journals": [{"id": j.id, "name": j.name, "method": j.craf_pay_method,
                          "label": METHOD_LABEL.get(j.craf_pay_method, j.name)} for j in self._journals()],
            "partners": rows, "today": fields.Date.to_string(fields.Date.context_today(self)),
            "currency": self._currency(),
        }

    @api.model
    def payment_save(self, vals):
        """vals: partner_type (customer/supplier), direction (in/out — bo'lmasa odatiy), partner_id yoki partner_name,
        amount (matn: 1 500 000 yoki 1000000+500000), journal_id, date, memo."""
        self._need()
        partner_type = vals.get("partner_type") or "customer"
        if partner_type not in KINDS:
            raise UserError("Noto'g'ri hamkor turi.")
        direction = vals.get("direction") or ("in" if partner_type == "customer" else "out")
        Partner = self.env["res.partner"]
        partner = Partner.browse(int(vals.get("partner_id") or 0)).exists()
        if not partner:
            name = (vals.get("partner_name") or "").strip()
            if not name:
                raise UserError("Mijoz / yetkazib beruvchini tanlang.")
            partner = Partner.search([("name", "=ilike", name)], limit=1) or Partner.sudo().create(
                {"name": name, "customer_rank" if partner_type == "customer" else "supplier_rank": 1})
        partner = partner.commercial_partner_id
        amount = self._parse_amount(vals.get("amount"))
        journal = self.env["account.journal"].browse(int(vals.get("journal_id") or 0)).exists()
        if not journal or not journal.craf_pay_method:
            raise UserError("To'lov usulini tanlang (naqd, plastik, bank).")
        day = self._day(vals.get("date"))
        pay = self.env["account.payment"].create({
            "payment_type": "inbound" if direction == "in" else "outbound",
            "partner_type": partner_type,
            "partner_id": partner.id,
            "amount": amount,
            "journal_id": journal.id,
            "date": day,
            "memo": (vals.get("memo") or "").strip() or False,
        })
        pay.action_post()
        self._reconcile_partner(partner, KINDS[partner_type])
        return {"id": pay.id, "name": pay.name, "amount": pay.amount, "partner": partner.name,
                "balance": round(self._balances(KINDS[partner_type]).get(partner, (0.0, None))[0], 2)}

    @api.model
    def payment_detail(self, payment_id):
        pay = self.env["account.payment"].browse(int(payment_id)).exists()
        if not pay:
            raise UserError("To'lov topilmadi.")
        row = self._payment_row(pay)
        invoices = pay.reconciled_invoice_ids | pay.reconciled_bill_ids
        row["invoices"] = [{"name": m.name, "origin": m.invoice_origin or m.ref or "",
                            "amount": m.amount_total, "residual": m.amount_residual} for m in invoices]
        roles = self._roles()
        row["actions"] = [a for a, ok in [
            ("cancel", roles["accountant"] and pay.state in LIVE_PAYMENT),
            ("c1", roles["accountant"] and pay.state in LIVE_PAYMENT and pay.c1_state != "done"),
            ("c1_undo", roles["accountant"] and pay.c1_state == "done"),
        ] if ok]
        return row

    @api.model
    def payment_action(self, payment_id, action):
        self._need()
        pay = self.env["account.payment"].browse(int(payment_id)).exists()
        if not pay:
            raise UserError("To'lov topilmadi.")
        if action == "cancel":
            if pay.c1_state == "done":
                raise UserError("%s 1C ga kiritilgan — avval 1C belgisini oling." % pay.name)
            partner, partner_type = pay.partner_id, pay.partner_type
            pay.action_draft()
            pay.action_cancel()
            self._reconcile_partner(partner, KINDS[partner_type])
        elif action == "c1":
            pay.action_c1_done()
        elif action == "c1_undo":
            pay.action_c1_reset()
        else:
            raise UserError("Bu amal mumkin emas.")
        return {"id": pay.id, "name": pay.name, "state": pay.state}

    # ================================================================== narx kerak: buyurtma
    @api.model
    def order_detail(self, order_id):
        order = self.env["sale.order"].browse(int(order_id)).exists()
        if not order:
            raise UserError("Buyurtma topilmadi.")
        lines = []
        for line in order.order_line.filtered(lambda l: not l.display_type and l.product_id):
            qty = line.qty_delivered or line.product_uom_qty
            lines.append({
                "id": line.id, "name": line.product_id.display_name, "code": line.product_id.default_code or "",
                "qty": qty, "delivered": line.qty_delivered,
                "uom": "dona" if line.product_uom_id == self.env.ref("uom.product_uom_unit") else line.product_uom_id.name,
                "kg_pc": line.product_id.craf_kg_per_pc or 0.0, "price": line.price_unit if line.price_unit > PRICE_MIN else 0.0,
                "list_price": line.product_id.lst_price if line.product_id.lst_price > PRICE_MIN else 0.0,
                "invoiced": line.qty_invoiced,
            })
        invoices = order.invoice_ids.filtered(lambda m: m.state == "posted")
        return {
            "id": order.id, "name": order.name, "partner": order.partner_id.name or "", "truck": order.craf_truck or "",
            "date": fields.Date.to_string(fields.Date.context_today(self, order.craf_given_date)) if order.craf_given_date else "",
            "lines": lines, "invoices": [{"name": m.name, "amount": m.amount_total, "residual": m.amount_residual}
                                         for m in invoices],
            "missing": order.craf_price_missing, "currency": self._currency(),
        }

    @api.model
    def order_prices_save(self, order_id, prices):
        self._need()
        order = self.env["sale.order"].browse(int(order_id)).exists()
        if not order:
            raise UserError("Buyurtma topilmadi.")
        clean = {}
        for key, value in (prices or {}).items():
            if value in (None, ""):
                continue
            clean[str(key)] = self._parse_amount(value, "Narx")
        order._craf_set_prices(clean)
        return {"id": order.id, "name": order.name, "missing": order.craf_price_missing,
                "amount": sum(order.invoice_ids.filtered(lambda m: m.state == "posted").mapped("amount_total"))}

    # ================================================================== hisob-fakturasiz kirim
    @api.model
    def receipt_detail(self, picking_id):
        picking = self.env["stock.picking"].browse(int(picking_id)).exists()
        if not picking:
            raise UserError("Kirim topilmadi.")
        partners = self.env["res.partner"].search([("supplier_rank", ">", 0)], limit=300)
        return {
            "id": picking.id, "name": picking.name, "vehicle": picking.craf_vehicle or "",
            "partner": picking.partner_id.name or "", "date": fields.Date.to_string(picking._craf_day()),
            "lines": [{"id": m.id, "name": m.product_id.display_name, "qty": m.quantity, "uom": m.product_uom.name,
                       "price": m.craf_price or 0.0} for m in picking._craf_supply_moves()],
            "bill": picking.craf_bill_id.name if picking.craf_bill_id.state == "posted" else "",
            "partners": sorted({p.name for p in partners if p.name}), "currency": self._currency(),
        }

    @api.model
    def receipt_bill_save(self, picking_id, vals):
        """vals: partner_name, prices {move_id: narx}."""
        self._need()
        picking = self.env["stock.picking"].browse(int(picking_id)).exists()
        if not picking or not picking._craf_is_supply():
            raise UserError("Kirim topilmadi.")
        if picking.craf_bill_id and picking.craf_bill_id.state == "posted":
            raise UserError("%s ga hisob-faktura yozilgan: %s." % (picking.name, picking.craf_bill_id.name))
        name = (vals.get("partner_name") or "").strip()
        if name:
            Partner = self.env["res.partner"]
            partner = Partner.search([("name", "=ilike", name)], limit=1) or Partner.sudo().create(
                {"name": name, "supplier_rank": 1, "is_company": True})
            if partner != picking.partner_id:
                picking.sudo().partner_id = partner
        moves = picking._craf_supply_moves()
        for key, value in (vals.get("prices") or {}).items():
            move = moves.filtered(lambda m: m.id == int(key))
            if move and value not in (None, ""):
                move.sudo().craf_price = self._parse_amount(value, move.product_id.name)
        missing = picking._craf_bill_missing()
        if missing:
            raise UserError("Hisob-faktura uchun %s kerak." % " va ".join(missing))
        bill = picking._craf_make_bill()
        return {"id": picking.id, "name": picking.name, "bill": bill.name, "amount": bill.amount_total}

    # ================================================================== narxlar
    @api.model
    def prices(self):
        rows = []
        Tmpl = self.env["product.template"]
        for t in Tmpl.search([("sale_ok", "=", True), ("type", "=", "consu")],
                             order="craf_section_id, craf_color_id, craf_length_m desc, name"):
            price = t.list_price if t.list_price > PRICE_MIN else 0.0
            kg_pc = t.craf_kg_per_pc or 0.0
            rows.append({
                "id": t.id, "name": t.name, "code": t.default_code or "",
                "section": t.craf_section_id.name or "Boshqa", "color": t.craf_color_id.name or "",
                "length": t.craf_length_m or 0.0, "kg_pc": round(kg_pc, 4), "per_pack": t.craf_pcs_per_pack or 0,
                "price": round(price, 2), "price_kg": round(price / kg_pc, 2) if price and kg_pc else 0.0,
            })
        return {"rows": rows, "currency": self._currency(), "roles": self._roles()}

    @api.model
    def prices_save(self, changes):
        """changes: [{id, price_kg} yoki {id, price}] — dona narxi butun so'mga yaxlitlanadi."""
        self._need()
        Tmpl = self.env["product.template"]
        count = 0
        for ch in changes or []:
            t = Tmpl.browse(int(ch.get("id") or 0)).exists()
            if not t:
                continue
            if ch.get("price_kg") not in (None, ""):
                kg = self._parse_amount(ch["price_kg"], "%s: 1 kg narxi" % t.name)
                if not t.craf_kg_per_pc:
                    raise UserError("%s: 1 dona og'irligi yo'q — narxni dona uchun yozing." % t.name)
                price = round(kg * t.craf_kg_per_pc)
            elif ch.get("price") not in (None, ""):
                price = round(self._parse_amount(ch["price"], "%s: narx" % t.name))
            else:
                continue
            if abs(t.list_price - price) > 0.5:
                old = t.list_price
                t.list_price = price
                t.message_post(body="Narx: %s → %s %s (1 dona)" % (
                    _money(old) if old > PRICE_MIN else "yo'q", _money(price), self._currency()["symbol"]))
                count += 1
        return {"count": count}

    @api.model
    def prices_demo(self):
        """Namuna narxlar (1 kg) — faqat narxi yo'q mahsulotlarga, sinov uchun."""
        self._need("manager")
        changes = []
        for t in self.env["product.template"].search(
                [("sale_ok", "=", True), ("type", "=", "consu"), ("list_price", "<=", PRICE_MIN),
                 ("craf_kg_per_pc", ">", 0)]):
            changes.append({"id": t.id, "price_kg": DEMO_KG.get(t.craf_color_id.name, DEMO_KG_DEFAULT)})
        return self.prices_save(changes)
