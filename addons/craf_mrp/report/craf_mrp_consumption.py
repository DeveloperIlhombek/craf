from odoo import fields, models, tools


class CrafMrpConsumption(models.Model):
    """Xom-ashyo sarfi: bajarilgan ishlab chiqarish buyurtmalaridagi haqiqiy sarf va me'yor."""

    _name = "craf.mrp.consumption"
    _description = "Xom-ashyo sarfi (me'yor va haqiqiy)"
    _auto = False
    _order = "date desc"

    date = fields.Date("Sana", readonly=True)
    production_id = fields.Many2one("mrp.production", "Buyurtma", readonly=True)
    origin = fields.Char("Hujjat", readonly=True)
    picking_type_id = fields.Many2one("stock.picking.type", "Bosqich", readonly=True)
    finished_product_id = fields.Many2one("product.product", "Chiqgan mahsulot", readonly=True)
    product_id = fields.Many2one("product.product", "Xom-ashyo", readonly=True)
    uom_id = fields.Many2one("uom.uom", "Birlik", readonly=True)
    qty_produced = fields.Float("Chiqdi", readonly=True, aggregator="sum")
    qty_actual = fields.Float("Haqiqiy sarf", readonly=True, aggregator="sum")
    qty_norm = fields.Float("Me'yor bo'yicha", readonly=True, aggregator="sum")
    qty_diff = fields.Float("Farq (+ ortiqcha)", readonly=True, aggregator="sum")
    company_id = fields.Many2one("res.company", readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                WITH produced AS (
                    SELECT fm.production_id, SUM(fm.quantity) AS qty
                      FROM stock_move fm
                      JOIN mrp_production p ON p.id = fm.production_id AND fm.product_id = p.product_id
                     WHERE fm.state = 'done'
                  GROUP BY fm.production_id
                ),
                norm AS (
                    SELECT DISTINCT ON (b.product_tmpl_id, bl.product_id)
                           b.product_tmpl_id, bl.product_id, bl.product_qty / NULLIF(b.product_qty, 0) AS per_unit
                      FROM mrp_bom b
                      JOIN mrp_bom_line bl ON bl.bom_id = b.id
                     WHERE b.active AND b.type = 'normal'
                  ORDER BY b.product_tmpl_id, bl.product_id, b.craf_auto DESC NULLS LAST, b.sequence, b.id
                )
                SELECT sm.id AS id,
                       (sm.date AT TIME ZONE 'UTC')::date AS date,
                       mo.id AS production_id,
                       mo.origin AS origin,
                       mo.picking_type_id AS picking_type_id,
                       mo.product_id AS finished_product_id,
                       sm.product_id AS product_id,
                       sm.product_uom AS uom_id,
                       COALESCE(pr.qty, 0) AS qty_produced,
                       sm.quantity AS qty_actual,
                       COALESCE(n.per_unit * pr.qty, 0) AS qty_norm,
                       sm.quantity - COALESCE(n.per_unit * pr.qty, 0) AS qty_diff,
                       mo.company_id AS company_id
                  FROM stock_move sm
                  JOIN mrp_production mo ON mo.id = sm.raw_material_production_id
                  JOIN product_product fp ON fp.id = mo.product_id
             LEFT JOIN produced pr ON pr.production_id = mo.id
             LEFT JOIN norm n ON n.product_tmpl_id = fp.product_tmpl_id AND n.product_id = sm.product_id
                 WHERE sm.state = 'done'
            )
        """)
