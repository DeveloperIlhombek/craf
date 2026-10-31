from odoo import api, models

from .sale_order import money


class ReportCrafDillerAkt(models.AbstractModel):
    _name = "report.craf_diller.report_akt"
    _description = "Akt sverka (PDF)"

    @api.model
    def _get_report_values(self, docids, data=None):
        data = data or {}
        detail = self.env["craf.pul"].sudo().partner_detail(
            docids[0], "customer", data.get("date_from") or False, data.get("date_to") or False)
        return {
            "doc_ids": docids, "doc_model": "res.partner", "d": detail, "company": self.env.company,
            "rows": list(reversed(detail["rows"])), "money": money,
            "dmy": lambda iso: "%s.%s.%s" % (iso[8:10], iso[5:7], iso[0:4]) if iso else "",
        }
