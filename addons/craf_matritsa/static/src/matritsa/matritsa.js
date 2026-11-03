// Craf → Matritsa: qolip (matritsa) mutaxassisi sahifasi — telefon birinchi.
// Ko'rinish Sexlar / Литейка sahifalari bilan bir xil (o_craf_litey, o_craf_sex uslublari), formalar alohida sahifada.
import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const API = "craf.matritsa";
const TABS = ["matritsa", "gaz", "soda", "qoldiq"];

function toNum(v) {
    const n = parseFloat(String(v === undefined || v === null ? "" : v).replace(/\s/g, "").replace(",", "."));
    return Number.isFinite(n) ? n : 0;
}

export class CrafMatritsa extends Component {
    static template = "craf_matritsa.Page";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.actionService = useService("action");
        const ctx = (this.props.action && this.props.action.context) || {};
        this.state = useState({
            data: null,
            tab: TABS.includes(ctx.craf_tab) ? ctx.craf_tab : "matritsa",
            filter: "all", // matritsalar: all / ok / broken
            q: "",
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
        onWillStart(() => this.load());
    }

    // ================================================================ yuklash
    async load() {
        this.state.data = await this.orm.call(API, "get_data", []);
    }
    async refresh() {
        await this.load();
        this.env.bus.trigger("CRAF:NAV-REFRESH"); // pastki paneldagi sonlar
    }
    setTab(tab) {
        this.state.tab = tab;
        this.scrollRoot(0);
    }
    scrollRoot(top) {
        const root = document.querySelector(".o_craf_matritsa");
        if (root) {
            root.scrollTo(0, top);
        }
    }

    // ================================================================ format
    num(value, digits = 1) {
        return Number(value || 0).toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
    }
    errorText(e) {
        return (e && e.data && e.data.message) || (e && e.message) || String(e);
    }
    eq(a, b) {
        return Number(a) === b;
    }
    get pageTitle() {
        return { matritsa: "Matritsalar", gaz: "Gaz ballonlari", soda: "Kaustik soda", qoldiq: "Qoldiq" }[this.state.tab];
    }

    // ================================================================ matritsalar
    get matrixGroups() {
        const d = this.state.data;
        const q = this.state.q.trim().toLowerCase();
        const list = d.matrices.filter(
            (m) =>
                (this.state.filter === "all" || m.state === this.state.filter) &&
                (!q || m.name.toLowerCase().includes(q) || (m.section || "").toLowerCase().includes(q))
        );
        return d.sections
            .map((s) => ({ ...s, items: list.filter((m) => m.section_id === s.id) }))
            .filter((s) => s.items.length);
    }

    // ================================================================ varaqlar (alohida sahifa)
    openSheet(sheet) {
        if (!this.state.sheet) {
            const root = document.querySelector(".o_craf_matritsa");
            this.listScroll = root ? root.scrollTop : 0; // orqaga qaytganda ro'yxat shu joyda
        }
        setTimeout(() => this.scrollRoot(0));
        this.state.sheet = sheet;
    }
    closeSheet() {
        const was = this.state.sheet;
        this.state.sheet = null;
        if (was) {
            setTimeout(() => this.scrollRoot(this.listScroll || 0));
        }
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
    async options() {
        if (!this.opts) {
            this.opts = await this.orm.call(API, "form_options", []);
        }
        return this.opts;
    }
    newItem() {
        if (this.state.tab === "soda") {
            return this.openSoda();
        }
        if (this.state.tab === "gaz") {
            const first = this.state.data.gas.flatMap((g) => g.ballons.map((b) => ({ g, b })))[0];
            return first ? this.openGas(first.g, first.b) : null;
        }
        return this.openMatrix();
    }
    get newLabel() {
        return { matritsa: "Yangi matritsa", gaz: "Gaz sarfi", soda: "Soda olindi", qoldiq: "Yangi matritsa" }[this.state.tab];
    }

    // ---------------------------------------------------------------- matritsa
    async openMatrix(m = null) {
        await this.run(async () => {
            const o = await this.options();
            const f = m
                ? { id: m.id, name: m.name, section_id: m.section_id, note: m.note, state: m.state, broken_note: "" }
                : { id: false, name: "", section_id: "", note: "", state: "ok", broken_note: "" };
            this.openSheet({ type: "matrix", o, f, m });
        });
    }
    saveMatrix() {
        const s = this.state.sheet;
        if (!s.f.name.trim() || !s.f.section_id) {
            s.error = "Matritsa raqami va profilini (kesim) tanlang.";
            return;
        }
        this.run(async () => {
            const res = await this.orm.call(API, "matrix_save", [{ ...s.f, section_id: Number(s.f.section_id) }]);
            this.notification.add(`${res.name} saqlandi`, { type: "success" });
            this.closeSheet();
            await this.refresh();
        });
    }
    setMatrixState(state) {
        const s = this.state.sheet;
        const go = () =>
            this.run(async () => {
                await this.orm.call(API, "matrix_state", [s.f.id, state, s.f.broken_note]);
                this.notification.add(`${s.f.name} — ${state === "broken" ? "yaroqsiz" : "yaroqli"}`, { type: "success" });
                this.closeSheet();
                await this.refresh();
            });
        if (state === "broken") {
            this.confirm("Yaroqsiz", `${s.f.name} matritsasi yaroqsiz deb belgilanadi.`, "Yaroqsiz", go);
        } else {
            go();
        }
    }

    // ---------------------------------------------------------------- gaz sarfi
    openGas(g, b) {
        this.openSheet({ type: "gas", g, b, f: { ballon_id: b.id, qty: "", note: "" } });
    }
    pickBallon(s, b) {
        s.b = b;
        s.f.ballon_id = b.id;
    }
    gasLeft(s) {
        return s.b.qty - toNum(s.f.qty);
    }
    saveGas() {
        const s = this.state.sheet;
        const qty = toNum(s.f.qty);
        if (qty <= 0) {
            s.error = "Sarf miqdorini yozing.";
            return;
        }
        if (qty > s.b.qty) {
            s.error = `${s.b.name}: ballonda ${this.num(s.b.qty, 2)} ${s.g.unit} qolgan.`;
            return;
        }
        this.run(async () => {
            const res = await this.orm.call(API, "gaz_use", [s.f.ballon_id, s.f.qty, s.f.note]);
            this.notification.add(`${res.ballon}: ${res.qty} ${s.g.unit} sarf, qoldi ${res.left}`, { type: "success" });
            this.closeSheet();
            await this.refresh();
        });
    }

    // ---------------------------------------------------------------- kaustik soda
    async openSoda() {
        await this.run(async () => {
            const o = await this.options();
            const f = { date: o.today, employee_id: o.my_employee || false, qty: {}, note: "" };
            this.openSheet({ type: "soda", o, f });
        });
    }
    sodaTotal(s) {
        return this.state.data.soda.reduce((a, c) => a + toNum(s.f.qty[c.id]), 0);
    }
    saveSoda() {
        const s = this.state.sheet;
        if (this.sodaTotal(s) <= 0) {
            s.error = "Olingan kaustik soda miqdorini yozing (kg).";
            return;
        }
        const over = this.state.data.soda.filter((c) => toNum(s.f.qty[c.id]) > c.avail);
        if (over.length) {
            s.error = over.map((c) => `${c.name}: omborda ${this.num(c.avail, 2)} kg`).join("\n");
            return;
        }
        this.confirm("Kaustik soda olindi", `${this.num(this.sodaTotal(s), 2)} kg ombordan sarfga yechiladi.`, "Saqlash", () =>
            this.run(async () => {
                const res = await this.orm.call(API, "soda_save", [
                    { ...s.f, employee_id: s.f.employee_id ? Number(s.f.employee_id) : false },
                ]);
                this.notification.add(`${res.name}: ${res.total} kg kaustik soda yozildi`, { type: "success" });
                this.closeSheet();
                await this.refresh();
            })
        );
    }

    // ---------------------------------------------------------------- boshqa
    openList(xmlid) {
        this.actionService.doAction(xmlid);
    }
}

registry.category("actions").add("craf_matritsa", CrafMatritsa);
