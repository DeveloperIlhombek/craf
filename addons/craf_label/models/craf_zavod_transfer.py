from odoo import api, fields, models


class CrafZavodTransfer(models.TransientModel):
    _inherit = "craf.zavod.transfer"

    scan_code = fields.Char("Skaner", help="Pachka QR kodini skanerlang yoki pachka raqamini / mahsulot kodini yozing.")
    pack_id = fields.Many2one("craf.pack", "Skanerlangan pachka")

    @api.onchange("scan_code")
    def _onchange_scan_code(self):
        code = (self.scan_code or "").strip()
        if not code:
            return
        pack = self.env["craf.pack"]._craf_find(code)
        if pack:
            self.pack_id = pack
            if pack.location_id:
                self.location_id = pack.location_id
            self.product_id = pack.product_id
            per = pack.product_id.craf_pcs_per_pack
            if per and pack.pcs == per:
                self.qty_packs, self.qty_extra = 1, 0
            elif per:
                self.qty_packs, self.qty_extra = 0, pack.pcs
            self.quantity = pack.pcs
            self.scan_code = pack.name
            return
        short = code.rstrip("/").rsplit("/", 1)[-1].strip()
        product = self.env["product.product"].search(
            ["|", ("default_code", "=ilike", short), ("barcode", "=", short)], limit=1)
        if product:
            self.pack_id = False
            self.product_id = product
            return
        return {"warning": {"title": "Topilmadi", "message": "'%s' — bunday pachka yoki mahsulot kodi yo'q." % code}}

    def action_confirm(self):
        res = super().action_confirm()
        for wiz in self:
            if wiz.pack_id:
                wiz.pack_id.location_id = wiz.location_dest_id
        return res
