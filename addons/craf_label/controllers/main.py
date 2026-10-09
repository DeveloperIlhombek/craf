from odoo import http
from odoo.http import request


class CrafLabelController(http.Controller):

    @http.route("/craf/p/<string:code>", type="http", auth="user")
    def craf_pack_open(self, code, **kwargs):
        """QR kod havolasi: pachka kartochkasini ochadi."""
        pack = request.env["craf.pack"]._craf_find(code)
        if not pack:
            return request.redirect("/odoo/action-craf_label.action_craf_pack")
        return request.redirect("/odoo/action-craf_label.action_craf_pack/%s" % pack.id)
