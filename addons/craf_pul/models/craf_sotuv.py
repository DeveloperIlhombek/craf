from odoo import api, models

from .craf_pul import _money


class CrafSotuv(models.AbstractModel):
    _inherit = "craf.sotuv"

    def _craf_debt(self, partner_ids):
        """{partner_id: qarz} — mijozlar qarzi (0 dan katta bo'lsa)."""
        if not partner_ids:
            return {}
        Partner = self.env["res.partner"].sudo()
        partners = Partner.browse(list(partner_ids)).exists()
        rows = self.env["account.move.line"].sudo()._read_group(
            [("account_id.account_type", "=", "asset_receivable"), ("parent_state", "=", "posted"),
             ("partner_id", "in", partners.commercial_partner_id.ids)], ["partner_id"], ["balance:sum"])
        debt = {p.id: b for p, b in rows}
        return {p.id: debt.get(p.commercial_partner_id.id, 0.0) for p in partners}

    def _craf_with_debt(self, items):
        debts = self._craf_debt({i["id"] for i in items if i and i.get("id")})
        symbol = self.env.company.currency_id.symbol or ""
        for item in items:
            if item and item.get("id"):
                value = debts.get(item["id"], 0.0)
                item["debt"] = round(value, 2)
                item["debt_text"] = "qarz %s %s" % (_money(value), symbol) if value > 0.5 else ""
        return items

    def _partner_info(self, name, learned_partners):
        res = super()._partner_info(name, learned_partners)
        self._craf_with_debt([res["partner"]] if res.get("partner") else [] + list(res.get("suggestions") or []))
        return res

    @api.model
    def search_partners(self, query="", limit=8):
        return self._craf_with_debt(super().search_partners(query, limit))
