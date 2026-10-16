// Craf → Sexlar: Press, Kimyoviy ishlov, Bo'yash va qadoqlash — telefon birinchi.
// Ko'rinish Литейка sahifasi bilan bir xil (o_craf_litey uslublari), sexga xos qismlari sx-* klasslarida.
import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { parseSum } from "@craf_litey/litey/litey";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const API = "craf.sex";
const STAGE_KEY = "craf_sex_stage";
const WEEKDAYS = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"];
const STAGE_MODEL = { press: "craf.extrusion.shift", kimyo: "craf.chem.treatment", boyash: "craf.paint.batch" };

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
function key() {
    return Math.random().toString(36).slice(2);
}
function toNum(v) {
    const n = parseFloat(String(v === undefined || v === null ? "" : v).replace(/\s/g, "").replace(",", "."));
    return Number.isFinite(n) ? n : 0;
}
function toInt(v) {
    return Math.max(0, Math.floor(toNum(v)));
}

export class CrafSex extends Component {
    static template = "craf_sex.Sex";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.opts = {};
        this.state = useState({
            data: null,
            loading: true,
            stage: null,
            tab: "ish",
            from: false,
            to: false,
            sheet: null,
            busy: false,
            pick: {}, // tanlangan korzinkalar (kimyo / bo'yash)
            onlyDrafts: false,
            onlyC1: false,
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
            let stage = ctx.craf_stage || null;
            if (!stage) {
                try {
                    stage = window.localStorage.getItem(STAGE_KEY);
                } catch {
                    stage = null;
                }
            }
            await this.load(stage);
        });
    }

    // ================================================================ yuklash
    async load(stage, from, to) {
        this.state.loading = true;
        try {
            const data = await this.orm.call(API, "get_data", [
                stage || this.state.stage || false,
                (from === undefined ? this.state.from : from) || false,
                (to === undefined ? this.state.to : to) || false,
            ]);
            this.state.data = data;
            this.state.stage = data.stage;
            this.state.from = data.date_from;
            this.state.to = data.date_to;
            const valid = new Set([...data.baskets.waiting, ...data.baskets.ready].map((l) => l.id));
            for (const id of Object.keys(this.state.pick)) {
                if (!valid.has(Number(id))) {
                    delete this.state.pick[id];
                }
            }
        } finally {
            this.state.loading = false;
        }
    }
    refresh() {
        return this.load();
    }
    setStage(stage) {
        if (stage === this.state.stage) {
            return;
        }
        try {
            window.localStorage.setItem(STAGE_KEY, stage);
        } catch {
            // brauzer xotirasi yopiq bo'lsa — e'tiborsiz
        }
        this.state.pick = {};
        const root = document.querySelector(".o_craf_sex");
        if (root) {
            root.scrollTo(0, 0);
        }
        this.load(stage);
    }
    setTab(tab) {
        this.state.tab = tab;
        const root = document.querySelector(".o_craf_sex");
        if (root) {
            root.scrollTo(0, 0);
        }
    }

    // ================================================================ format
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
    dmy(iso) {
        return dmy(iso);
    }
    errorText(e) {
        return (e && e.data && e.data.message) || (e && e.message) || String(e);
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
    get stageTitle() {
        return { press: "Press", kimyo: "Kimyoviy ishlov", boyash: "Bo'yash va qadoqlash" }[this.state.stage] || "Sexlar";
    }
    get newLabel() {
        return { press: "Smena ochish", kimyo: "Kimyoviy ishlov", boyash: "Bo'yash smenasi" }[this.state.stage];
    }
    toneClass(tone) {
        return { ok: "cl-ok", warn: "cl-warn", bad: "cl-bad" }[tone] || "";
    }

    // ================================================================ davr
    openPeriod() {
        this.openSheet({ type: "period", from: this.state.from, to: this.state.to });
    }
    preset(kind) {
        const today = this.state.data.today;
        const ranges = {
            today: [today, today],
            yesterday: [addDays(today, -1), addDays(today, -1)],
            7: [addDays(today, -6), today],
            30: [addDays(today, -29), today],
            month: [today.slice(0, 8) + "01", today],
        };
        const [f, t] = ranges[kind];
        this.closeSheet();
        this.load(null, f, t);
    }
    applyPeriod() {
        const s = this.state.sheet;
        if (s.from && s.to) {
            this.closeSheet();
            this.load(null, s.from, s.to);
        }
    }
    shift(dir) {
        const span = Math.round((new Date(this.state.to) - new Date(this.state.from)) / 86400000) + 1;
        this.load(null, addDays(this.state.from, dir * span), addDays(this.state.to, dir * span));
    }

    // ================================================================ hujjatlar ro'yxati
    get docList() {
        const d = this.state.data;
        return d.docs.filter(
            (doc) => (!this.state.onlyDrafts || doc.state === "draft") && (!this.state.onlyC1 || (doc.state === "done" && doc.c1 !== "done"))
        );
    }
    get docGroups() {
        const groups = [];
        let current = null;
        for (const doc of this.docList) {
            if (!current || current.date !== doc.date) {
                current = { date: doc.date, label: dmy(doc.date), weekday: WEEKDAYS[(new Date(doc.date).getUTCDay() + 6) % 7], docs: [] };
                groups.push(current);
            }
            current.docs.push(doc);
        }
        return groups;
    }
    get c1Count() {
        return this.state.data.docs.filter((d) => d.state === "done" && d.c1 !== "done").length;
    }

    // ================================================================ korzinka tanlash (kimyo, bo'yash)
    get pickList() {
        const b = this.state.data.baskets;
        return this.state.stage === "kimyo" ? b.waiting : b.ready;
    }
    togglePick(load) {
        if (this.state.pick[load.id]) {
            delete this.state.pick[load.id];
        } else {
            this.state.pick[load.id] = true;
        }
    }
    pickAll() {
        const all = this.pickList.every((l) => this.state.pick[l.id]);
        for (const l of this.pickList) {
            if (all) {
                delete this.state.pick[l.id];
            } else {
                this.state.pick[l.id] = true;
            }
        }
    }
    get picked() {
        return this.pickList.filter((l) => this.state.pick[l.id]);
    }
    get pickedSummary() {
        const list = this.picked;
        return {
            count: list.length,
            pcs: list.reduce((s, l) => s + l.pcs, 0),
            kg: list.reduce((s, l) => s + l.kg, 0),
            area: list.reduce((s, l) => s + l.area, 0),
        };
    }

    // ================================================================ varaqlar
    openSheet(sheet) {
        this.state.sheet = sheet;
    }
    closeSheet() {
        this.state.sheet = null;
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
                sheet.error = this.errorText(e);
            } else {
                this.notification.add(this.errorText(e), { type: "danger", sticky: true, title: "Bajarilmadi" });
            }
        } finally {
            this.state.busy = false;
        }
    }
    confirm(title, body, label, onConfirm) {
        this.dialog.add(ConfirmationDialog, { title, body, confirmLabel: label, cancelLabel: "Yo'q", confirm: onConfirm, cancel: () => {} });
    }
    async options(stage) {
        const method = { press: "press_options", kimyo: "chem_options", boyash: "paint_options" }[stage];
        this.opts[stage] = await this.orm.call(API, method, []);
        return this.opts[stage];
    }
    newDoc() {
        if (this.state.stage === "press") {
            return this.openPress();
        }
        if (this.state.stage === "kimyo") {
            return this.openChem();
        }
        return this.openPaint();
    }
    editDoc(stage, id) {
        if (stage === "press") {
            return this.openPress(id);
        }
        if (stage === "kimyo") {
            return this.openChem(id);
        }
        return this.openPaint(id);
    }

    // ---------------------------------------------------------------- PRESS
    async openPress(id = false) {
        await this.run(async () => {
            const o = await this.options("press");
            let f;
            if (id) {
                f = await this.orm.call(API, "press_load", [id]);
            } else {
                const last = this.state.data.docs.find((d) => d.equipment) || {};
                f = {
                    id: false, date: o.today, equipment_id: (o.presses[0] || {}).id || false, section_id: false,
                    shift: "1", employee_id: false, billet_product_id: (o.billets[0] || {}).id || false,
                    billet_text: "", rest_text: "", scrap_text: "", duration: 11, note: "", direct: [], loads: [],
                };
                const eq = o.presses.find((p) => p.name === last.equipment);
                if (eq) {
                    f.equipment_id = eq.id;
                }
            }
            this.openSheet({ type: "press", o, f, sectionQuery: "" });
        });
    }
    sectionOf(f) {
        return (this.opts.press && this.opts.press.sections.find((s) => s.id === Number(f.section_id))) || null;
    }
    directQty(f, productId) {
        const row = f.direct.find((r) => r.product_id === productId);
        return row ? row.pcs : "";
    }
    setDirect(f, productId, ev) {
        const pcs = toInt(ev.target.value);
        const row = f.direct.find((r) => r.product_id === productId);
        if (row) {
            row.pcs = pcs;
        } else {
            f.direct.push({ product_id: productId, pcs });
        }
    }
    pressPreview(f) {
        const sec = this.sectionOf(f);
        let kg = 0;
        let pcs = 0;
        for (const l of f.loads || []) {
            kg += l.net || l.theory;
            pcs += l.pcs;
        }
        if (sec) {
            for (const r of f.direct) {
                const p = sec.direct.find((d) => d.id === r.product_id);
                if (p) {
                    kg += r.pcs * p.kg_pc;
                    pcs += r.pcs;
                }
            }
        }
        const billet = parseSum(f.billet_text) || 0;
        const rest = parseSum(f.rest_text) || 0;
        const scrap = parseSum(f.scrap_text) || 0;
        return {
            kg, pcs, billet,
            yield: billet ? (kg / billet) * 100 : 0,
            loss: billet ? billet - kg - rest - scrap : 0,
        };
    }
    async savePress(confirm) {
        const f = this.state.sheet.f;
        if (!f.section_id) {
            this.state.sheet.error = "Matritsani (profil kesimini) tanlang.";
            return;
        }
        for (const [label, text] of [["Quyma sarfi", f.billet_text], ["Питак", f.rest_text], ["Brak", f.scrap_text]]) {
            if (text && Number.isNaN(parseSum(text))) {
                this.state.sheet.error = `${label}: raqam va + bilan yozing, masalan 930+925`;
                return;
            }
        }
        const doSave = () =>
            this.run(async () => {
                const res = await this.orm.call(API, "press_save", [
                    { ...f, section_id: Number(f.section_id), equipment_id: f.equipment_id ? Number(f.equipment_id) : false,
                      employee_id: f.employee_id ? Number(f.employee_id) : false },
                    Boolean(confirm),
                ]);
                this.notification.add(confirm ? `${res.name} tasdiqlandi` : `${res.name} saqlandi`, { type: "success" });
                this.closeSheet();
                await this.refresh();
            });
        if (confirm) {
            const p = this.pressPreview(f);
            this.confirm(
                "Smenani tasdiqlash",
                `Quyma ${this.num(p.billet)} kg → profil ${this.num(p.kg)} kg (${this.num(p.pcs, 0)} dona), chiqish ${this.num(p.yield)}%. ` +
                    "Tasdiqlansa, quyma Press sexidan yechiladi, profillar kimyoga (korzinkalarda) va qadoqlashga o'tadi.",
                "Tasdiqlash",
                doSave
            );
        } else {
            doSave();
        }
    }

    // ---------------------------------------------------------------- korzinka (press)
    async openBasket(shift, load = null) {
        await this.run(async () => {
            const o = await this.options("press");
            const sec = o.sections.find((x) => x.id === shift.section_id) || null;
            const f = load
                ? { load_id: load.id, basket_id: load.basket_id, qty_6: load.qty_6 || "", qty_5: load.qty_5 || "", gross_text: load.gross ? String(load.gross) : "" }
                : { load_id: false, basket_id: (o.baskets[0] || {}).id || false, qty_6: "", qty_5: "", gross_text: "" };
            const baskets = [...o.baskets];
            if (load && !baskets.find((b) => b.id === load.basket_id)) {
                baskets.unshift({ id: load.basket_id, name: load.basket, tare: load.gross - load.net, capacity: 0 });
            }
            this.openSheet({ type: "basket", o, f, shift, sec, baskets, title: shift.name });
        });
    }
    basketPreview(s) {
        const f = s.f;
        const b = s.baskets.find((x) => x.id === Number(f.basket_id)) || { tare: 0, capacity: 0 };
        const sec = s.sec || { kg6: 0, kg5: 0 };
        const pcs = toInt(f.qty_6) + toInt(f.qty_5);
        const theory = toInt(f.qty_6) * sec.kg6 + toInt(f.qty_5) * sec.kg5;
        const gross = parseSum(f.gross_text) || 0;
        const net = gross ? gross - (b.tare || 0) : 0;
        return { pcs, theory, net, diff: net ? net - theory : 0, tare: b.tare || 0, capacity: b.capacity || 0, over: b.capacity && pcs > b.capacity };
    }
    async saveBasket() {
        const s = this.state.sheet;
        await this.run(async () => {
            const res = await this.orm.call(API, "basket_save", [{ ...s.f, shift_id: s.shift.id, basket_id: Number(s.f.basket_id) }]);
            this.notification.add(`${res.basket}: ${res.content}`, { type: "success" });
            this.closeSheet();
            await this.refresh();
        });
    }
    deleteBasket() {
        const s = this.state.sheet;
        this.confirm("Korzinkani olib tashlash", "Bu korzinka smenadan olib tashlanadi va bo'shaydi.", "Olib tashlash", () =>
            this.run(async () => {
                await this.orm.call(API, "basket_delete", [s.f.load_id]);
                this.closeSheet();
                await this.refresh();
            })
        );
    }

    // ---------------------------------------------------------------- KIMYO
    async openChem(id = false) {
        await this.run(async () => {
            const o = await this.options("kimyo");
            let f;
            let loads = [...this.state.data.baskets.waiting];
            if (id) {
                f = await this.orm.call(API, "chem_load", [id]);
                for (const l of f.loads) {
                    if (!loads.find((x) => x.id === l.id)) {
                        loads.unshift(l);
                    }
                }
                f.pick = Object.fromEntries(f.load_ids.map((i) => [i, true]));
            } else {
                f = { id: false, date: o.today, shift: "1", employee_id: false, equipment_id: (o.equipment[0] || {}).id || false,
                      chem: {}, note: "", pick: { ...this.state.pick } };
                if (!Object.keys(f.pick).length) {
                    f.pick = Object.fromEntries(loads.map((l) => [l.id, true]));
                }
            }
            this.openSheet({ type: "chem", o, f, loads });
        });
    }
    sheetPicked(s) {
        return s.loads.filter((l) => s.f.pick[l.id]);
    }
    toggleSheetPick(s, load) {
        if (s.f.pick[load.id]) {
            delete s.f.pick[load.id];
        } else {
            s.f.pick[load.id] = true;
        }
    }
    chemArea(s) {
        return this.sheetPicked(s).reduce((a, l) => a + l.area, 0);
    }
    chemNorm(s, c) {
        return Math.round(this.chemArea(s) * c.per_m2 * 100) / 100;
    }
    async saveChem(confirm) {
        const s = this.state.sheet;
        const ids = this.sheetPicked(s).map((l) => l.id);
        if (!ids.length) {
            s.error = "Ishlov berilgan korzinkalarni belgilang.";
            return;
        }
        const doSave = () =>
            this.run(async () => {
                const res = await this.orm.call(API, "chem_save", [
                    { ...s.f, load_ids: ids, employee_id: s.f.employee_id ? Number(s.f.employee_id) : false,
                      equipment_id: s.f.equipment_id ? Number(s.f.equipment_id) : false },
                    Boolean(confirm),
                ]);
                this.notification.add(confirm ? `${res.name} tasdiqlandi — korzinkalar bo'yashga o'tdi` : `${res.name} saqlandi`, { type: "success" });
                this.state.pick = {};
                this.closeSheet();
                await this.refresh();
            });
        if (confirm) {
            this.confirm("Kimyoviy ishlovni tasdiqlash",
                `${ids.length} ta korzinka bo'yash sexiga o'tadi, kimyo Kimyoviy ishlov joyidan yechiladi.`, "Tasdiqlash", doSave);
        } else {
            doSave();
        }
    }

    // ---------------------------------------------------------------- BO'YASH
    async openPaint(id = false) {
        await this.run(async () => {
            const o = await this.options("boyash");
            let f;
            let loads = [...this.state.data.baskets.ready];
            if (id) {
                f = await this.orm.call(API, "paint_load", [id]);
                for (const l of f.loads) {
                    if (!loads.find((x) => x.id === l.id)) {
                        loads.unshift(l);
                    }
                }
                f.pick = Object.fromEntries(f.load_ids.map((i) => [i, true]));
                f.lines = f.lines.map((l) => ({ ...l, key: key() }));
            } else {
                f = { id: false, date: o.today, shift: "1", color_id: false, employee_id: false,
                      equipment_id: (o.equipment[0] || {}).id || false, powder_text: "", powder_bags: "", note: "",
                      pick: { ...this.state.pick }, lines: [] };
                if (Object.keys(f.pick).length) {
                    f.lines = this.linesFromLoads(loads.filter((l) => f.pick[l.id]));
                }
            }
            this.openSheet({ type: "paint", o, f, loads, addSemi: "" });
        });
    }
    linesFromLoads(loads) {
        const byId = {};
        for (const l of loads) {
            for (const p of l.products) {
                byId[p.id] = (byId[p.id] || 0) + p.qty;
            }
        }
        return Object.entries(byId).map(([id, qty]) => ({ key: key(), semi_id: Number(id), pcs_in: qty, defect: "", packs: "", extra: "" }));
    }
    togglePaintPick(s, load) {
        this.toggleSheetPick(s, load);
        // korzinkalardan kelgan qatorlar qayta yig'iladi, qo'lda qo'shilganlari qoladi
        const fromLoads = this.linesFromLoads(this.sheetPicked(s));
        const manual = s.f.lines.filter((l) => l.manual);
        const old = Object.fromEntries(s.f.lines.filter((l) => !l.manual).map((l) => [l.semi_id, l]));
        s.f.lines = [
            ...fromLoads.map((l) => (old[l.semi_id] ? { ...old[l.semi_id], pcs_in: l.pcs_in } : l)),
            ...manual,
        ];
    }
    semi(s, id) {
        return s.o.semis.find((x) => x.id === Number(id)) || null;
    }
    lineInfo(s, line) {
        const semi = this.semi(s, line.semi_id);
        const variant = semi && s.f.color_id ? semi.variants[String(s.f.color_id)] : null;
        const perPack = (variant && variant.per_pack) || (semi && semi.per_pack) || 0;
        const packed = toInt(line.packs) * perPack + toInt(line.extra);
        const pcsIn = toInt(line.pcs_in) || (packed ? packed + toInt(line.defect) : 0);
        const ok = pcsIn - toInt(line.defect);
        return {
            name: variant ? variant.name : semi ? semi.name : "?",
            missing: Boolean(semi && s.f.color_id && !variant),
            perPack, packed, pcsIn, ok,
            mismatch: Boolean(packed && packed !== ok),
            area: semi ? pcsIn * semi.area_pc : 0,
            kg: semi ? ok * semi.kg_pc : 0,
            avail: semi ? semi.avail : 0,
        };
    }
    paintTotals(s) {
        let area = 0;
        let ok = 0;
        let defect = 0;
        let kg = 0;
        for (const l of s.f.lines) {
            const i = this.lineInfo(s, l);
            area += i.area;
            ok += i.ok;
            kg += i.kg;
            defect += toInt(l.defect);
        }
        const color = s.o.colors.find((c) => c.id === Number(s.f.color_id));
        const powderNorm = (area * s.o.powder_g_m2) / 1000;
        const powder = parseSum(s.f.powder_text) || (color && color.pkg_kg ? toNum(s.f.powder_bags) * color.pkg_kg : 0);
        return { area, ok, defect, kg, powderNorm, powder, color };
    }
    addPaintLine() {
        const s = this.state.sheet;
        if (!s.addSemi) {
            return;
        }
        s.f.lines.push({ key: key(), semi_id: Number(s.addSemi), pcs_in: "", defect: "", packs: "", extra: "", manual: true });
        s.addSemi = "";
    }
    removePaintLine(line) {
        const s = this.state.sheet;
        s.f.lines = s.f.lines.filter((l) => l !== line);
    }
    get semisInStock() {
        const s = this.state.sheet;
        return s.o.semis.filter((x) => x.avail > 0 && !s.f.lines.find((l) => l.semi_id === x.id));
    }
    async savePaint(confirm) {
        const s = this.state.sheet;
        if (!s.f.color_id) {
            s.error = "Rangni tanlang.";
            return;
        }
        if (!s.f.lines.length) {
            s.error = "Profil qatorlarini qo'shing: korzinkalarni belgilang yoki «Profil qo'shish».";
            return;
        }
        if (s.f.powder_text && Number.isNaN(parseSum(s.f.powder_text))) {
            s.error = "Kukun: raqam bilan yozing.";
            return;
        }
        const t = this.paintTotals(s);
        const doSave = () =>
            this.run(async () => {
                const res = await this.orm.call(API, "paint_save", [
                    { ...s.f, color_id: Number(s.f.color_id), load_ids: this.sheetPicked(s).map((l) => l.id),
                      employee_id: s.f.employee_id ? Number(s.f.employee_id) : false,
                      equipment_id: s.f.equipment_id ? Number(s.f.equipment_id) : false },
                    Boolean(confirm),
                ]);
                this.notification.add(confirm ? `${res.name} tasdiqlandi — omborga topshirishni unutmang` : `${res.name} saqlandi`, { type: "success" });
                this.state.pick = {};
                this.closeSheet();
                await this.refresh();
            });
        if (confirm) {
            this.confirm("Bo'yashni tasdiqlash",
                `${t.color ? t.color.name : ""}: bo'yaldi ${this.num(t.ok, 0)} dona, brak ${this.num(t.defect, 0)} dona, kukun ${this.num(t.powder, 2)} kg. ` +
                    "Bo'yalgan profil Qadoqlash joyiga kiradi.", "Tasdiqlash", doSave);
        } else {
            doSave();
        }
    }

    // ---------------------------------------------------------------- hujjat
    async openDoc(stage, id) {
        await this.run(async () => {
            const d = await this.orm.call(API, "doc_detail", [stage, id]);
            this.openSheet({ type: "doc", d });
        });
    }
    docAction(d, action) {
        const texts = {
            done: ["Tasdiqlash", `${d.name} tasdiqlanadi: ombor harakatlari yoziladi.`, "Tasdiqlash"],
            cancel: ["Bekor qilish", `${d.name} bekor qilinadi.`, "Bekor qilish"],
            draft: ["Qoralamaga qaytarish", `${d.name} yana qoralama bo'ladi.`, "Qaytarish"],
            delete: ["O'chirish", `${d.name} butunlay o'chiriladi.`, "O'chirish"],
            to_stock: ["Omborga topshirish", `${d.name}: bo'yalgan profillar Qadoqlashdan Tayyor mahsulot omboriga o'tadi.`, "Topshirish"],
        };
        const run = () =>
            this.run(async () => {
                const res = await this.orm.call(API, "doc_action", [d.stage, d.id, action]);
                if (action === "labels") {
                    this.closeSheet();
                    await this.actionService.doAction(res.action);
                    return;
                }
                const done = {
                    done: "tasdiqlandi", cancel: "bekor qilindi", draft: "qoralamaga qaytdi", delete: "o'chirildi",
                    c1: "1C ga kiritildi deb belgilandi", c1_undo: "1C belgisi olib tashlandi",
                    to_stock: `omborga topshirildi (${res.picking || ""})`,
                }[action];
                this.notification.add(`${res.name} ${done}`, { type: "success" });
                this.closeSheet();
                await this.refresh();
            });
        if (texts[action]) {
            const [title, body, label] = texts[action];
            this.confirm(title, body, label, run);
        } else {
            run();
        }
    }
    eq(a, b) {
        return Number(a) === b;
    }
    docBasket(d) {
        this.closeSheet();
        this.openBasket({ id: d.id, name: d.name, title: d.title, section_id: d.section_id });
    }
    docEdit(d) {
        this.closeSheet();
        this.editDoc(d.stage, d.id);
    }
    docOpen(d) {
        this.closeSheet();
        this.actionService.doAction(
            { type: "ir.actions.act_window", res_model: STAGE_MODEL[d.stage], res_id: d.id, views: [[false, "form"]] },
            { onClose: () => this.refresh() }
        );
    }
    quickToStock(card) {
        this.docAction({ stage: "boyash", id: card.id, name: card.name }, "to_stock");
    }

    // ---------------------------------------------------------------- menyu
    openMenu() {
        this.openSheet({ type: "menu" });
    }
    go(xmlid) {
        this.closeSheet();
        this.actionService.doAction(xmlid);
    }
    menuRefresh() {
        this.closeSheet();
        this.refresh();
    }
}

registry.category("actions").add("craf_sex", CrafSex);
