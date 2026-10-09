from datetime import datetime, time, timedelta

from odoo import api, fields, models

PERIODS = {"today": 1, "7": 7, "30": 30}

# Me'yorlar (prototip; zavod tajribasiga qarab o'zgartiriladi)
NORM_BURN_LOSS = 3.0      # угар, % dan oshmasin
NORM_PRESS_YIELD = 80.0   # press chiqishi, % dan kam bo'lmasin
NORM_DEFECT = 2.0         # bo'yash braki, % dan oshmasin


class CrafDashboard(models.AbstractModel):
    _name = "craf.dashboard"
    _description = "Craf kunlik panel"

    @api.model
    def get_data(self, period="7"):
        days = PERIODS.get(period, 7)
        today = fields.Date.context_today(self)
        start = today - timedelta(days=days - 1)
        dom = [("date", ">=", start), ("date", "<=", today), ("state", "=", "done")]

        melts = self.env["craf.foundry.melt"].search(dom)
        shifts = self.env["craf.extrusion.shift"].search(dom)
        batches = self.env["craf.paint.batch"].search(dom)

        metal = sum(melts.mapped("charge_metal"))
        billet = sum(melts.mapped("billet_qty"))
        loss = sum(melts.mapped("burn_loss_qty"))
        press_in = sum(shifts.mapped("billet_qty"))
        press_out = sum(shifts.mapped("output_kg"))
        press_pcs = sum(shifts.mapped("output_pcs"))
        paint_in = sum(batches.mapped("pcs_in"))
        paint_ok = sum(batches.mapped("pcs_ok"))
        paint_def = sum(batches.mapped("pcs_defect"))
        paint_kg = sum(batches.mapped("kg_ok"))
        powder = sum(batches.mapped("powder_qty"))
        powder_norm = sum(batches.mapped("powder_norm_qty"))

        # Tayyor profil = bo'yalgan + bo'yashsiz sotiladigan (Прижим, Соединитель…)
        direct = shifts.line_ids.filtered(lambda l: l.product_id.sale_ok)
        finished_kg = paint_kg + sum(direct.mapped("kg"))
        finished_pcs = paint_ok + sum(direct.mapped("pcs"))

        tz_start = self._utc(start)
        tz_end = self._utc(today + timedelta(days=1))
        packs = self.env["craf.pack"].search_count([("date", ">=", tz_start), ("date", "<", tz_end)])
        orders = self.env["sale.order"].search([
            ("state", "=", "sale"), ("date_order", ">=", tz_start), ("date_order", "<", tz_end)])
        currency = self.env.company.currency_id

        series = []
        for i in range(days):
            day = start + timedelta(days=i)
            series.append({
                "date": fields.Date.to_string(day),
                "label": day.strftime("%d.%m"),
                "billet": round(sum(melts.filtered(lambda m, d=day: m.date == d).mapped("billet_qty")), 1),
                "press": round(sum(shifts.filtered(lambda s, d=day: s.date == d).mapped("output_kg")), 1),
                "paint": round(sum(batches.filtered(lambda b, d=day: b.date == d).mapped("kg_ok")), 1),
            })

        zones = self.env["craf.zavod.xarita"].get_map_data(top_limit=0)["zones"]
        return {
            "period": period,
            "start": fields.Date.to_string(start),
            "end": fields.Date.to_string(today),
            "kpi": {
                "finished_kg": finished_kg,
                "finished_pcs": finished_pcs,
                "melt_count": len(melts),
                "billet_kg": billet,
                "metal_kg": metal,
                "burn_loss_pct": loss / metal * 100.0 if metal else 0.0,
                "shift_count": len(shifts),
                "press_in_kg": press_in,
                "press_out_kg": press_out,
                "press_pcs": press_pcs,
                "press_yield_pct": press_out / press_in * 100.0 if press_in else 0.0,
                "batch_count": len(batches),
                "paint_ok_pcs": paint_ok,
                "paint_kg": paint_kg,
                "defect_pct": paint_def / paint_in * 100.0 if paint_in else 0.0,
                "defect_pcs": paint_def,
                "powder_kg": powder,
                "powder_diff_pct": (powder - powder_norm) / powder_norm * 100.0 if powder_norm else 0.0,
                "packs": packs,
                "orders": len(orders),
                "sales_amount": sum(orders.mapped("amount_total")),
                "currency": currency.symbol or currency.name,
            },
            "norms": {"burn_loss": NORM_BURN_LOSS, "press_yield": NORM_PRESS_YIELD, "defect": NORM_DEFECT},
            "series": series,
            "zones": [{"id": z["id"], "name": z["name"], "kind": z["kind"], "kg": z["kg_total"],
                       "pcs": z["pcs_total"]} for z in zones],
            "low_stock": self._low_stock(),
            "drafts": self._drafts(),
            "recent": self._recent(),
        }

    @api.model
    def _utc(self, day):
        """Mahalliy kun boshini (foydalanuvchi vaqt zonasida) UTC datetime ga aylantiradi."""
        local = datetime.combine(day, time.min)
        tz_dt = fields.Datetime.context_timestamp(self, datetime.combine(day, time(12)))
        offset = tz_dt.utcoffset() or timedelta(0)
        return local - offset

    @api.model
    def _low_stock(self, limit=6):
        Tmpl = self.env["product.template"]
        products = Tmpl.search([("sale_ok", "=", True), ("craf_section_id", "!=", False), ("is_storable", "=", True)])
        rows = sorted(products, key=lambda t: t.qty_available)[:limit]
        return [{
            "id": t.id,
            "name": t.display_name,
            "pcs": t.qty_available,
            "text": Tmpl._craf_packs_text(t.qty_available, t.craf_pcs_per_pack),
        } for t in rows]

    @api.model
    def _drafts(self):
        return [
            {"model": model, "label": label, "count": self.env[model].search_count([("state", "=", "draft")])}
            for model, label in (
                ("craf.foundry.melt", "Plavka"),
                ("craf.extrusion.shift", "Press"),
                ("craf.paint.batch", "Bo'yash"),
            )
        ]

    @api.model
    def _recent(self, limit=8):
        docs = []
        for rec in self.env["craf.foundry.melt"].search([("state", "=", "done")], limit=limit):
            docs.append(("Литейка", rec, "%s kg quyma · угар %s%%" % (self._n(rec.billet_qty), self._p(rec.burn_loss_pct))))
        for rec in self.env["craf.extrusion.shift"].search([("state", "=", "done")], limit=limit):
            docs.append(("Press", rec, "%s · %s dona · chiqish %s%%" % (rec.section_id.name, self._n(rec.output_pcs), self._p(rec.yield_pct))))
        for rec in self.env["craf.paint.batch"].search([("state", "=", "done")], limit=limit):
            docs.append(("Bo'yash", rec, "%s · %s dona · brak %s%%" % (rec.color_id.name, self._n(rec.pcs_ok), self._p(rec.defect_pct))))
        docs.sort(key=lambda d: (d[1].date, d[1].write_date), reverse=True)
        return [{
            "stage": stage, "model": rec._name, "id": rec.id, "name": rec.name,
            "date": rec.date.strftime("%d.%m"), "text": text,
        } for stage, rec, text in docs[:limit]]

    @staticmethod
    def _n(value):
        return f"{value:,.0f}".replace(",", " ")

    @staticmethod
    def _p(value):
        return f"{value:.1f}".replace(".", ",")
