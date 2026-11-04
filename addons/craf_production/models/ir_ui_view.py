"""Odoo'ning o'zbekcha (va boshqa) tarjimalaridagi buzilgan view ifodalarini tuzatish.

Rasmiy uz.po da ba'zi tarjimonlar kod ifodasini ham tarjima qilgan: «and» → «va», «or» → «yoki»,
«not x» → «x emas», «'» → «‘». Natijada forma ochilmaydi (SyntaxError). Har modul yangilanishida
(data/craf_fix_translations.xml) tarjima qilingan arch dagi buzilgan invisible/readonly/required ifodasi
inglizcha arch dagi mos ifoda bilan almashtiriladi. Tarjima qayta yuklansa ham keyingi yangilanishda tuzaladi.
"""
import ast
import json
import logging
import re
from collections import Counter

from lxml import etree

from odoo import api, models

_logger = logging.getLogger(__name__)

ATTRS = ("invisible", "readonly", "required", "column_invisible")
WORDS = {"va": "and", "yoki": "or", "emas": "not"}
QUOTES = str.maketrans({c: "'" for c in "‘’ʻʼ`´"})


def _ok(expr):
    try:
        ast.parse(expr.strip(), mode="eval")
        return True
    except SyntaxError:
        return False


def _key(expr):
    tokens = re.findall(r"\w+", (expr or "").translate(QUOTES))
    return frozenset(Counter(WORDS.get(t, t) for t in tokens).items())


class IrUiView(models.Model):
    _inherit = "ir.ui.view"

    @api.model
    def _craf_fix_translations(self):
        """Tarjimadagi buzilgan ifodalarni inglizcha asl ifoda bilan almashtiradi. Tuzatilganlar soni."""
        cr = self.env.cr
        cr.execute("SELECT id, name, arch_db FROM ir_ui_view WHERE arch_db IS NOT NULL "
                   "AND (SELECT count(*) FROM jsonb_object_keys(arch_db)) > 1")
        fixed = 0
        for vid, name, arch in cr.fetchall():
            source = arch.get("en_US")
            if not source:
                continue
            try:
                originals = {}
                for el in etree.fromstring(source.encode()).iter():
                    for attr in ATTRS:
                        if el.get(attr) and _ok(el.get(attr)):
                            originals.setdefault((attr, _key(el.get(attr))), set()).add(el.get(attr))
            except etree.XMLSyntaxError:
                continue
            for lang, text in arch.items():
                if lang == "en_US" or not text:
                    continue
                try:
                    root = etree.fromstring(text.encode())
                except etree.XMLSyntaxError:
                    continue
                changed = 0
                for el in root.iter():
                    for attr in ATTRS:
                        expr = el.get(attr)
                        if not expr or _ok(expr):
                            continue
                        match = originals.get((attr, _key(expr)), set())
                        if len(match) == 1:
                            el.set(attr, next(iter(match)))
                            changed += 1
                        else:
                            _logger.warning("Tarjima: %s (%s) %s=\"%s\" — mos asl ifoda topilmadi", name, lang, attr, expr)
                if changed:
                    cr.execute("UPDATE ir_ui_view SET arch_db = jsonb_set(arch_db, %s, %s::jsonb) WHERE id = %s",
                               ["{%s}" % lang, json.dumps(etree.tostring(root, encoding="unicode")), vid])
                    _logger.info("Tarjima tuzatildi: %s (%s) — %s ta ifoda", name, lang, changed)
                    fixed += changed
        if fixed:
            self.env.registry.clear_cache("templates")
            self.invalidate_model(["arch_db"])
        return fixed
