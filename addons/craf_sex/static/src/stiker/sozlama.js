// Craf → Stiker sozlamalari — telefon birinchi.
// Qoidalar (rang / profil → qalinlik, logo), profil normalari (kenglik × tomon), stiker turlari, logolar va
// «Tekshirish». Bo'yash xodimi — faqat ko'rish; omborchi, direktor, administrator — to'liq CRUD.
// Ko'rinish Sexlar sahifasi bilan bir xil (o_craf_litey, o_craf_sex uslublari), formalar alohida sahifada.
import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const API = "craf.stiker.sozlama";
const TAB_KEY = "craf_stiker_tab";
const TABS = [
    { key: "choice", label: "Qoidalar", icon: "fa-random" },
    { key: "norm", label: "Normalar", icon: "fa-th-list" },
    { key: "sticker", label: "Turlar", icon: "fa-tags" },
    { key: "logo", label: "Logolar", icon: "fa-certificate" },
    { key: "check", label: "Tekshirish", icon: "fa-calculator" },
];
const ADD_LABEL = { choice: "Qoida", norm: "Norma", sticker: "Stiker turi", logo: "Logo" };
// yangi stiker turi: qalinlikka qarab odatiy mikron va rulon uzunligi (stiker.xlsx)
const ADHESION_DEFAULTS = { medium: { micron: 50, roll: 500 }, high: { micron: 80, roll: 300 } };

function savedTab() {
    try {
        const tab = window.localStorage.getItem(TAB_KEY);
        return TABS.some((t) => t.key === tab) ? tab : "choice";
    } catch {
        return "choice";
    }
}

export class CrafStikerSozlama extends Component {
    static template = "craf_sex.StikerSozlama";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        const ctx = (this.props.action && this.props.action.context) || {};
        this.fromPage = Boolean(ctx.craf_from); // Bo'yash sahifasidan ochilgan — orqaga tugmasi
        this.backContext = ctx.craf_back || null; // qaytish: Bo'yash sahifasining Materiallar bo'limi
        this.actionService = useService("action");
        this.state = useState({
            data: null,
            tab: TABS.some((t) => t.key === ctx.craf_tab) ? ctx.craf_tab : savedTab(),
            form: null, // { kind, vals, isNew, title, sub, error, sectionQ }
            busy: false,
            q: "",
            archived: false,
            check: { color_id: "", section_id: "", length: "6", pcs: "1", logo_id: "", result: null, error: "" },
        });
        this.onKey = (ev) => {
            if (ev.key === "Escape" && this.state.form && !this.state.busy) {
                this.closeForm();
            }
        };
        window.addEventListener("keydown", this.onKey);
        onWillUnmount(() => window.removeEventListener("keydown", this.onKey));
        onWillStart(() => this.load());
    }

    // ================================================================ yuklash
    async load() {
        this.state.data = await this.orm.call(API, "get_data", []);
    }
    get canEdit() {
        return Boolean(this.state.data && this.state.data.can_edit);
    }
    get tabs() {
        const d = this.state.data;
        const counts = d ? { choice: d.choices.length, norm: d.norms.length, sticker: d.stickers.length, logo: d.logos.length } : {};
        return TABS.map((t) => ({ ...t, count: counts[t.key] }));
    }
    get addLabel() {
        return this.canEdit ? ADD_LABEL[this.state.tab] || "" : "";
    }
    setTab(tab) {
        this.state.tab = tab;
        this.state.q = "";
        try {
            window.localStorage.setItem(TAB_KEY, tab);
        } catch {
            // brauzer xotirasi yopiq bo'lsa — e'tiborsiz
        }
        this.scrollTop();
    }
    scrollTop() {
        setTimeout(() => {
            const root = document.querySelector(".o_craf_stiker");
            if (root) {
                root.scrollTo(0, 0);
            }
        });
    }
    goBack() {
        if (this.state.form) {
            return this.closeForm();
        }
        if (this.backContext) {
            return this.actionService.doAction(
                { type: "ir.actions.client", tag: "craf_sex", name: "Bo'yash va qadoqlash", context: this.backContext },
                { clearBreadcrumbs: true }
            );
        }
        window.history.back();
    }

    // ================================================================ format
    num(value, digits = 1) {
        return Number(value || 0).toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
    }
    eqNum(a, b) {
        return Number(a) === Number(b);
    }
    errorText(e) {
        return (e && e.data && e.data.message) || (e && e.message) || String(e);
    }
    async run(fn) {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        const form = this.state.form;
        if (form) {
            form.error = "";
        }
        try {
            return await fn();
        } catch (e) {
            if (form && this.state.form === form) {
                form.error = this.errorText(e);
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

    // ================================================================ ro'yxatlar
    get choices() {
        return this.state.data.choices.filter((c) => this.state.archived || c.active);
    }
    get normGroups() {
        const q = this.state.q.trim().toLowerCase();
        const groups = {};
        for (const n of this.state.data.norms) {
            if (q && !n.section.toLowerCase().includes(q)) {
                continue;
            }
            const g = (groups[n.section_id] = groups[n.section_id] || { id: n.section_id, name: n.section, items: [], perM: 0 });
            g.items.push(n);
            g.perM += n.sides;
        }
        return Object.values(groups).sort((a, b) => a.name.localeCompare(b.name));
    }
    get sectionsWithoutNorm() {
        const used = new Set(this.state.data.norms.map((n) => n.section_id));
        return this.state.data.sections.filter((s) => !used.has(s.id));
    }
    get sectionsWithoutNormText() {
        return this.sectionsWithoutNorm.map((s) => s.name).join(", ");
    }
    get stickerGroups() {
        const groups = {};
        for (const s of this.state.data.stickers) {
            if (!this.state.archived && !s.active) {
                continue;
            }
            const g = (groups[s.logo_id] = groups[s.logo_id] || { id: s.logo_id, name: s.logo, items: [] });
            g.items.push(s);
        }
        return Object.values(groups);
    }
    get logos() {
        return this.state.data.logos.filter((l) => this.state.archived || l.active);
    }
    get activeLogos() {
        return this.state.data.logos.filter((l) => l.active);
    }
    get archivedCount() {
        const d = this.state.data;
        const key = { choice: "choices", sticker: "stickers", logo: "logos" }[this.state.tab];
        return key ? d[key].filter((x) => !x.active).length : 0;
    }
    moreCount(list, max) {
        return list.length > max ? list.length - max : 0;
    }

    // ================================================================ formalar (alohida sahifa)
    openForm(kind, rec = null) {
        if (!this.canEdit || !ADD_LABEL[kind]) {
            return;
        }
        const d = this.state.data;
        let vals;
        let title;
        let sub = "";
        if (kind === "choice") {
            vals = rec
                ? { id: rec.id, color_ids: [...rec.color_ids], section_ids: [...rec.section_ids], adhesion: rec.adhesion,
                    logo_id: rec.logo_id || "", sequence: rec.sequence, note: rec.note, active: rec.active }
                : { id: false, color_ids: [], section_ids: [], adhesion: "high", logo_id: "", sequence: 10, note: "", active: true };
            title = rec ? "Stiker qoidasi" : "Yangi stiker qoidasi";
            sub = "Agar rang va/yoki profil … bo'lsa → shunday stiker";
        } else if (kind === "norm") {
            vals = rec
                ? { id: rec.id, section_id: rec.section_id, width: rec.width, sides: String(rec.sides), sticker_id: rec.sticker_id || "", note: rec.note }
                : { id: false, section_id: "", width: d.widths[0] || 40, sides: "1", sticker_id: "", note: "" };
            title = rec ? `Norma: ${rec.section}` : "Yangi profil normasi";
            sub = "Qaysi kenglikdagi stiker necha tomonga";
        } else if (kind === "sticker") {
            vals = rec
                ? { id: rec.id, logo_id: rec.logo_id, adhesion: rec.adhesion, width: rec.width, micron: rec.micron, roll: rec.roll,
                    min_rolls: rec.min_rolls || "", note: rec.note, active: rec.active, locked: rec.locked }
                : { id: false, logo_id: (this.activeLogos[0] || {}).id || "", adhesion: "medium", width: d.widths[0] || 40,
                    micron: 50, roll: 500, min_rolls: "", note: "", active: true, locked: false };
            title = rec ? rec.name : "Yangi stiker turi";
            sub = "Logo, qalinlik, kenglik, rulon uzunligi — ombor mahsuloti o'zi yaratiladi";
        } else {
            vals = rec
                ? { id: rec.id, name: rec.name, sequence: rec.sequence, active: rec.active, count: rec.count }
                : { id: false, name: "", sequence: 10, active: true, count: 0 };
            title = rec ? `Logo: ${rec.name}` : "Yangi logo";
        }
        this.state.form = { kind, vals, isNew: !rec, title, sub, error: "", sectionQ: "" };
        this.scrollTop();
    }
    closeForm() {
        this.state.form = null;
    }
    toggleIn(list, id) {
        const i = list.indexOf(id);
        if (i >= 0) {
            list.splice(i, 1);
        } else {
            list.push(id);
        }
    }
    get formSections() {
        const f = this.state.form;
        const q = (f.sectionQ || "").trim().toLowerCase();
        const picked = new Set(f.vals.section_ids);
        return this.state.data.sections
            .filter((s) => picked.has(s.id) || !q || s.name.toLowerCase().includes(q))
            .sort((a, b) => Number(picked.has(b.id)) - Number(picked.has(a.id)));
    }
    stickersForWidth(width) {
        return this.state.data.stickers.filter((s) => s.active && Number(s.width) === Number(width));
    }
    setAdhesion(adhesion) {
        const v = this.state.form.vals;
        v.adhesion = adhesion;
        // yangi stiker turida — odatiy mikron va rulon uzunligi
        if (this.state.form.kind === "sticker" && this.state.form.isNew && ADHESION_DEFAULTS[adhesion]) {
            Object.assign(v, ADHESION_DEFAULTS[adhesion]);
        }
    }
    get choiceText() {
        // forma ostida: qoida qanday o'qiladi
        const f = this.state.form;
        const d = this.state.data;
        const v = f.vals;
        const name = (list, id) => (list.find((x) => x.id === Number(id)) || {}).name || "?";
        const colors = v.color_ids.length ? v.color_ids.map((id) => name(d.colors, id)).join(", ") : "hamma rang";
        const sections = v.section_ids.length ? ` · ${v.section_ids.length} ta profil` : "";
        const result = [];
        if (v.adhesion) {
            result.push((d.adhesions.find((a) => a.key === v.adhesion) || {}).label);
        }
        if (v.logo_id) {
            result.push(`logo ${name(d.logos, v.logo_id)}`);
        }
        return `${colors}${sections} → ${result.join(", ") || "natija tanlanmagan"}`;
    }
    validate(f) {
        const v = f.vals;
        if (f.kind === "choice" && !v.adhesion && !v.logo_id) {
            return "Natijani tanlang: stiker qalinligi va/yoki logo.";
        }
        if (f.kind === "norm" && !v.section_id) {
            return "Profilni (kesim) tanlang.";
        }
        if ((f.kind === "norm" || f.kind === "sticker") && !(Number(v.width) > 0)) {
            return "Kenglikni yozing (mm).";
        }
        if (f.kind === "sticker" && !v.logo_id) {
            return "Logoni tanlang.";
        }
        if (f.kind === "sticker" && !(Number(String(v.roll).replace(",", ".")) > 0)) {
            return "Rulon uzunligini yozing (m).";
        }
        if (f.kind === "logo" && !String(v.name || "").trim()) {
            return "Logo nomini yozing.";
        }
        return "";
    }
    saveForm() {
        const f = this.state.form;
        const err = this.validate(f);
        if (err) {
            f.error = err;
            return;
        }
        this.run(async () => {
            const res = await this.orm.call(API, "save", [f.kind, { ...f.vals }]);
            this.notification.add(`${res.name} — saqlandi`, { type: "success" });
            this.closeForm();
            await this.load();
        });
    }
    deleteForm() {
        const f = this.state.form;
        const what = { choice: "qoida", norm: "norma", sticker: "stiker turi", logo: "logo" }[f.kind];
        this.confirm("O'chirish", `${f.title} — ${what} butunlay o'chiriladi.`, "O'chirish", () =>
            this.run(async () => {
                const res = await this.orm.call(API, "delete", [f.kind, f.vals.id]);
                this.notification.add(`${res.name} — o'chirildi`, { type: "success" });
                this.closeForm();
                await this.load();
            })
        );
    }

    // ================================================================ tekshirish
    runCheck() {
        const c = this.state.check;
        c.error = "";
        if (!c.color_id || !c.section_id) {
            c.error = "Rang va profilni tanlang.";
            return;
        }
        this.run(async () => {
            try {
                c.result = await this.orm.call(API, "preview", [{ ...c, result: undefined }]);
            } catch (e) {
                c.result = null;
                c.error = this.errorText(e);
            }
        });
    }
}

registry.category("actions").add("craf_stiker_sozlama", CrafStikerSozlama);
