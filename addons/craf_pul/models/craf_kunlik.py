from odoo import api, models

from .craf_pul import LIVE_PAYMENT, METHOD_LABEL, _money


class CrafKunlikHisobot(models.AbstractModel):
    _inherit = "craf.kunlik.hisobot"

    def _payments_of_day(self, day):
        return self.env["account.payment"].search([
            ("company_id", "=", self.env.company.id), ("date", "=", day), ("state", "in", LIVE_PAYMENT)],
            order="id")

    def _money_department(self, day):
        pays = self._payments_of_day(day)
        symbol = self.env["craf.pul"]._currency()["symbol"]
        docs, by_method = [], {}
        income = outgo = 0.0
        for p in pays:
            inbound = p.payment_type == "inbound"
            method = p.journal_id.craf_pay_method
            if inbound:
                income += p.amount
                by_method[method] = by_method.get(method, 0.0) + p.amount
            else:
                outgo += p.amount
            docs.append({
                "model": "account.payment", "id": p.id,
                "name": "%s · %s · %s%s %s" % (p.name, p.partner_id.name or "", "+" if inbound else "−",
                                                _money(p.amount), symbol),
                "state": "done", "state_label": METHOD_LABEL.get(method, p.journal_id.name), "c1": p.c1_state,
                "who": p.partner_id.name or "", "shift": "",
            })
        extra = []
        if income:
            extra.append("Tushum: %s %s (%s)" % (_money(income), symbol, ", ".join(
                "%s %s" % (METHOD_LABEL.get(k, k).lower(), _money(v)) for k, v in by_method.items())))
        if outgo:
            extra.append("To'landi: %s %s" % (_money(outgo), symbol))
        return {
            "key": "pul", "title": "To'lovlar (tushum va to'lov)", "model": "account.payment", "action": False,
            "docs": docs, "used": [], "made": [], "waste": [], "extra": extra,
            "done_count": len(docs), "draft_count": 0,
        }

    @api.model
    def get_data(self, day=None):
        data = super().get_data(day)
        day = self._parse_day(data["date"])
        dep = self._money_department(day)
        deps = data["departments"]
        invoices = self.env["account.move"].search([
            ("company_id", "=", self.env.company.id), ("state", "=", "posted"), ("invoice_date", "=", day),
            ("move_type", "in", ("out_invoice", "out_refund", "in_invoice", "in_refund"))])
        symbol = self.env["craf.pul"]._currency()["symbol"]
        for d in deps:
            types = {"sotuv": ("out_invoice", "out_refund"), "kirim": ("in_invoice", "in_refund")}.get(d["key"])
            if types:
                total = abs(sum(m.amount_total_signed for m in invoices if m.move_type in types))
                if total:
                    d["extra"].append("Summa: %s %s" % (_money(total), symbol))
        deps.append(dep)
        for i, d in enumerate(deps):
            d["title"] = "%s. %s" % (i + 1, d["title"].split(". ", 1)[1] if d["title"][:1].isdigit() else d["title"])
        data["c1_new"] += sum(1 for d in dep["docs"] if d["c1"] == "new")
        return data

    @api.model
    def action_mark_c1(self, day=None):
        count = super().action_mark_c1(day)
        pays = self._payments_of_day(self._parse_day(day)).filtered(lambda p: p.c1_state == "new")
        pays.action_c1_done()
        return count + len(pays)
