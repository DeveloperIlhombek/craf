// Craf → Pul: qarzlar, to'lovlar, narxlar — telefon birinchi.
// Ko'rinish Литейка / Sexlar sahifalari bilan bir xil (o_craf_litey uslublari), pulga xos qismlari pl-* klasslarida.
import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { parseSum } from "@craf_litey/litey/litey";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const API = "craf.pul";
const TAB_KEY = "craf_pul_tab";
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
/** "1 500 000", "1500000+250000", "1,5" → son; bo'sh → null; noto'g'ri → NaN */
function parseMoney(text) {
    const raw = String(text === undefined || text === null ? "" : text).replace(/[\s ]/g, "").replace(/,/g, ".");
    if (!raw) {
        return null;
    }
    return parseSum(raw);
}

export class CrafPul extends Component {
    static template = "craf_pul.Pul";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        let tab = "qarz";
        try {
            tab = window.localStorage.getItem(TAB_KEY) || "qarz";
        } catch {
            tab = "qarz";
        }
        this.state = useState({
            data: null,
            loading: true,
            tab,
            side: "customer",
            q: "",
            from: false,
            to: false,
            sheet: null,
            busy: false,
            prices: null,
            priceQ: "",
            priceFilter: "all",
            edits: {},
            bulkKg: "",
        });
        this.onKey = (ev) => {
            if (ev.key === "Escape" && this.state.sheet && !this.state.busy) {
                this.closeSheet();
            }
        };
        window.addEventListener("keydown", this.onKey);
        onWillUnmount(() => window.removeEventListener("keydown", this.onKey));
        onWillStart(async () => {
            await this.load();
            if (this.state.tab === "narx") {
                await this.loadPrices();
            }
        });
    }

    // ================================================================ yuklash
    async load(from, to) {
        this.state.loading = true;
        try {
            const data = await this.orm.call(API, "get_data", [
                (from === undefined ? this.state.from : from) || false,
                (to === undefined ? this.state.to : to) || false,
            ]);
            this.state.data = data;
            this.state.from = data.date_from;
            this.state.to = data.date_to;
        } finally {
            this.state.loading = false;
        }
    }
    refresh() {
        return this.load();
    }
    async loadPrices() {
        const res = await this.orm.call(API, "prices", []);
        this.state.prices = res.rows;
        this.state.edits = {};
    }
    setTab(tab) {
        this.state.tab = tab;
        try {
            window.localStorage.setItem(TAB_KEY, tab);
        } catch {
            // brauzer xotirasi yopiq bo'lsa — e'tiborsiz
        }
        const root = document.querySelector(".o_craf_pul");
        if (root) {
            root.scrollTo(0, 0);
        }
        if (tab === "narx" && !this.state.prices) {
            this.loadPrices();
        }
    }

    // ================================================================ format
    num(value, digits = 0) {
        return Number(value || 0).toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
    }
    money(value) {
        return this.num(Math.round(Number(value || 0)), 0);
    }
    /** KPI uchun qisqa: 14,2 mln; 950 ming */
    short(value) {
        const v = Math.abs(Number(value || 0));
        const sign = Number(value || 0) < 0 ? "−" : "";
        if (v >= 1e9) {
            return sign + this.num(v / 1e9, v >= 1e10 ? 1 : 2);
        }
        if (v >= 1e6) {
            return sign + this.num(v / 1e6, v >= 1e8 ? 0 : 1);
        }
        if (v >= 1e4) {
            return sign + this.num(v / 1e3, 0);
        }
        return sign + this.num(v, 0);
    }
    shortUnit(value) {
        const v = Math.abs(Number(value || 0));
        const unit = v >= 1e9 ? "mlrd" : v >= 1e6 ? "mln" : v >= 1e4 ? "ming" : "";
        return unit ? `${unit} ${this.cur}` : this.cur;
    }
    fmtInput(text) {
        const v = parseMoney(text);
        return v !== null && Number.isFinite(v) && /^[\d\s.,]+$/.test(String(text)) ? this.num(v, 2) : text;
    }
    get cur() {
        return (this.state.data && this.state.data.currency.symbol) || "";
    }
    dmy(iso) {
        return dmy(iso);
    }
    dm(iso) {
        return dm(iso);
    }
    errorText(e) {
        return (e && e.data && e.data.message) || (e && e.message) || String(e);
    }
    toneClass(tone) {
        return { ok: "cl-ok", warn: "cl-warn", bad: "cl-bad" }[tone] || "";
    }
    eq(a, b) {
        return Number(a) === b;
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
    get canEdit() {
        return Boolean(this.state.data && this.state.data.roles.accountant);
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
        this.load(f, t);
    }
    applyPeriod() {
        const s = this.state.sheet;
        if (s.from && s.to) {
            this.closeSheet();
            this.load(s.from, s.to);
        }
    }
    shift(dir) {
        const span = Math.round((new Date(this.state.to) - new Date(this.state.from)) / 86400000) + 1;
        this.load(addDays(this.state.from, dir * span), addDays(this.state.to, dir * span));
    }

    // ================================================================ qarzlar
    get partnerList() {
        const d = this.state.data;
        const list = this.state.side === "customer" ? d.customers : d.suppliers;
        const q = this.state.q.trim().toLowerCase();
        return q ? list.filter((p) => p.name.toLowerCase().includes(q) || (p.phone || "").includes(q)) : list;
    }
    sideTotal(side) {
        const list = side === "customer" ? this.state.data.customers : this.state.data.suppliers;
        return list.filter((p) => p.balance > 0).reduce((s, p) => s + p.balance, 0);
    }

    // ================================================================ to'lovlar ro'yxati
    get payGroups() {
        const groups = [];
        let current = null;
        for (const p of this.state.data.payments) {
            if (!current || current.date !== p.date) {
                current = { date: p.date, label: dmy(p.date), weekday: WEEKDAYS[(new Date(p.date).getUTCDay() + 6) % 7], rows: [], inc: 0, out: 0 };
                groups.push(current);
            }
            current.rows.push(p);
            if (p.kind === "in") {
                current.inc += p.amount;
            } else {
                current.out += p.amount;
            }
        }
        return groups;
    }
    methodIcon(method) {
        return { naqd: "fa-money", plastik: "fa-credit-card", bank: "fa-university" }[method] || "fa-exchange";
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

    // ---------------------------------------------------------------- to'lov qo'shish
    async newPayment(partnerType = null, partner = null) {
        const type = partnerType || (this.state.tab === "qarz" ? this.state.side : "customer");
        await this.run(async () => {
            const o = await this.orm.call(API, "payment_options", [type]);
            const naqd = o.journals.find((j) => j.method === "naqd") || o.journals[0] || {};
            this.openSheet({
                type: "pay", o, partnerType: type, q: partner ? partner.name : "",
                f: { partner_id: partner ? partner.id : false, partner_name: "", amount: "", journal_id: naqd.id || false, date: o.today, memo: "" },
                partner: partner ? { id: partner.id, name: partner.name, balance: partner.balance } : null,
            });
        });
    }
    async setPayType(type) {
        const s = this.state.sheet;
        if (s.partnerType === type) {
            return;
        }
        await this.run(async () => {
            s.o = await this.orm.call(API, "payment_options", [type]);
            s.partnerType = type;
            s.partner = null;
            s.f.partner_id = false;
            s.q = "";
        });
    }
    get payMatches() {
        const s = this.state.sheet;
        const q = (s.q || "").trim().toLowerCase();
        const list = s.o.partners;
        const found = q ? list.filter((p) => p.name.toLowerCase().includes(q)) : list.filter((p) => p.balance > 0.5);
        return found.slice(0, 8);
    }
    get payNewName() {
        const s = this.state.sheet;
        const q = (s.q || "").trim();
        if (!q || s.o.partners.some((p) => p.name.toLowerCase() === q.toLowerCase())) {
            return "";
        }
        return q;
    }
    pickPartner(p) {
        const s = this.state.sheet;
        s.partner = p;
        s.f.partner_id = p.id;
        s.f.partner_name = "";
        s.q = p.name;
    }
    pickNewPartner() {
        const s = this.state.sheet;
        s.partner = { id: false, name: this.payNewName, balance: 0, isNew: true };
        s.f.partner_id = false;
        s.f.partner_name = this.payNewName;
    }
    clearPartner() {
        const s = this.state.sheet;
        s.partner = null;
        s.f.partner_id = false;
        s.f.partner_name = "";
    }
    get payPreview() {
        const s = this.state.sheet;
        const amount = parseMoney(s.f.amount);
        const ok = amount !== null && Number.isFinite(amount) && amount > 0;
        const before = s.partner ? s.partner.balance : 0;
        return { amount: ok ? amount : 0, ok, bad: amount !== null && !ok, before, after: before - (ok ? amount : 0) };
    }
    async savePayment() {
        const s = this.state.sheet;
        if (!s.partner) {
            s.error = s.partnerType === "customer" ? "Mijozni tanlang." : "Yetkazib beruvchini tanlang.";
            return;
        }
        const p = this.payPreview;
        if (!p.ok) {
            s.error = "Summani raqam bilan yozing, masalan 1 500 000.";
            return;
        }
        const back = s.back;
        let saved = false;
        await this.run(async () => {
            const res = await this.orm.call(API, "payment_save", [{ ...s.f, partner_type: s.partnerType }]);
            this.notification.add(`${res.partner}: ${this.money(res.amount)} ${this.cur} — ${res.name}`, { type: "success" });
            saved = true;
            this.closeSheet();
            await this.refresh();
        });
        if (saved && back) {
            await this.openPartner({ id: back.id, name: back.name }, back.kind);
        }
    }

    // ---------------------------------------------------------------- hamkor (akt sverka)
    async openPartner(partner, kind = null, from = false, to = false) {
        const k = kind || this.state.side;
        await this.run(async () => {
            const d = await this.orm.call(API, "partner_detail", [partner.id, k, from, to]);
            this.openSheet({ type: "partner", d, from: d.date_from, to: d.date_to });
        });
    }
    reloadPartner() {
        const s = this.state.sheet;
        this.openPartner(s.d.partner, s.d.kind, s.from, s.to);
    }
    partnerPay() {
        const d = this.state.sheet.d;
        this.closeSheet();
        this.newPayment(d.kind, { id: d.partner.id, name: d.partner.name, balance: d.current }).then(() => {
            if (this.state.sheet && this.state.sheet.type === "pay") {
                this.state.sheet.back = { id: d.partner.id, name: d.partner.name, kind: d.kind };
            }
        });
    }
    downloadAkt() {
        const s = this.state.sheet;
        const d = s.d;
        const url = `/craf/pul/akt?partner_id=${d.partner.id}&kind=${d.kind}&date_from=${s.from}&date_to=${s.to}`;
        window.location.href = url;
    }
    openRow(row) {
        if (row.payment_id) {
            this.openPaymentDetail(row.payment_id);
        } else {
            this.closeSheet();
            this.actionService.doAction(
                { type: "ir.actions.act_window", res_model: "account.move", res_id: row.move_id, views: [[false, "form"]] },
                { onClose: () => this.refresh() }
            );
        }
    }

    // ---------------------------------------------------------------- to'lov tafsiloti
    async openPaymentDetail(id) {
        await this.run(async () => {
            const p = await this.orm.call(API, "payment_detail", [id]);
            this.openSheet({ type: "paydoc", p });
        });
    }
    paymentAction(p, action) {
        const go = () =>
            this.run(async () => {
                await this.orm.call(API, "payment_action", [p.id, action]);
                const msg = { cancel: "bekor qilindi", c1: "1C ga kiritildi deb belgilandi", c1_undo: "1C belgisi olindi" }[action];
                this.notification.add(`${p.name} ${msg}`, { type: "success" });
                this.closeSheet();
                await this.refresh();
            });
        if (action === "cancel") {
            this.confirm("To'lovni bekor qilish", `${p.name} (${p.partner}, ${this.money(p.amount)} ${this.cur}) bekor qilinadi — qarz qayta ochiladi.`, "Bekor qilish", go);
        } else {
            go();
        }
    }

    // ---------------------------------------------------------------- narx kerak (buyurtma)
    openNoprice() {
        this.openSheet({ type: "noprice" });
    }
    async openOrder(id) {
        await this.run(async () => {
            const o = await this.orm.call(API, "order_detail", [id]);
            const prices = {};
            for (const l of o.lines) {
                prices[l.id] = l.price ? String(l.price) : l.list_price ? String(l.list_price) : "";
            }
            this.openSheet({ type: "order", o, prices });
        });
    }
    orderTotal(s) {
        let total = 0;
        for (const l of s.o.lines) {
            const p = parseMoney(s.prices[l.id]);
            if (p && Number.isFinite(p)) {
                total += p * (l.delivered || l.qty);
            }
        }
        return total;
    }
    async saveOrder() {
        const s = this.state.sheet;
        for (const l of s.o.lines) {
            const p = parseMoney(s.prices[l.id]);
            if (p === null || !Number.isFinite(p) || p <= 1) {
                s.error = `${l.name}: narxni yozing.`;
                return;
            }
        }
        await this.run(async () => {
            const res = await this.orm.call(API, "order_prices_save", [s.o.id, s.prices]);
            this.notification.add(`${res.name}: hisob-faktura ${this.money(res.amount)} ${this.cur}`, { type: "success" });
            this.closeSheet();
            await this.refresh();
        });
    }

    // ---------------------------------------------------------------- hisob-fakturasiz kirim
    openUnbilled() {
        this.openSheet({ type: "unbilled" });
    }
    async openReceipt(id) {
        await this.run(async () => {
            const r = await this.orm.call(API, "receipt_detail", [id]);
            const prices = {};
            for (const l of r.lines) {
                prices[l.id] = l.price ? String(l.price) : "";
            }
            this.openSheet({ type: "receipt", r, prices, partner: r.partner });
        });
    }
    receiptTotal(s) {
        let total = 0;
        for (const l of s.r.lines) {
            const p = parseMoney(s.prices[l.id]);
            if (p && Number.isFinite(p)) {
                total += p * l.qty;
            }
        }
        return total;
    }
    async saveReceipt() {
        const s = this.state.sheet;
        if (!(s.partner || "").trim()) {
            s.error = "Yetkazib beruvchini yozing.";
            return;
        }
        for (const l of s.r.lines) {
            const p = parseMoney(s.prices[l.id]);
            if (p === null || !Number.isFinite(p) || p <= 0) {
                s.error = `${l.name}: narxni yozing.`;
                return;
            }
        }
        await this.run(async () => {
            const res = await this.orm.call(API, "receipt_bill_save", [s.r.id, { partner_name: s.partner, prices: s.prices }]);
            this.notification.add(`${res.name}: hisob-faktura ${res.bill} — ${this.money(res.amount)} ${this.cur}`, { type: "success" });
            this.closeSheet();
            await this.refresh();
        });
    }

    // ================================================================ narxlar
    get priceChips() {
        const rows = this.state.prices || [];
        const colors = [...new Set(rows.map((r) => r.color).filter(Boolean))];
        return colors;
    }
    get priceMissingCount() {
        return (this.state.prices || []).filter((r) => !this.rowPrice(r)).length;
    }
    get priceRows() {
        const q = this.state.priceQ.trim().toLowerCase();
        const f = this.state.priceFilter;
        return (this.state.prices || []).filter((r) => {
            if (q && !(r.name.toLowerCase().includes(q) || r.code.toLowerCase().includes(q) || r.section.toLowerCase().includes(q))) {
                return false;
            }
            if (f === "missing") {
                return !this.rowPrice(r);
            }
            if (f !== "all") {
                return r.color === f;
            }
            return true;
        });
    }
    get priceGroups() {
        const groups = [];
        let current = null;
        for (const r of this.priceRows) {
            if (!current || current.section !== r.section) {
                current = { section: r.section, rows: [] };
                groups.push(current);
            }
            current.rows.push(r);
        }
        return groups;
    }
    /** Tahrirlangan yoki saqlangan dona narxi */
    rowPrice(r) {
        const e = this.state.edits[r.id];
        if (e) {
            if (e.price_kg !== undefined) {
                const kg = parseMoney(e.price_kg);
                return kg && Number.isFinite(kg) && r.kg_pc ? Math.round(kg * r.kg_pc) : 0;
            }
            const p = parseMoney(e.price);
            return p && Number.isFinite(p) ? Math.round(p) : 0;
        }
        return r.price;
    }
    kgValue(r) {
        const e = this.state.edits[r.id];
        if (e && e.price_kg !== undefined) {
            return e.price_kg;
        }
        const p = this.rowPrice(r);
        return p && r.kg_pc ? String(Math.round(p / r.kg_pc)) : "";
    }
    pcValue(r) {
        const e = this.state.edits[r.id];
        if (e && e.price !== undefined) {
            return e.price;
        }
        const p = this.rowPrice(r);
        return p ? String(p) : "";
    }
    setKg(r, ev) {
        this.state.edits[r.id] = { price_kg: ev.target.value };
    }
    setPc(r, ev) {
        this.state.edits[r.id] = { price: ev.target.value };
    }
    isEdited(r) {
        return Boolean(this.state.edits[r.id]);
    }
    get editCount() {
        return Object.keys(this.state.edits).length;
    }
    applyBulk() {
        const kg = parseMoney(this.state.bulkKg);
        if (!kg || !Number.isFinite(kg)) {
            this.notification.add("1 kg narxini raqam bilan yozing.", { type: "warning" });
            return;
        }
        let n = 0;
        for (const r of this.priceRows) {
            if (r.kg_pc) {
                this.state.edits[r.id] = { price_kg: String(kg) };
                n++;
            }
        }
        this.notification.add(`${n} ta mahsulotga 1 kg = ${this.money(kg)} ${this.cur} (saqlang)`, { type: "info" });
    }
    cancelEdits() {
        this.state.edits = {};
    }
    async savePrices() {
        const changes = Object.entries(this.state.edits).map(([id, e]) => ({ id: Number(id), ...e }));
        await this.run(async () => {
            const res = await this.orm.call(API, "prices_save", [changes]);
            this.notification.add(`${res.count} ta narx saqlandi`, { type: "success" });
            await this.loadPrices();
            await this.refresh();
        });
    }
    demoPrices() {
        this.closeSheet();
        this.confirm(
            "Namuna narxlar",
            "Narxi yo'q mahsulotlarga sinov uchun 1 kg narxi qo'yiladi: bo'yalmagan 45 000, oq va antratsit 52 000, 7016 MATT 56 000, Золотой Дуб 58 000 so'm. Keyin o'zgartirishingiz mumkin.",
            "Qo'yish",
            () =>
                this.run(async () => {
                    const res = await this.orm.call(API, "prices_demo", []);
                    this.notification.add(`${res.count} ta mahsulotga namuna narx qo'yildi`, { type: "success" });
                    await this.loadPrices();
                    await this.refresh();
                })
        );
    }

    // ================================================================ menyu, sozlash
    openMenu() {
        this.openSheet({ type: "menu" });
    }
    go(action) {
        this.closeSheet();
        this.actionService.doAction(action);
    }
    goList(model, name, domain = []) {
        this.closeSheet();
        this.actionService.doAction({ type: "ir.actions.act_window", name, res_model: model, domain, views: [[false, "list"], [false, "form"]] });
    }
    menuRefresh() {
        this.closeSheet();
        this.refresh();
    }
    runSetup() {
        this.closeSheet();
        this.run(async () => {
            await this.orm.call(API, "setup_run", []);
            this.notification.add("Sozlash tekshirildi: Naqd / Plastik / Bank kassalari, soliqsiz narx, sotuvda narx", { type: "success" });
            await this.refresh();
        });
    }
    switchCurrency() {
        const s = this.state.data.setup;
        this.confirm(
            "Valyutani so'mga o'tkazish",
            s.moves
                ? `Kompaniya valyutasi ${s.currency} → UZS. ${s.moves} ta qoralama buxgalteriya yozuvi (sinov hisob-fakturalari) o'chiriladi.`
                : `Kompaniya valyutasi ${s.currency} → UZS.`,
            "O'tkazish",
            () =>
                this.run(async () => {
                    await this.orm.call(API, "setup_switch_currency", []);
                    this.notification.add("Valyuta: so'm", { type: "success" });
                    await this.refresh();
                })
        );
    }
}

registry.category("actions").add("craf_pul", CrafPul);
