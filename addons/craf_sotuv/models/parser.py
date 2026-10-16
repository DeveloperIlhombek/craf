"""Telegram "Berildi ..." xabarlarini ajratish (Odoo ga bog'liq emas — alohida sinash mumkin).

Xabar namunasi::

    Berildi
    Farxod
    Zavod
    Kraf antrasid
    L 28
    T 20
    Sh1.   23
    Kraf oq
    Z 60
    ZE. 2
    L 33+2dona

Qoidalar:
- "Berildi" (Beriildi, Берилди ...) — yangi sotuv boshlanadi; shu qatordagi qolgan so'z — mijoz
- undan keyingi birinchi bo'sh bo'lmagan qator — mijoz
- raqamsiz qator — sarlavha: joy (Zavod / Parnik / Rohat), seriya va rang (Kraf antrasid, Alusam oq,
  Oq, J306, Termo yolka ...). Sarlavha oldingi seriya/rangni almashtiradi
- raqamli qator — mahsulot: qisqartma + miqdor. "52" — pachka, "17dona" — dona, "33+2dona" — 33 pachka 2 dona
"""
import hashlib
import re
from datetime import datetime

BERILDI_RE = re.compile(r"^\s*(?:b+e+r+i+l*d+i+|б+е+р+и+л*д+и+)\b[\s.,:;!-]*(?P<rest>.*)$", re.I)
STAMP_RE = re.compile(
    r"\[?\s*(?P<d>\d{1,2})[./](?P<m>\d{1,2})[./](?P<y>\d{2,4})[\s,T]+(?P<H>\d{1,2}):(?P<M>\d{2})(?::\d{2})?\s*\]?")
FORWARD_RE = re.compile(r"^\s*\[?(forwarded from|переслано|переслано от|yo'naltirildi|yuborilgan)\b", re.I)
QTY_RE = re.compile(
    r"^(?P<head>.*?)(?P<sep>[\s._:;,=-]*)(?P<q>\d+)"
    r"(?:\s*\+\s*(?P<d>\d+)\s*(?P<du>dona|donna|ta|та|шт|sht|дона)?)?"
    r"\s*(?P<unit>dona|donna|ta|та|шт|sht|дона|pachka|pachk|pach|pch|пачка|пач|p|п)?\.?"
    r"\s*[.,;:)]?\s*(?P<tail>[^\d]*)$", re.I)
LENGTH_RE = re.compile(r"^(?P<n>[56])\s*(?:m|mt|metr|metrli|м|мт|метр)$", re.I)
DONA_UNITS = {"dona", "donna", "ta", "та", "шт", "sht", "дона"}

CYR_FIX = str.maketrans({"ё": "е", "ʼ": "'", "‘": "'", "’": "'", "`": "'"})


def norm(text):
    """Kichik harf, ё→е, ortiqcha bo'shliqlar olib tashlanadi."""
    text = (text or "").translate(CYR_FIX).lower()
    text = text.replace("мм", "mm")
    return re.sub(r"\s+", " ", text).strip()


def compact(text):
    """Qidiruv kaliti: bo'shliq, nuqta, chiziqcha va pastki chiziqsiz ("Sh 1." -> "sh1")."""
    return re.sub(r"[\s._\-:;,'()*]+", "", norm(text))


def tokens(text):
    """'Z 7.1_' -> ['z', '7.1']; 'Sh1.' -> ['sh1']."""
    out = []
    for raw in re.split(r"[\s_;:,()*/]+", norm(text)):
        tok = raw.strip(".-'")
        if tok:
            out.append(tok)
    return out


def source_key(date_str, text):
    base = "%s|%s" % (date_str or "", "\n".join(norm(l) for l in (text or "").splitlines() if l.strip()))
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:20]


# --------------------------------------------------------------------------- bloklarga bo'lish
def split_blocks(text, default_date=None):
    """Matnni sotuv bloklariga bo'ladi. [(date_str|None, [qatorlar])].

    Telegram Desktop dan nusxa: "СУЛТОН, [06.10.2026 12:43]" — sana shu blokka yoziladi."""
    blocks = []
    current = None
    pending_date = default_date
    for line in (text or "").splitlines():
        stripped = line.strip()
        if FORWARD_RE.match(stripped):
            continue
        stamp = STAMP_RE.search(stripped)
        if stamp and len(STAMP_RE.sub("", stripped).strip(" ,:-[]")) < 40 and not BERILDI_RE.match(stripped):
            # "Ism, [06.10.2026 12:43]" — keyingi blok sanasi
            y = int(stamp.group("y"))
            y = y + 2000 if y < 100 else y
            try:
                pending_date = datetime(y, int(stamp.group("m")), int(stamp.group("d")),
                                        int(stamp.group("H")), int(stamp.group("M"))).strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
            if current is not None and len(current[1]) > 1:
                current = None
            continue
        if BERILDI_RE.match(stripped):
            current = [pending_date, [stripped]]
            blocks.append(current)
            pending_date = default_date
            continue
        if current is None:
            if not stripped:
                continue
            # "Berildi" siz matn — bitta blok sifatida
            current = [pending_date, ["Berildi"]]
            blocks.append(current)
            pending_date = default_date
        current[1].append(stripped)
    return [(d, lines) for d, lines in blocks if any(l.strip() for l in lines[1:]) or BERILDI_RE.match(lines[0]).group("rest")]


# --------------------------------------------------------------------------- lug'at
class Dictionary:
    """Qisqartmalar lug'ati.

    entries: [{"key": compact, "kind": item|group|location|product|partner|ignore, ...}]
      item:     type, series (["Бал"] yoki []), filter (["термо"])
      group:    series, color (rang kodi), family_type, filter, length
      location: location_id
      product:  product_id (o'rgatilgan: key = learn_key)
      partner:  partner_id (o'rgatilgan: key = compact(mijoz nomi))
    """

    def __init__(self, entries):
        self.by_kind = {}
        for e in entries:
            self.by_kind.setdefault(e["kind"], {})[e["key"]] = e

    def get(self, kind, key):
        return self.by_kind.get(kind, {}).get(key)

    def group_or_location(self, key):
        return self.get("location", key) or self.get("group", key) or self.get("ignore", key)

    def match_header(self, toks):
        """Sarlavha qatori: barcha so'zlar ma'lum bo'lsa (joy, seriya, rang) -> (topilganlar, noma'lumlar)."""
        found, unknown = [], []
        i = 0
        while i < len(toks):
            hit = None
            for j in range(len(toks), i, -1):
                key = "".join(toks[i:j])
                entry = self.group_or_location(key)
                if entry:
                    hit = (entry, j)
                    break
            if hit:
                found.append(hit[0])
                i = hit[1]
            else:
                m = LENGTH_RE.match(toks[i])
                if m:
                    found.append({"kind": "group", "key": toks[i], "length": float(m.group("n")), "_length_only": True})
                else:
                    unknown.append(toks[i])
                i += 1
        return found, unknown

    def match_item(self, toks):
        """[tokenlar] -> (item_entry|None, qolgan tokenlar)."""
        for j in range(len(toks), 0, -1):
            entry = self.get("item", "".join(toks[:j]))
            if entry:
                return entry, toks[j:]
        if toks:
            m = re.match(r"^([a-zа-я]+)(\d[\w.]*)$", toks[0])
            if m:
                entry = self.get("item", m.group(1))
                if entry:
                    return entry, [m.group(2)] + toks[1:]
        return None, toks


def parse_qty(line, dictionary):
    """'L 33+2dona' -> {'head': 'L', 'packs': 33, 'extra': 2}; raqamli qator bo'lmasa None."""
    m = QTY_RE.match(line.strip())
    if not m:
        return None
    head = m.group("head").strip()
    if not re.search(r"[a-zа-яё]", head, re.I):
        return None
    glued = not m.group("sep") and head and head[-1].isalpha()
    if glued:
        # "T36", "Tb3" — faqat qisqartma ma'lum bo'lsa; "J306" — rang (sarlavha)
        if not dictionary.get("item", compact(head)):
            return None
    q = int(m.group("q"))
    d = int(m.group("d")) if m.group("d") else 0
    unit = (m.group("unit") or "").lower()
    if m.group("d") is not None:
        packs, extra = q, d
    elif unit in DONA_UNITS:
        packs, extra = 0, q
    else:
        packs, extra = q, 0
    return {"head": head, "packs": packs, "extra": extra, "tail": (m.group("tail") or "").strip(" .,;:")}


def parse_block(lines, dictionary, default_location=None):
    """Bitta "Berildi" bloki -> {'customer', 'location', 'lines': [...], 'notes': [...]}."""
    first = BERILDI_RE.match(lines[0])
    customer = (first.group("rest") if first else "").strip(" ,.-:")
    body = lines[1:]
    result = {"customer": customer, "location": default_location, "lines": [], "notes": []}
    ctx = {"series": [], "color": None, "family_type": None, "filter": [], "length": None, "label": ""}
    for raw in body:
        text = raw.strip()
        if not text:
            continue
        if not result["customer"]:
            result["customer"] = text.strip(" ,.-:")
            continue
        qty = parse_qty(text, dictionary)
        toks = tokens(text)
        if qty is None:
            found, unknown = dictionary.match_header(toks)
            locations = [e for e in found if e["kind"] == "location"]
            groups = [e for e in found if e["kind"] == "group"]
            if locations:
                result["location"] = locations[-1]["location_id"]
            if groups:
                ctx = {"series": [], "color": None, "family_type": None, "filter": [], "length": None,
                       "label": text}
                for g in groups:
                    if g.get("series"):
                        ctx["series"] = list(g["series"])
                    if g.get("color"):
                        ctx["color"] = g["color"]
                    if g.get("family_type"):
                        ctx["family_type"] = g["family_type"]
                        ctx["filter"] = list(g.get("filter") or [])
                    if g.get("length"):
                        ctx["length"] = g["length"]
            if unknown:
                result["notes"].append("Tushunilmadi: «%s»" % text)
            continue
        result["lines"].append(_item_line(text, qty, ctx, dictionary))
    return result


def _item_line(raw, qty, ctx, dictionary):
    toks = tokens(qty["head"])
    series = list(ctx["series"])
    color = ctx["color"]
    length = ctx["length"]
    rest = []
    # qatordagi seriya / rang / uzunlik so'zlari ("L oq 20", "Z 5m 10")
    for tok in toks:
        g = dictionary.get("group", tok)
        lm = LENGTH_RE.match(tok)
        if g and not g.get("family_type"):
            if g.get("series"):
                series = list(g["series"])
            if g.get("color"):
                color = g["color"]
        elif lm:
            length = float(lm.group("n"))
        else:
            rest.append(tok)
    note = []
    if qty["tail"]:
        tail_found, tail_unknown = dictionary.match_header(tokens(qty["tail"]))
        for g in tail_found:
            if g["kind"] == "group" and g.get("color"):
                color = g["color"]
        if tail_unknown:
            note.append(qty["tail"])
        series_tail = [g for g in tail_found if g["kind"] == "group" and g.get("series")]
    else:
        series_tail = []
    item, spec = dictionary.match_item(rest)
    family_type = ctx["family_type"]
    filters = list(ctx["filter"])
    item_type = None
    if family_type:
        # "Termo yolka" sarlavhasi ostida: "Z 7.1" — Ёлка Термо Z ... 7.1mm
        filters += rest
        item_type = family_type
    elif item:
        item_type = item.get("type")
        filters += list(item.get("filter") or [])
        filters += spec
        if item.get("series"):
            series = list(item["series"])  # TB = T Бал: qisqartmaning o'z seriyasi ustun
        elif series_tail:
            series = list(series_tail[-1]["series"])
    abbr = compact(" ".join(rest)) or compact(qty["head"])
    learn_key = "|".join([
        abbr, ",".join(series), str(color or ""), (family_type or "") + ":" + ",".join(ctx["filter"]),
        str(int(length)) if length else "",
    ])
    return {
        "raw": raw,
        "abbr": abbr,
        "type": item_type,
        "series": series,
        "color": color,
        "filter": filters,
        "length": length,
        "packs": qty["packs"],
        "extra": qty["extra"],
        "known": bool(item or family_type),
        "series_strict": bool(item and item.get("series") and not family_type),
        "learn_key": learn_key,
        "note": " ".join(note),
    }


def parse_text(text, dictionary, default_location=None, default_date=None):
    out = []
    for date_str, lines in split_blocks(text, default_date):
        block = parse_block(lines, dictionary, default_location)
        block["date"] = date_str
        block["raw"] = "\n".join(lines)
        block["key"] = source_key(date_str, block["raw"])
        out.append(block)
    return out
