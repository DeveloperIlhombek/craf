"""Hikvision ISAPI «HTTP Listening» (push) yozuvlarini o'qish: JSON, multipart (event_log + Picture) va XML."""
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

_logger = logging.getLogger(__name__)

TASHKENT = timezone(timedelta(hours=5))
# majorEventType = 5 (Event): yuz, barmoq izi, karta — qabul; tanilmadi — faqat jurnal
ACCEPT_SUB = {75: "face", 38: "finger", 1: "card", 104: "face", 105: "face"}
REJECT_SUB = {76: "Yuz tanilmadi", 39: "Barmoq izi tanilmadi", 9: "Karta ruxsatsiz"}


def _strip_ns(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _xml_to_dict(elem):
    children = list(elem)
    if not children:
        return (elem.text or "").strip()
    out = {}
    for child in children:
        key = _strip_ns(child.tag)
        value = _xml_to_dict(child)
        if key in out:
            if not isinstance(out[key], list):
                out[key] = [out[key]]
            out[key].append(value)
        else:
            out[key] = value
    return out


def parse_time(value):
    """'2026-10-14T08:01:02+05:00' → UTC naive datetime. Mintaqa yo'q bo'lsa — Toshkent."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)  # +0500 → +05:00
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TASHKENT)
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _bool(value, default=True):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def normalize(data):
    """Bitta hodisa lug'ati → {kind, ...}. kind: event | heartbeat | other."""
    if not isinstance(data, dict):
        return {"kind": "other"}
    if "EventNotificationAlert" in data and isinstance(data["EventNotificationAlert"], dict):
        data = data["EventNotificationAlert"]
    event_type = str(data.get("eventType") or "").strip()
    if event_type.lower() in ("heartbeat", "heartbeat ", "heart_beat"):
        return {"kind": "heartbeat", "mac": data.get("macAddress") or "", "ip": data.get("ipAddress") or ""}
    ace = data.get("AccessControllerEvent")
    if not isinstance(ace, dict):
        return {"kind": "other", "event_type": event_type}
    major = _int(ace.get("majorEventType"))
    sub = _int(ace.get("subEventType"))
    employee_no = str(ace.get("employeeNoString") or ace.get("employeeNo") or "").strip()
    return {
        "kind": "event",
        "major": major,
        "sub": sub,
        "employee_no": employee_no,
        "name": str(ace.get("name") or "").strip(),
        "time": parse_time(data.get("dateTime") or ace.get("time")),
        "serial": _int(ace.get("serialNo")),
        "status": str(ace.get("attendanceStatus") or "").strip(),
        "verify": str(ace.get("currentVerifyMode") or "").strip(),
        "current": _bool(ace.get("currentEvent"), True),
        "mac": data.get("macAddress") or "",
        "ip": data.get("ipAddress") or "",
        "device_name": str(ace.get("deviceName") or "").strip(),
    }


def parse_body(content_type, body, form=None):
    """So'rov tanasi → hodisalar ro'yxati. form — multipart maydonlari {nom: matn}."""
    content_type = (content_type or "").lower()
    payloads = []
    if form:
        for key in ("event_log", "AccessControllerEvent", "EventNotificationAlert"):
            if form.get(key):
                payloads.append(form[key])
        if not payloads:
            payloads.extend(v for v in form.values() if isinstance(v, str) and v.strip()[:1] in ("{", "<"))
    if not payloads and body:
        text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body)
        if "multipart" in content_type and "{" in text:
            # tanani o'zimiz bo'lamiz (werkzeug form bo'sh qolsa)
            for match in re.finditer(r"(\{.*?\})\s*\r?\n--", text, re.S):
                payloads.append(match.group(1))
        else:
            payloads.append(text)
    events = []
    for raw in payloads:
        raw = raw.strip() if isinstance(raw, str) else raw
        if not raw:
            continue
        data = None
        if raw[:1] == "{":
            try:
                data = json.loads(raw)
            except ValueError:
                # ba'zi qurilmalar JSON dan keyin bo'sh joy / qo'shimcha qism qo'yadi
                try:
                    data = json.loads(raw[: raw.rfind("}") + 1])
                except ValueError:
                    data = None
        elif raw[:1] == "<":
            try:
                root = ET.fromstring(raw)
                data = {_strip_ns(root.tag): _xml_to_dict(root)}
            except ET.ParseError:
                data = None
        if data is None:
            events.append({"kind": "other", "error": "o'qib bo'lmadi"})
            continue
        events.append(normalize(data))
    return events
