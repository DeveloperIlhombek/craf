import base64
import io
import json

from PIL import Image
from werkzeug.exceptions import NotFound

from odoo import http
from odoo.exceptions import AccessDenied, AccessError, UserError
from odoo.http import content_disposition, request

from odoo.addons.craf_pul.controllers.main import CrafPulController
from odoo.addons.portal.controllers.web import Home as PortalHome

from ..models.res_partner import norm_phone

SW = """self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
    if (e.request.mode === "navigate") {
        e.respondWith(fetch(e.request).catch(() => new Response(
            "<meta charset=utf-8><meta name=viewport content='width=device-width'>"
            + "<p style='font:18px sans-serif;padding:24px'>Internet yo'q. Aloqa tiklangach sahifani yangilang.</p>",
            {headers: {"Content-Type": "text/html; charset=utf-8"}})));
    }
});
"""


def _is_dealer(user):
    return user.share and user.partner_id.sudo().commercial_partner_id.craf_is_diller


class CrafDillerHome(PortalHome):

    def _login_redirect(self, uid, redirect=None):
        if not redirect and _is_dealer(request.env["res.users"].browse(uid)):
            redirect = "/diller"
        return super()._login_redirect(uid, redirect=redirect)

    @http.route()
    def index(self, *args, **kw):
        if request.session.uid and _is_dealer(request.env.user):
            return request.redirect("/diller")
        return super().index(*args, **kw)


class CrafDillerController(http.Controller):

    def _service(self):
        return request.env["craf.diller"].sudo()

    def _dealer(self):
        """Fayl yo'llari uchun: (foydalanuvchi, diller) yoki 404."""
        try:
            return self._service()._me()
        except (AccessError, UserError):
            raise NotFound() from None

    # ------------------------------------------------------------------ sahifa
    @http.route("/diller", type="http", auth="public", sitemap=False)
    def diller(self, **kwargs):
        user = request.env.user
        if user._is_public():
            return request.redirect("/diller/login")
        if not _is_dealer(user):
            return request.redirect("/odoo")
        return request.render("craf_diller.app", {})

    def _auth(self, values):
        return request.render("craf_diller.auth", dict({"mode": "login", "error": "", "login": ""}, **values))

    @http.route("/diller/login", type="http", auth="public", methods=["GET", "POST"], sitemap=False)
    def diller_login(self, login="", password="", **kwargs):
        if request.httprequest.method == "GET":
            if not request.env.user._is_public():
                return request.redirect("/diller")
            return self._auth({})
        phone = norm_phone(login)
        credential = {"login": phone if len(phone) == 12 else login.strip(), "password": password, "type": "password"}
        try:
            request.session.authenticate(request.env, credential)
        except AccessDenied:
            return self._auth({"error": "Telefon yoki parol noto'g'ri (ko'p urinishda vaqtincha to'xtatiladi).",
                               "login": login})
        return request.redirect("/diller")

    @http.route("/diller/taklif/<string:token>", type="http", auth="public", methods=["GET", "POST"], sitemap=False)
    def diller_invite(self, token, password="", password2="", **kwargs):
        user = request.env["res.users"]._craf_invite_user(token)
        if not user:
            return self._auth({"error": "Havola eskirgan yoki ishlatilgan. Yangi havola so'rang."})
        values = {"mode": "invite", "name": user.name, "phone": user.login, "token": token}
        if request.httprequest.method == "GET":
            return self._auth(values)
        if len(password) < 8:
            return self._auth(dict(values, error="Parol kamida 8 belgi bo'lsin."))
        if password != password2:
            return self._auth(dict(values, error="Parollar bir xil emas."))
        user.write({"password": password, "craf_invite_hash": False, "craf_invite_expiry": False})
        request.session.authenticate(request.env, {"login": user.login, "password": password, "type": "password"})
        return request.redirect("/diller")

    @http.route("/diller/api/<string:method>", type="jsonrpc", auth="user", sitemap=False)
    def diller_api(self, method, **params):
        return self._service()._craf_call(method, params)

    # ------------------------------------------------------------------ fayllar
    @http.route("/diller/rasm/<int:product_id>", type="http", auth="user", sitemap=False, readonly=True)
    def diller_image(self, product_id, **kwargs):
        self._dealer()
        service = self._service()
        try:
            product = service._product(product_id)
        except UserError:
            raise NotFound() from None
        section = product.product_tmpl_id.craf_section_id
        record, field = (product, "image_512") if product.image_128 else (section, "drawing")
        if not record[field]:
            raise NotFound()
        stream = request.env["ir.binary"].sudo()._get_image_stream_from(record, field, width=320, height=320)
        return stream.get_response(max_age=3600)

    @http.route("/diller/foto/<int:att_id>", type="http", auth="user", sitemap=False, readonly=True)
    def diller_photo(self, att_id, size=None, **kwargs):
        _user, dealer = self._dealer()
        env = request.env(su=True)
        att = env["ir.attachment"].browse(att_id).exists()
        if not att or not env["sale.order"].search_count(
                [("craf_truck_photo_ids", "in", att.ids), ("partner_id", "=", dealer.id)]):
            raise NotFound()
        px = 256 if size == "256" else 0
        return env["ir.binary"]._get_image_stream_from(att, "raw", width=px, height=px).get_response(max_age=86400)

    @http.route("/diller/faktura/<int:move_id>", type="http", auth="user", sitemap=False)
    def diller_invoice(self, move_id, **kwargs):
        _user, dealer = self._dealer()
        env = request.env(su=True)
        move = env["account.move"].browse(move_id).exists()
        if not move or move.state != "posted" or move.move_type not in ("out_invoice", "out_refund") \
                or move.partner_id.commercial_partner_id != dealer:
            raise NotFound()
        pdf, _kind = env["ir.actions.report"]._render_qweb_pdf("account.account_invoices", move.ids)
        return self._pdf(pdf, "%s.pdf" % (move.name or "faktura").replace("/", "-"))

    def _pdf(self, data, name):
        return request.make_response(data, headers=[
            ("Content-Type", "application/pdf"), ("Content-Disposition", content_disposition(name))])

    @http.route("/diller/akt.pdf", type="http", auth="user", sitemap=False)
    def diller_akt_pdf(self, date_from=None, date_to=None, **kwargs):
        _user, dealer = self._dealer()
        env = request.env(su=True)
        data = {"date_from": date_from, "date_to": date_to}
        pdf, _kind = env["ir.actions.report"]._render_qweb_pdf("craf_diller.action_report_akt", dealer.ids, data=data)
        return self._pdf(pdf, "Akt-sverka.pdf")

    @http.route("/diller/akt.xlsx", type="http", auth="user", sitemap=False)
    def diller_akt_xlsx(self, date_from=None, date_to=None, **kwargs):
        _user, dealer = self._dealer()
        detail = self._service().env["craf.pul"].partner_detail(dealer.id, "customer", date_from or False,
                                                                date_to or False)
        return CrafPulController()._craf_akt_xlsx(detail)

    # ------------------------------------------------------------------ PWA
    @http.route("/diller/manifest.webmanifest", type="http", auth="public", sitemap=False, readonly=True)
    def diller_manifest(self, **kwargs):
        body = {
            "name": "CRAF Diller", "short_name": "CRAF", "start_url": "/diller", "scope": "/diller",
            "display": "standalone", "background_color": "#ffffff", "theme_color": "#1f3a5f", "lang": "uz",
            "icons": [{"src": "/diller/icon/%s.png" % s, "sizes": "%sx%s" % (s, s), "type": "image/png"}
                      for s in (192, 512)],
        }
        return request.make_response(json.dumps(body), headers=[("Content-Type", "application/manifest+json")])

    @http.route("/diller/sw.js", type="http", auth="public", sitemap=False, readonly=True)
    def diller_sw(self, **kwargs):
        return request.make_response(SW, headers=[
            ("Content-Type", "text/javascript"), ("Service-Worker-Allowed", "/diller"),
            ("Cache-Control", "no-cache")])

    @http.route("/diller/icon/<int:size>.png", type="http", auth="public", sitemap=False, readonly=True)
    def diller_icon(self, size, **kwargs):
        if size not in (192, 512):
            raise NotFound()
        canvas = Image.new("RGB", (size, size), "#ffffff")
        logo = request.env.company.sudo().logo
        if logo:
            image = Image.open(io.BytesIO(base64.b64decode(logo))).convert("RGBA")
            image.thumbnail((int(size * 0.8), int(size * 0.8)))
            canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2), image)
        out = io.BytesIO()
        canvas.save(out, "PNG")
        return request.make_response(out.getvalue(), headers=[("Content-Type", "image/png"),
                                                              ("Cache-Control", "public, max-age=86400")])
