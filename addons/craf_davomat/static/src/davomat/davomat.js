// Craf → Davomat: bugungi davomat, oylik tabel, KPI, terminallar — telefon birinchi.
// Ko'rinish Литейка / Sexlar / Pul sahifalari bilan bir xil (o_craf_litey uslublari), o'ziga xoslari dv-* klasslarida.
import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const API = "craf.davomat";
const TAB_KEY = "craf_davomat_tab";
const MONTHS = ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul", "Avgust", "Sentyabr", "Oktyabr", "Noyabr", "Dekabr"];
const DAYS7 = [
    ["1", "Du"], ["2", "Se"], ["3", "Ch"], ["4", "Pa"], ["5", "Ju"], ["6", "Sh"], ["7", "Ya"],
];

function addDays(iso, n) {
    const d = new Date(iso + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
}
function dmy(iso) {
    return iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : "";
}

export class CrafDavomat extends Component {
    static template = "craf_davomat.Davomat";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        let tab = "bugun";
        try {
            tab = window.localStorage.getItem(TAB_KEY) || "bugun";
        } catch {
            tab = "bugun";
        }
        this.days7 = DAYS7;
        this.state = useState({
            tab,
            day: false,
            year: false,
            month: false,
            dayData: null,
            monthData: null,
            kpiData: null,
            devData: null,
            loading: false,
            busy: false,
            sheet: null,
            q: "",
            filter: "all",
        });
        this.onKey = (ev) => {
            if (ev.key === "Escape" && this.state.sheet && !this.state.busy) {
                this.closeSheet();
            }
        };
        window.addEventListener("keydown", this.onKey);
        onWillUnmount(() => window.removeEventListener("keydown", this.onKey));
        onWillStart(() => this.loadTab());
    }

    // ================================================================ yuklash
    async loadTab() {
        this.state.loading = true;
        try {
            const t = this.state.tab;
            if (t === "bugun") {
                this.state.dayData = await this.orm.call(API, "get_day", [this.state.day || false]);
                this.state.day = this.state.dayData.day;
            } else if (t === "tabel") {
                this.state.monthData = await this.orm.call(API, "get_month", [this.state.year || false, this.state.month || false]);
                this.state.year = this.state.monthData.year;
                this.state.month = this.state.monthData.month;
            } else if (t === "kpi") {
                this.state.kpiData = await this.orm.call(API, "get_kpi", [this.state.year || false, this.state.month || false]);
                this.state.year = this.state.kpiData.year;
                this.state.month = this.state.kpiData.month;
            } else {
                this.state.devData = await this.orm.call(API, "devices", []);
            }
        } finally {
            this.state.loading = false;
        }
    }
    setTab(tab) {
        this.state.tab = tab;
        try {
            window.localStorage.setItem(TAB_KEY, tab);
        } catch {
            // brauzer xotirasi yopiq — e'tiborsiz
        }
        const root = document.querySelector(".o_craf_davomat");
        if (root) {
            root.scrollTo(0, 0);
        }
        this.loadTab();
    }
    get ready() {
        const t = this.state.tab;
        return Boolean(
            (t === "bugun" && this.state.dayData) || (t === "tabel" && this.state.monthData) ||
            (t === "kpi" && this.state.kpiData) || (t === "terminal" && this.state.devData)
        );
    }
    get roles() {
        const d = this.state.dayData || this.state.monthData || this.state.kpiData || this.state.devData;
        return (d && d.roles) || {};
    }

    // ================================================================ format
    num(value, digits = 1) {
        return Number(value || 0).toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
    }
    dmy(iso) {
        return dmy(iso);
    }
    toneClass(tone) {
        return { ok: "cl-ok", warn: "cl-warn", bad: "cl-bad" }[tone] || "";
    }
    errorText(e) {
        return (e && e.data && e.data.message) || (e && e.message) || String(e);
    }
    eq(a, b) {
        return String(a || "") === String(b || "");
    }
    get dayLabel() {
        const d = this.state.dayData;
        if (!d) {
            return "";
        }
        if (d.day === d.today) {
            return "Bugun";
        }
        if (d.day === addDays(d.today, -1)) {
            return "Kecha";
        }
        return `${dmy(d.day)}, ${d.weekday}`;
    }
    get monthLabel() {
        return this.state.month ? `${MONTHS[this.state.month - 1]} ${this.state.year}` : "";
    }
    hours(h) {
        if (!h) {
            return "";
        }
        const hh = Math.floor(h);
        const mm = Math.round((h - hh) * 60);
        return mm ? `${hh} s ${mm} daq` : `${hh} soat`;
    }
    gradeClass(g) {
        return { A: "dv-g-a", B: "dv-g-b", C: "dv-g-c", D: "dv-g-d" }[g] || "";
    }

    // ================================================================ kun
    shiftDay(n) {
        this.state.day = addDays(this.state.day, n);
        this.loadTab();
    }
    openDay() {
        this.openSheet({ type: "day", day: this.state.day });
    }
    applyDay(day) {
        this.closeSheet();
        this.state.day = day;
        this.loadTab();
    }
    get dayRows() {
        const d = this.state.dayData;
        const q = this.state.q.trim().toLowerCase();
        const f = this.state.filter;
        return d.rows.filter((r) => {
            if (q && !(r.name.toLowerCase().includes(q) || (r.terminal || "").includes(q) || (r.job || "").toLowerCase().includes(q))) {
                return false;
            }
            if (f === "late") {
                return r.late > 0;
            }
            return f === "all" || r.status === f;
        });
    }
    countStatus(st) {
        const rows = this.state.dayData.rows;
        return st === "late" ? rows.filter((r) => r.late > 0).length : rows.filter((r) => r.status === st).length;
    }

    // ================================================================ oy
    shiftMonth(n) {
        let m = this.state.month + n;
        let y = this.state.year;
        if (m < 1) {
            m = 12;
            y -= 1;
        } else if (m > 12) {
            m = 1;
            y += 1;
        }
        this.state.month = m;
        this.state.year = y;
        this.loadTab();
    }
    downloadTabel() {
        window.location.href = `/craf/davomat/tabel?year=${this.state.year}&month=${this.state.month}`;
    }
    cellClass(cell) {
        if (cell.late) {
            return "dv-c-late";
        }
        return { K: "dv-c-abs", D: "dv-c-rest" }[cell.code] || (cell.code ? "dv-c-work" : "");
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

    // ---------------------------------------------------------------- xodim
    async openEmployee(id) {
        let ok = false;
        await this.run(async () => {
            const byDay = this.state.tab === "bugun" && this.state.day;
            const y = byDay ? Number(this.state.day.slice(0, 4)) : this.state.year;
            const m = byDay ? Number(this.state.day.slice(5, 7)) : this.state.month;
            const e = await this.orm.call(API, "employee_detail", [id, y || false, m || false]);
            this.openSheet({ type: "emp", e, f: { terminal: e.terminal, schedule_id: e.schedule_id || "", place: e.place || "" } });
            ok = true;
        });
        return ok;
    }
    async saveEmployee() {
        const s = this.state.sheet;
        await this.run(async () => {
            await this.orm.call(API, "employee_save", [s.e.id, { terminal: s.f.terminal, schedule_id: s.f.schedule_id || false, place: s.f.place || false }]);
            this.notification.add(`${s.e.name}: saqlandi`, { type: "success" });
            await this.loadTab();
        });
    }
    newAttendance() {
        const e = this.state.sheet.e;
        const day = this.state.tab === "bugun" && this.state.day ? this.state.day : new Date().toISOString().slice(0, 10);
        this.openSheet({ type: "att", e, f: { id: false, employee_id: e.id, date: day, time_in: "08:00", time_out: "", out_next_day: false } });
    }
    editAttendance(row) {
        const e = this.state.sheet.e;
        this.openSheet({
            type: "att", e, row,
            f: { id: row.id, employee_id: e.id, date: row.date, time_in: row.in, time_out: row.out, out_next_day: Boolean(row.out_date && row.out_date !== row.date) },
        });
    }
    async saveAttendance() {
        const s = this.state.sheet;
        let ok = false;
        await this.run(async () => {
            await this.orm.call(API, "attendance_save", [s.f]);
            this.notification.add(`${s.e.name}: davomat saqlandi`, { type: "success" });
            ok = true;
        });
        if (ok) {
            await this.loadTab();
            await this.openEmployee(s.e.id);
        }
    }
    deleteAttendance() {
        const s = this.state.sheet;
        this.confirm("Davomatni o'chirish", `${s.e.name}: ${dmy(s.f.date)} ${s.f.time_in}–${s.f.time_out || "…"} o'chiriladi.`, "O'chirish", async () => {
            let ok = false;
            await this.run(async () => {
                await this.orm.call(API, "attendance_delete", [s.f.id]);
                ok = true;
            });
            if (ok) {
                await this.loadTab();
                await this.openEmployee(s.e.id);
            }
        });
    }
    backToEmployee() {
        this.openEmployee(this.state.sheet.e.id);
    }

    // ---------------------------------------------------------------- KPI sozlamasi
    openKpiSettings() {
        this.openSheet({ type: "kpiset", f: { ...this.state.kpiData.settings } });
    }
    async saveKpiSettings() {
        const s = this.state.sheet;
        await this.run(async () => {
            await this.orm.call(API, "kpi_settings_save", [s.f]);
            this.notification.add("KPI sozlamasi saqlandi", { type: "success" });
            this.closeSheet();
            await this.loadTab();
        });
    }

    // ---------------------------------------------------------------- terminallar
    openDevice(dev = null) {
        this.openSheet({
            type: "dev",
            d: dev,
            f: dev ? { id: dev.id, name: dev.name, place: dev.place, serial: dev.serial, note: dev.note, active: dev.active } : { id: false, name: "", place: "zavod", serial: "", note: "", active: true },
            testEmp: "",
            testResult: "",
        });
    }
    async saveDevice() {
        const s = this.state.sheet;
        await this.run(async () => {
            const res = await this.orm.call(API, "device_save", [s.f]);
            this.notification.add(`${s.f.name}: saqlandi`, { type: "success" });
            await this.loadTab();
            const dev = this.state.devData.devices.find((d) => d.id === res.id);
            if (dev && !s.f.id) {
                this.openDevice(dev);
            } else {
                this.closeSheet();
            }
        });
    }
    copyUrl(url) {
        try {
            navigator.clipboard.writeText(url);
            this.notification.add("Manzil nusxalandi", { type: "info" });
        } catch {
            this.notification.add("Nusxalab bo'lmadi — qo'lda belgilang.", { type: "warning" });
        }
    }
    get withTerminal() {
        return (this.state.devData ? this.state.devData.employees : []).filter((e) => e.terminal);
    }
    async testDevice() {
        const s = this.state.sheet;
        if (!s.testEmp) {
            s.error = "Xodimni tanlang (Terminal ID si bor).";
            return;
        }
        await this.run(async () => {
            const res = await this.orm.call(API, "device_test", [s.f.id, Number(s.testEmp)]);
            s.testResult = `${res.label}${res.action ? " — " + (res.action === "in" ? "kirish" : "chiqish") : ""}${res.note ? " (" + res.note + ")" : ""}`;
            this.state.devData = await this.orm.call(API, "devices", []);
        });
    }
    openAssign(u) {
        this.openSheet({ type: "assign", u, emp: "" });
    }
    async saveAssign() {
        const s = this.state.sheet;
        if (!s.emp) {
            s.error = "Xodimni tanlang.";
            return;
        }
        await this.run(async () => {
            const res = await this.orm.call(API, "log_assign", [s.u.no, Number(s.emp)]);
            this.notification.add(`Terminal ID ${s.u.no} biriktirildi: ${res.done} / ${res.count} yozuv davomatga o'tdi`, { type: "success" });
            this.closeSheet();
            await this.loadTab();
        });
    }
    async openSchedules() {
        await this.run(async () => {
            const rows = await this.orm.call(API, "schedules", []);
            this.openSheet({ type: "scheds", rows });
        });
    }
    editSchedule(row = null) {
        this.openSheet({
            type: "sched",
            f: row ? { id: row.id, name: row.name, start: row.start, end: row.end, break: row.break, grace: row.grace, days: row.days }
                : { id: false, name: "", start: "08:00", end: "17:00", break: 1, grace: 10, days: "123456" },
        });
    }
    toggleDay(key) {
        const f = this.state.sheet.f;
        f.days = f.days.includes(key) ? f.days.replace(key, "") : f.days + key;
    }
    async saveSchedule() {
        const s = this.state.sheet;
        let ok = false;
        await this.run(async () => {
            await this.orm.call(API, "schedule_save", [s.f]);
            ok = true;
        });
        if (ok) {
            this.notification.add("Ish jadvali saqlandi", { type: "success" });
            await this.openSchedules();
        }
    }
    goLogs() {
        this.closeSheet();
        this.actionService.doAction("craf_davomat.action_craf_davomat_log");
    }
}

registry.category("actions").add("craf_davomat", CrafDavomat);
