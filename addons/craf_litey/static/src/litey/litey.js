// Craf → Литейка: telefon birinchi (mobile first) sahifa.
// Varaqlar: Qoldiq (materiallar, CRUD) · Kunlik (Excel Лист1) · Hujjatlar (plavka, kirim, ko'chirish, sanash, tuzatish).
// Hamma yangi hujjat va material pastdan chiquvchi varaqda (sheet) yoziladi; kompyuterda varaq markazda ochiladi.
import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const API = "craf.litey.hisobot";
const SUM_RE = /^[+-]?\d+(?:\.\d+)?(?:[+-]\d+(?:\.\d+)?)*$/;
const KIND_ICON = {
    plavka: "fa-fire",
    kirim: "fa-truck",
    kochirish: "fa-exchange",
    chiqim: "fa-sign-out",
    sanash: "fa-check-square-o",
    tuzatish: "fa-pencil-square-o",
};
const MOVE_KINDS = ["kirim", "chiqish_plavka", "chiqish_boshqa", "sarf_plavka", "sarf_boshqa", "tuzatish", "boshqa"];
const WEEKDAYS = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"];

function addDays(iso, n) {
    const d = new Date(iso + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
}
function dm(iso) {
    return iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}` : "";
}
function dmy(iso) {
    return iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : "";
}

/** Daftar yozuvi: "993+600+351" → 1944; bo'sh → null; noto'g'ri → NaN. */
export function parseSum(text) {
    const s = String(text || "").replace(/[\s ]/g, "").replace(/,/g, ".").replace(/^=/, "");
    if (!s) {
        return null;
    }
    if (!SUM_RE.test(s)) {
        return NaN;
    }
    return Math.round((s.match(/[+-]?\d+(?:\.\d+)?/g) || []).reduce((a, t) => a + parseFloat(t), 0) * 1000) / 1000;
}

export class CrafLitey extends Component {
    static template = "craf_litey.Litey";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.opts = null; // form_options (kirim / ko'chirish / sanash)
        this.matOpts = null; // material_options
        this.state = useState({
            data: null,
            loading: true,
            tab: "qoldiq",
            from: false,
            to: false,
            q: "",
            filter: "all",
            day: false,
            docs: null,
            docKind: "all",
            docDrafts: false,
            docView: "list",
            sheet: null,
            busy: false,
        });
        this.onKey = (ev) => {
            if (ev.key === "Escape" && this.state.sheet && !this.state.busy) {
                this.closeSheet();
            }
        };
        window.addEventListener("keydown", this.onKey);
        onWillUnmount(() => window.removeEventListener("keydown", this.onKey));
        onWillStart(async () => {
            const ctx = (this.props.action && this.props.action.context) || {};
            if (["qoldiq", "kunlik", "hujjat"].includes(ctx.craf_tab)) {
                this.state.tab = ctx.craf_tab;
            }
            await this.load();
        });
    }

    // ================================================================ yuklash
    async load(from, to) {
        this.state.loading = true;
        const f = from === undefined ? this.state.from : from;
        const t = to === undefined ? this.state.to : to;
        try {
            const data = await this.orm.call(API, "get_data", [f || false, t || false]);
            this.state.data = data;
            this.state.from = data.date_from;
            this.state.to = data.date_to;
            if (!this.state.day || this.state.day < data.date_from || this.state.day > data.date_to) {
                this.state.day = data.date_to;
            }
            this.state.docs = null;
            if (this.state.tab === "hujjat") {
                await this.loadDocs();
            }
        } finally {
            this.state.loading = false;
        }
    }
    async loadDocs() {
        this.state.docs = await this.orm.call(API, "documents", [this.state.from, this.state.to]);
    }
    async refresh() {
        this.opts = null;
        await this.load();
    }
    async setTab(tab) {
        if (this.state.tab !== tab) {
            const root = document.querySelector(".o_craf_litey");
            if (root) {
                root.scrollTo(0, 0);
            }
        }
        this.state.tab = tab;
        if (tab === "hujjat" && !this.state.docs) {
            await this.loadDocs();
        }
    }
    async ensureOpts(force = false) {
        if (!this.opts || force) {
            this.opts = await this.orm.call(API, "form_options", []);
        }
        return this.opts;
    }

    // ================================================================ format
    fmt(value, digits = 1) {
        const v = Number(value || 0);
        if (Math.abs(v) < 0.0005) {
            return "—";
        }
        return v.toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
    }
    num(value, digits = 1) {
        return Number(value || 0).toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
    }
    signed(value, digits = 1) {
        const v = Number(value || 0);
        if (Math.abs(v) < 0.0005) {
            return "0";
        }
        return (v > 0 ? "+" : "−") + this.num(Math.abs(v), digits);
    }
    errorText(e) {
        return (e && e.data && e.data.message) || (e && e.message) || String(e);
    }
    dmy(iso) {
        return dmy(iso);
    }
    kindIcon(kind) {
        return KIND_ICON[kind] || "fa-file-o";
    }
    lossClass(state) {
        return { ok: "cl-ok", warn: "cl-warn", bad: "cl-bad" }[state] || "cl-muted";
    }
    get kpiLossState() {
        const k = this.state.data.kpi;
        if (!k.metal) {
            return "none";
        }
        if (k.loss_pct < 0 || k.loss_pct > 5) {
            return "bad";
        }
        return k.loss_pct > 3 ? "warn" : "ok";
    }
    get periodLabel() {
        const { from, to, data } = this.state;
        if (!from) {
            return "";
        }
        if (from === to) {
            return from === data.today ? "Bugun" : dmy(from);
        }
        return `${dm(from)} – ${dm(to)}`;
    }

    // ================================================================ davr
    preset(kind) {
        const today = this.state.data.today;
        const ranges = {
            today: [today, today],
            yesterday: [addDays(today, -1), addDays(today, -1)],
            7: [addDays(today, -6), today],
            30: [addDays(today, -29), today],
            month: [today.slice(0, 8) + "01", today],
            prev: [addDays(today.slice(0, 8) + "01", -1).slice(0, 8) + "01", addDays(today.slice(0, 8) + "01", -1)],
        };
        const [f, t] = ranges[kind];
        this.closeSheet();
        this.load(f, t);
    }
    applyPeriod() {
        const s = this.state.sheet;
        if (!s.from || !s.to) {
            return;
        }
        this.closeSheet();
        this.load(s.from, s.to);
    }
    shift(dir) {
        const span = Math.round((new Date(this.state.to) - new Date(this.state.from)) / 86400000) + 1;
        this.load(addDays(this.state.from, dir * span), addDays(this.state.to, dir * span));
    }

    // ================================================================ Qoldiq varag'i
    get materials() {
        const { q, filter, data } = this.state;
        const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
        return data.movement.filter((r) => {
            if (filter === "metal" && r.kind !== "metal") {
                return false;
            }
            if (filter === "aux" && r.kind !== "aux") {
                return false;
            }
            if (filter === "low" && !(r.low || r.negative)) {
                return false;
            }
            if (filter === "active" && !MOVE_KINDS.some((k) => Math.abs(r[k]) > 0.0005)) {
                return false;
            }
            const hay = `${r.excel_name} ${r.name} ${r.code}`.toLowerCase();
            return words.every((w) => hay.includes(w));
        });
    }
    clearFilter() {
        this.state.q = "";
        this.state.filter = "all";
    }
    get alertCount() {
        return this.state.data.movement.filter((r) => r.low || r.negative).length;
    }
    level(r) {
        // Qoldiq darajasi: minimal qoldiqning 3 barobari = to'la. Minimal belgilanmagan bo'lsa — ko'rsatilmaydi.
        if (!r.min_qty) {
            return null;
        }
        return Math.max(0, Math.min(100, (r.closing / (r.min_qty * 3)) * 100));
    }
    periodIn(r) {
        return r.kirim + r.chiqish_plavka + r.chiqish_boshqa;
    }
    periodOut(r) {
        return r.sarf_plavka + r.sarf_boshqa;
    }
    get materialTotals() {
        const rows = this.state.data.movement.filter((r) => r.uom === "kg");
        const t = {};
        for (const k of ["opening", "kirim", "chiqish_plavka", "chiqish_boshqa", "sarf_plavka", "sarf_boshqa", "closing"]) {
            t[k] = rows.reduce((s, r) => s + r[k], 0);
        }
        t.tuzatish = rows.reduce((s, r) => s + r.tuzatish + r.boshqa, 0);
        return t;
    }
    goStale() {
        this.state.docDrafts = true;
        this.state.docKind = "plavka";
        this.setTab("hujjat");
    }

    // ================================================================ Kunlik varag'i
    get dayRows() {
        const d = this.state.data;
        const i = d.days.findIndex((x) => x.date === this.state.day);
        if (i < 0) {
            return [];
        }
        return d.matrix.map((row) => {
            const value = row.values[i];
            let delta = null;
            if (row.kind === "balance") {
                const prev = i > 0 ? row.values[i - 1] : null;
                delta = prev === null ? null : value - prev;
            }
            return { ...row, value, delta };
        });
    }
    dayChipLabel(day) {
        return WEEKDAYS[day.weekday];
    }

    // ================================================================ Hujjatlar varag'i
    get docList() {
        const docs = this.state.docs;
        if (!docs) {
            return [];
        }
        return docs.docs.filter(
            (d) =>
                (this.state.docKind === "all" || d.kind === this.state.docKind) &&
                (!this.state.docDrafts || d.state === "draft" || d.stale)
        );
    }
    get docGroups() {
        const groups = [];
        let current = null;
        for (const d of this.docList) {
            if (!current || current.date !== d.date) {
                current = { date: d.date, label: dmy(d.date), weekday: WEEKDAYS[(new Date(d.date).getUTCDay() + 6) % 7], docs: [] };
                groups.push(current);
            }
            current.docs.push(d);
        }
        return groups;
    }
    setDocKind(kind) {
        this.state.docKind = kind;
        if (kind !== "plavka" && this.state.docView === "daftar") {
            this.state.docView = "list";
        }
    }
    meltQty(melt, col) {
        return melt.qty[String(col.product_id)] || 0;
    }
    meltText(melt, col) {
        return melt.text[String(col.product_id)] || "";
    }

    // ================================================================ varaqlar (sheet)
    openSheet(sheet) {
        this.state.sheet = sheet;
    }
    closeSheet() {
        this.state.sheet = null;
    }
    openPeriod() {
        this.openSheet({ type: "period", from: this.state.from, to: this.state.to });
    }
    openNew() {
        this.openSheet({ type: "new" });
    }
    openMenu() {
        this.openSheet({ type: "menu" });
    }
    async run(fn) {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        const sheet = this.state.sheet;
        if (sheet) {
            sheet.error = "";
        }
        try {
            return await fn();
        } catch (e) {
            if (sheet && this.state.sheet === sheet) {
                // varaq ochiq bo'lsa — xato tugma yonida, varaq ichida ko'rinadi
                sheet.error = this.errorText(e);
            } else {
                this.notification.add(this.errorText(e), { type: "danger", sticky: true, title: "Bajarilmadi" });
            }
        } finally {
            this.state.busy = false;
        }
    }
    confirm(title, body, confirmLabel, onConfirm) {
        this.dialog.add(ConfirmationDialog, {
            title,
            body,
            confirmLabel,
            cancelLabel: "Yo'q",
            confirm: onConfirm,
            cancel: () => {},
        });
    }

    // ---------------------------------------------------------------- material: ko'rish
    async openMaterial(row) {
        const id = row.product_id;
        this.openSheet({ type: "material", loading: true, row, m: null });
        await this.run(async () => {
            const m = await this.orm.call(API, "material_detail", [id]);
            if (this.state.sheet && this.state.sheet.type === "material") {
                this.state.sheet.m = m;
                this.state.sheet.loading = false;
            }
        });
    }
    openMoves(productId) {
        this.closeSheet();
        this.orm
            .call(API, "action_open_moves", [productId, this.state.from, this.state.to])
            .then((action) => this.actionService.doAction(action));
    }

    // ---------------------------------------------------------------- material: forma
    async openMaterialForm(m = null) {
        await this.run(async () => {
            this.matOpts = await this.orm.call(API, "material_options", []);
            const o = this.matOpts;
            const kg = (o.uoms.find((u) => u.label === "kg") || o.uoms[0] || {}).id;
            this.openSheet({
                type: "matform",
                o,
                f: m
                    ? {
                          product_id: m.product_id,
                          name: m.name,
                          code: m.code,
                          kind: m.kind,
                          uom_id: m.uom_id,
                          melt: m.melt,
                          min_qty: m.min_qty || "",
                          location_id: m.location_id || o.litey_location_id,
                          excel_name: m.excel_name,
                          name_1c: m.name_1c,
                          can_delete: m.can_delete,
                          on_hand: m.on_hand,
                          uom: m.uom,
                      }
                    : {
                          product_id: false,
                          name: "",
                          code: "",
                          kind: "metal",
                          uom_id: kg,
                          melt: true,
                          min_qty: "",
                          location_id: o.litey_location_id,
                          excel_name: "",
                          name_1c: "",
                      },
                more: Boolean(m && (m.excel_name || m.name_1c)),
            });
        });
    }
    matCodePlaceholder() {
        const s = this.state.sheet;
        return s.f.product_id ? "" : s.o.next_codes[s.f.kind];
    }
    async saveMaterial() {
        const f = this.state.sheet.f;
        if (!f.name.trim()) {
            this.notification.add("Material nomini yozing", { type: "warning" });
            return;
        }
        await this.run(async () => {
            const res = await this.orm.call(API, "material_save", [{ ...f, min_qty: parseFloat(String(f.min_qty).replace(",", ".")) || 0 }]);
            this.notification.add(`${res.name} (${res.code}) ${f.product_id ? "saqlandi" : "qo'shildi"}`, { type: "success" });
            this.closeSheet();
            await this.refresh();
        });
    }
    removeMaterial(m) {
        const del = m.can_delete;
        const body = del
            ? `«${m.name}» hech bir hujjatda ishlatilmagan — butunlay o'chiriladi.`
            : `«${m.name}» hujjatlarda ishlatilgan, shuning uchun o'chirilmaydi: Литейка ro'yxatidan chiqariladi. ` +
              `Mahsulot, qoldig'i (${this.num(m.on_hand, 2)} ${m.uom}) va tarixi Inventarizatsiya da qoladi; keyin qaytarish mumkin.`;
        this.confirm(del ? "Materialni o'chirish" : "Ro'yxatdan chiqarish", body, del ? "O'chirish" : "Chiqarish", () =>
            this.run(async () => {
                const res = await this.orm.call(API, "material_remove", [m.product_id]);
                this.notification.add(
                    res.result === "deleted" ? `${res.name} o'chirildi` : `${res.name} Литейка ro'yxatidan chiqarildi`,
                    { type: "success" }
                );
                this.closeSheet();
                await this.refresh();
            })
        );
    }
    async openHidden() {
        await this.run(async () => {
            const rows = await this.orm.call(API, "material_hidden", []);
            this.openSheet({ type: "hidden", rows });
        });
    }
    async restoreMaterial(m) {
        await this.run(async () => {
            const res = await this.orm.call(API, "material_restore", [m.product_id]);
            this.notification.add(`${res.name} Литейка ro'yxatiga qaytarildi`, { type: "success" });
            this.state.sheet.rows = this.state.sheet.rows.filter((r) => r.product_id !== m.product_id);
            await this.refresh();
        });
    }

    // ---------------------------------------------------------------- yangi: menyu
    newMelt() {
        this.closeSheet();
        this.actionService.doAction(
            {
                type: "ir.actions.act_window",
                name: "Plavka",
                res_model: "craf.foundry.melt",
                views: [[false, "form"]],
                context: { default_date: this.state.data.today },
            },
            { onClose: () => this.refresh() }
        );
    }
    materialName(id) {
        const m = this.opts && this.opts.materials.find((x) => x.id === Number(id));
        return m ? m.short : "";
    }
    materialById(id) {
        return (this.opts && this.opts.materials.find((x) => x.id === Number(id))) || null;
    }
    get materialGroups() {
        const kirim = this.state.sheet && this.state.sheet.type === "kirim";
        // press chiqindisi (питак, brak, briket) sotib olinmaydi — kirimda ko'rinmaydi
        const mats = ((this.opts && this.opts.materials) || []).filter((m) => !(kirim && m.press_waste));
        return [
            { label: "Metall (shixta)", items: mats.filter((m) => m.kind === "metal") },
            { label: "Qo'shimcha va sarf buyumlari", items: mats.filter((m) => m.kind === "aux") },
        ].filter((g) => g.items.length);
    }
    isSel(line, m) {
        return Number(line.product_id) === m.id;
    }
    onLineProduct(line, ev) {
        line.product_id = ev.target.value ? Number(ev.target.value) : "";
    }
    lineValue(line) {
        return parseSum(line.text);
    }
    lineBad(line) {
        return Number.isNaN(parseSum(line.text));
    }

    // ---------------------------------------------------------------- kirim
    async openKirim(productId = false) {
        await this.run(async () => {
            const o = await this.ensureOpts(true);
            const line = this.newKirimLine(productId);
            this.openSheet({
                type: "kirim",
                f: { date: o.today, vehicle: "", partner_name: "", location_id: o.litey_location_id, note: "" },
                lines: [line],
            });
        });
    }
    newKirimLine(productId = false) {
        const m = productId ? this.materialById(productId) : null;
        return { key: Math.random().toString(36).slice(2), product_id: productId || "", text: "", price: m && m.last_price ? String(m.last_price) : "" };
    }
    onKirimProduct(line, ev) {
        line.product_id = ev.target.value ? Number(ev.target.value) : "";
        const m = this.materialById(line.product_id);
        if (m && !line.price && m.last_price) {
            line.price = String(m.last_price);
        }
    }
    addLine() {
        const s = this.state.sheet;
        s.lines.push(s.type === "kirim" ? this.newKirimLine() : { key: Math.random().toString(36).slice(2), product_id: "", text: "" });
    }
    removeLine(line) {
        const s = this.state.sheet;
        s.lines = s.lines.filter((l) => l !== line);
        if (!s.lines.length) {
            this.addLine();
        }
    }
    get kirimTotals() {
        const s = this.state.sheet;
        let kg = 0;
        let sum = 0;
        for (const l of s.lines) {
            const v = parseSum(l.text);
            if (!v || Number.isNaN(v)) {
                continue;
            }
            const m = this.materialById(l.product_id);
            if (m && m.uom === "kg") {
                kg += v;
            }
            sum += v * (parseFloat(String(l.price || "0").replace(/\s/g, "").replace(",", ".")) || 0);
        }
        return { kg, sum };
    }
    async saveKirim() {
        const s = this.state.sheet;
        const lines = s.lines.filter((l) => l.product_id && l.text.trim());
        if (!lines.length) {
            this.notification.add("Material tanlang va miqdorini yozing", { type: "warning" });
            return;
        }
        if (lines.some((l) => this.lineBad(l))) {
            this.notification.add("Miqdorni raqam va + bilan yozing, masalan 1381+2527", { type: "warning" });
            return;
        }
        await this.run(async () => {
            const res = await this.orm.call(API, "create_receipt", [
                {
                    ...s.f,
                    lines: lines.map((l) => ({
                        product_id: l.product_id,
                        text: l.text,
                        price: parseFloat(String(l.price || "0").replace(/\s/g, "").replace(",", ".")) || 0,
                    })),
                },
            ]);
            this.notification.add(`${res.name}: ${res.summary} kirim qilindi`, { type: "success" });
            this.closeSheet();
            await this.refresh();
        });
    }

    // ---------------------------------------------------------------- ko'chirish
    async openTransfer(productId = false, fromId = false) {
        await this.run(async () => {
            const o = await this.ensureOpts(true);
            const lit = o.litey_location_id;
            let src = fromId || false;
            if (!src && productId) {
                const m = this.materialById(productId);
                const other = m && Object.entries(m.stock).filter(([loc, q]) => Number(loc) !== lit && q > 0)
                    .sort((a, b) => b[1] - a[1])[0];
                src = other ? Number(other[0]) : false;
            }
            const fallback = o.locations.find((l) => l.id === o.transfer_src_id) || o.locations.find((l) => l.id !== lit);
            this.openSheet({
                type: "transfer",
                f: { date: o.today, location_id: src || (fallback && fallback.id) || "", location_dest_id: lit, note: "" },
                lines: [{ key: Math.random().toString(36).slice(2), product_id: productId || "", text: "" }],
            });
        });
    }
    swapTransfer() {
        const f = this.state.sheet.f;
        [f.location_id, f.location_dest_id] = [f.location_dest_id, f.location_id];
    }
    availableAt(productId, locId) {
        const m = this.materialById(productId);
        return m ? m.stock[String(locId)] || 0 : 0;
    }
    async saveTransfer() {
        const s = this.state.sheet;
        const lines = s.lines.filter((l) => l.product_id && l.text.trim());
        if (!lines.length) {
            this.notification.add("Material tanlang va miqdorini yozing", { type: "warning" });
            return;
        }
        if (lines.some((l) => this.lineBad(l))) {
            this.notification.add("Miqdorni raqam va + bilan yozing", { type: "warning" });
            return;
        }
        await this.run(async () => {
            const res = await this.orm.call(API, "create_transfer", [
                { ...s.f, location_id: Number(s.f.location_id), location_dest_id: Number(s.f.location_dest_id), lines },
            ]);
            this.notification.add(`${res.name}: ${res.summary} ko'chirildi`, { type: "success" });
            this.closeSheet();
            await this.refresh();
        });
    }

    // ---------------------------------------------------------------- sanash
    async openCount(countId = false, locationId = false) {
        await this.run(async () => {
            const c = await this.orm.call(API, "count_load", [countId || false, locationId || false, false]);
            this.openSheet({ type: "count", c, q: "", all: false });
        });
    }
    async reloadCount() {
        const c = this.state.sheet.c;
        const typed = Object.fromEntries(c.rows.filter((r) => r.text).map((r) => [r.product_id, r.text]));
        await this.run(async () => {
            const fresh = await this.orm.call(API, "count_load", [c.id || false, Number(c.location_id), c.date]);
            fresh.date = c.date;
            fresh.note = c.note;
            for (const r of fresh.rows) {
                if (typed[r.product_id] !== undefined) {
                    r.text = typed[r.product_id];
                    r.here = true;
                }
            }
            this.state.sheet.c = fresh;
        });
    }
    onCountLocation(ev) {
        this.state.sheet.c.location_id = Number(ev.target.value);
        this.reloadCount();
    }
    onCountDate(ev) {
        if (ev.target.value) {
            this.state.sheet.c.date = ev.target.value;
            this.reloadCount();
        }
    }
    get countRows() {
        const s = this.state.sheet;
        const words = s.q.trim().toLowerCase().split(/\s+/).filter(Boolean);
        return s.c.rows.filter((r) => {
            if (!s.all && !r.here && !r.text) {
                return false;
            }
            const hay = `${r.short} ${r.name} ${r.code}`.toLowerCase();
            return words.every((w) => hay.includes(w));
        });
    }
    get countHiddenCount() {
        const s = this.state.sheet;
        return s.c.rows.filter((r) => !r.here && !r.text).length;
    }
    countDiff(r) {
        const v = parseSum(r.text);
        if (v === null || Number.isNaN(v)) {
            return null;
        }
        return v - r.system;
    }
    get countSummary() {
        const rows = this.state.sheet.c.rows;
        const counted = rows.filter((r) => r.text && !Number.isNaN(parseSum(r.text)));
        const diff = counted.filter((r) => Math.abs(parseSum(r.text) - r.system) > 0.0005);
        return { counted: counted.length, diff: diff.length };
    }
    fillSystem(r) {
        r.text = String(Math.round(r.system * 1000) / 1000);
    }
    async saveCount(confirm) {
        const c = this.state.sheet.c;
        const bad = c.rows.find((r) => r.text && Number.isNaN(parseSum(r.text)));
        if (bad) {
            this.notification.add(`${bad.short}: miqdorni raqam bilan yozing`, { type: "warning" });
            return;
        }
        if (!this.countSummary.counted) {
            this.notification.add("Hech bir material sanalmagan", { type: "warning" });
            return;
        }
        const doSave = () =>
            this.run(async () => {
                const res = await this.orm.call(API, "count_save", [
                    {
                        id: c.id || false,
                        date: c.date,
                        location_id: Number(c.location_id),
                        note: c.note,
                        lines: c.rows.filter((r) => r.text).map((r) => ({ product_id: r.product_id, text: r.text })),
                    },
                    Boolean(confirm),
                ]);
                if (res.message) {
                    this.notification.add(`${res.name}: ${res.message}`, { type: "warning" });
                } else if (res.state === "done") {
                    this.notification.add(`${res.name} tasdiqlandi: ${res.counted} ta material, ${res.diff} tasida farq tuzatildi`, { type: "success" });
                } else {
                    this.notification.add(`${res.name} qoralama saqlandi`, { type: "success" });
                }
                this.closeSheet();
                await this.refresh();
            });
        if (confirm) {
            const s = this.countSummary;
            this.confirm(
                "Sanashni tasdiqlash",
                `${s.counted} ta material sanaldi, ${s.diff} tasida farq bor. Tasdiqlansa, ${c.location} qoldig'i sanalgan miqdorga tuzatiladi (inventarizatsiya).`,
                "Tasdiqlash",
                doSave
            );
        } else {
            doSave();
        }
    }

    // ---------------------------------------------------------------- hujjat
    async openDoc(doc) {
        if (doc.kind === "plavka" && doc.state === "draft" && !doc.stale) {
            // qoralama plavka — to'g'ridan-to'g'ri daftar formasi
            this.openRecord("craf.foundry.melt", doc.id);
            return;
        }
        await this.run(async () => {
            const d = await this.orm.call(API, "document_detail", [doc.model, doc.id, doc.move_ids || false]);
            this.openSheet({ type: "doc", d });
        });
    }
    openMeltRow(melt) {
        this.openRecord("craf.foundry.melt", melt.id);
    }
    openRecord(model, id) {
        this.closeSheet();
        this.actionService.doAction(
            { type: "ir.actions.act_window", res_model: model, res_id: id, views: [[false, "form"]] },
            { onClose: () => this.refresh() }
        );
    }
    docOpen(d) {
        if (d.model === "stock.move") {
            this.closeSheet();
            this.actionService.doAction({
                type: "ir.actions.act_window",
                name: d.name,
                res_model: "stock.move",
                views: [[false, "list"], [false, "form"]],
                domain: [["id", "in", d.move_ids]],
                context: { create: false },
            });
            return;
        }
        this.openRecord(d.model, d.id);
    }
    docAction(d, action) {
        const labels = {
            cancel: ["Bekor qilish", `${d.name} bekor qilinadi.`, "Bekor qilish"],
            draft: ["Qoralamaga qaytarish", `${d.name} yana qoralama bo'ladi.`, "Qaytarish"],
            delete: ["O'chirish", `${d.name} butunlay o'chiriladi.`, "O'chirish"],
            done: ["Sanashni tasdiqlash", `${d.name}: sanalgan miqdorlar qoldiqqa yoziladi (inventarizatsiya).`, "Tasdiqlash"],
            return: [
                "Teskari hujjat",
                `${d.name} qaytariladi: shu miqdorlar ${d.kind === "kirim" ? "yetkazib beruvchiga qaytgan" : "joyiga qaytgan"} deb yoziladi. Hujjat o'chmaydi, yonida teskari hujjat paydo bo'ladi.`,
                "Qaytarish",
            ],
        };
        const [title, body, label] = labels[action];
        this.confirm(title, body, label, () =>
            this.run(async () => {
                const res = await this.orm.call(API, "document_action", [d.model, d.id, action]);
                const done = {
                    cancel: "bekor qilindi",
                    draft: "qoralamaga qaytdi",
                    delete: "o'chirildi",
                    done: "tasdiqlandi",
                    return: `qaytarildi: ${res.new_name || ""}`,
                }[action];
                this.notification.add(`${res.name} ${done}`, { type: "success" });
                this.closeSheet();
                await this.refresh();
            })
        );
    }

    // ---------------------------------------------------------------- menyu amallari
    downloadXlsx() {
        this.closeSheet();
        window.location.href = `/craf/litey/xlsx?date_from=${this.state.from}&date_to=${this.state.to}`;
    }
    print() {
        this.closeSheet();
        setTimeout(() => window.print(), 50);
    }
    importExcel() {
        this.closeSheet();
        this.actionService.doAction("craf_litey.action_craf_litey_import", { onClose: () => this.refresh() });
    }
    openMelts() {
        this.closeSheet();
        this.actionService.doAction("craf_foundry.action_craf_foundry_melt");
    }
    openCounts() {
        this.closeSheet();
        this.actionService.doAction("craf_litey.action_craf_litey_count");
    }
    menuRefresh() {
        this.closeSheet();
        this.refresh();
    }
    openProducts() {
        this.closeSheet();
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: "Литейка materiallari",
            res_model: "product.template",
            views: [[false, "list"], [false, "form"]],
            domain: [["craf_litey_seq", ">", 0], ["craf_litey_hidden", "=", false]],
        });
    }
}

registry.category("actions").add("craf_litey", CrafLitey);
