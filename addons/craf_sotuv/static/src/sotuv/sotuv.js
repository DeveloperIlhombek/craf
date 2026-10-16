import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { scanBarcode } from "@web/core/barcode/barcode_dialog";
import { isBarcodeScannerSupported } from "@web/core/barcode/barcode_video_scanner";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { debounce } from "@web/core/utils/timing";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const MODEL = "craf.sotuv";
const STORE_KEY = "craf_sotuv_draft_v1";

function fmtNum(value, digits = 0) {
    const v = Number(value || 0);
    return v.toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

function packsText(pcs, perPack) {
    pcs = Math.round(pcs || 0);
    if (!perPack) {
        return `${fmtNum(pcs)} dona`;
    }
    const packs = Math.floor(pcs / perPack);
    const rest = pcs - packs * perPack;
    if (packs && rest) {
        return `${fmtNum(packs)} p + ${rest} d`;
    }
    if (packs) {
        return `${fmtNum(packs)} pachka`;
    }
    return `${rest} dona`;
}

function nowLocal() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export class CrafSotuv extends Component {
    static template = "craf_sotuv.Sotuv";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.busService = useService("bus_service");
        this.canScan = isBarcodeScannerSupported();
        this.state = useState({
            tab: "new",
            load: { queue: null, current: null, edit: null, scan: "", result: null, finish: false, busy: false, photoBusy: false },
            photoView: null,
            salesFilter: "all",
            init: null,
            text: "",
            orders: [],
            products: {},
            busy: false,
            done: [],
            picker: null,
            partnerDrop: null,
            sales: null,
            stock: null,
            stockLoc: false,
            stockQuery: "",
            stockAll: false,
            settings: false,
            expanded: {},
        });
        this.searchProducts = debounce(this._searchProducts.bind(this), 250);
        this.searchPartners = debounce(this._searchPartners.bind(this), 250);
        this.searchStock = debounce(() => this.loadStock(), 300);
        onWillStart(async () => {
            this.state.init = await this.orm.call(MODEL, "get_init", []);
            this.state.stockLoc = this.state.init.default_location_id;
            const wanted = (this.props.action && this.props.action.context && this.props.action.context.craf_tab) || "";
            const tabs = this.tabs.map((t) => t.key);
            this.state.tab = tabs.includes(wanted) ? wanted : tabs[0];
            if (this.state.init.is_seller) {
                this.restoreDraft();
            }
            if (this.state.tab === "load") {
                await this.loadQueue();
            }
        });
        this._onBus = (payload) => this.onBusUpdate(payload);
        onMounted(() => {
            this.busService.subscribe("craf_sotuv_update", this._onBus);
            if (!this.busService.isActive) {
                this.busService.start();
            }
            this._timer = setInterval(() => this.poll(), 30000);
        });
        onWillUnmount(() => {
            this.busService.unsubscribe("craf_sotuv_update", this._onBus);
            clearInterval(this._timer);
        });
    }

    // ------------------------------------------------------------------ rol va yangilanish
    get tabs() {
        const init = this.state.init;
        const out = [];
        if (init.is_seller) {
            out.push({ key: "new", label: "Buyurtma", icon: "fa-pencil-square-o", count: this.state.orders.length });
        }
        out.push({ key: "load", label: "Yuklash", icon: "fa-truck", count: init.queue_count || 0 });
        out.push({ key: "sales", label: init.is_seller ? "Sotuvlar" : "Bugun", icon: "fa-list-ul", count: 0 });
        out.push({ key: "stock", label: "Qoldiq", icon: "fa-cubes", count: 0 });
        return out;
    }
    async onBusUpdate() {
        await this.refreshActive(true);
    }
    poll() {
        if (document.visibilityState === "visible") {
            this.refreshActive(false);
        }
    }
    async refreshActive(fromBus) {
        const before = this.state.init.queue_count || 0;
        if (this.state.tab === "load") {
            if (this.state.load.current && !this.state.load.busy && !this.state.load.edit) {
                await this.reloadCurrent();
            } else if (!this.state.load.current) {
                await this.loadQueue();
            }
        } else if (this.state.tab === "sales" && this.state.sales) {
            await this.loadSales();
        }
        if (this.state.tab !== "load" || this.state.load.current) {
            const q = await this.orm.call(MODEL, "load_queue", []);
            this.state.init.queue_count = q.count;
        }
        if (fromBus && this.state.init.queue_count > before && !this.state.init.is_seller) {
            try {
                navigator.vibrate && navigator.vibrate([200, 100, 200]);
            } catch {
                // tebranish yo'q
            }
        }
    }

    // ------------------------------------------------------------------ umumiy
    fmt(v, d = 0) {
        return fmtNum(v, d);
    }
    get locations() {
        return this.state.init ? this.state.init.locations : [];
    }
    locLabel(id) {
        const loc = this.locations.find((l) => l.id === id);
        return loc ? loc.label : "";
    }
    setTab(tab) {
        this.state.tab = tab;
        if (tab === "load" && !this.state.load.current) {
            this.loadQueue();
        }
        if (tab === "sales" && !this.state.sales) {
            this.loadSales();
        }
        if (tab === "stock" && !this.state.stock) {
            this.loadStock();
        }
    }
    errorText(e) {
        return (e && e.data && e.data.message) || (e && e.message) || String(e);
    }
    saveDraft() {
        try {
            const { orders, products, text } = this.state;
            if (orders.length || text) {
                localStorage.setItem(STORE_KEY, JSON.stringify({ orders, products, text }));
            } else {
                localStorage.removeItem(STORE_KEY);
            }
        } catch {
            // brauzer xotirasi yo'q — muhim emas
        }
    }
    restoreDraft() {
        try {
            const raw = localStorage.getItem(STORE_KEY);
            if (raw) {
                const data = JSON.parse(raw);
                this.state.orders = data.orders || [];
                this.state.products = data.products || {};
                this.state.text = data.text || "";
            }
        } catch {
            // e'tiborsiz
        }
    }

    // ------------------------------------------------------------------ matn va fayl
    onText(ev) {
        this.state.text = ev.target.value;
        this.saveDraft();
    }
    async parseText() {
        const text = this.state.text.trim();
        if (!text) {
            this.notification.add("Buyurtmani yozing: 1-qator mijoz, keyin mahsulotlar", { type: "warning" });
            return;
        }
        await this._parse({ text });
        this.state.text = "";
        this.saveDraft();
    }
    async _parse({ text = false, messages = false }) {
        this.state.busy = true;
        try {
            const res = await this.orm.call(MODEL, "parse", [], {
                text,
                messages,
                location_id: this.state.init.default_location_id,
            });
            Object.assign(this.state.products, res.products);
            const known = new Set(this.state.orders.map((o) => o.key));
            let added = 0;
            let dups = 0;
            for (const order of res.orders) {
                if (known.has(order.key)) {
                    continue;
                }
                order.error = "";
                order.date = order.date || nowLocal();
                order.force = false;
                order.scan = "";
                this.state.orders.push(order);
                added++;
                if (order.duplicate) {
                    dups++;
                }
            }
            const msg = added
                ? (added === 1 ? "Buyurtma tayyor — tekshirib, yuklovchiga yuboring" : `${added} ta buyurtma tayyor`) +
                  (dups ? ` (${dups} tasi avval kiritilgan)` : "")
                : "Buyurtma topilmadi";
            this.notification.add(msg, { type: added ? "success" : "warning" });
            this.saveDraft();
        } finally {
            this.state.busy = false;
        }
    }
    newManual() {
        this.state.orders.unshift({
            key: `m${Date.now()}`,
            date: nowLocal(),
            raw: "",
            customer: "",
            partner: false,
            partner_is_new: true,
            partner_suggestions: [],
            location_id: this.state.init.default_location_id,
            notes: [],
            lines: [],
            duplicate: false,
            error: "",
            force: false,
            scan: "",
            manual: true,
        });
        this.saveDraft();
    }
    removeOrder(order) {
        const i = this.state.orders.indexOf(order);
        if (i >= 0) {
            this.state.orders.splice(i, 1);
        }
        this.saveDraft();
    }
    clearAll() {
        this.dialog.add(ConfirmationDialog, {
            title: "Ro'yxatni tozalash",
            body: `${this.state.orders.length} ta qoralama sotuv o'chiriladi (bazaga hech narsa yozilmaydi).`,
            confirmLabel: "Tozalash",
            confirm: () => {
                this.state.orders.splice(0);
                this.saveDraft();
            },
            cancel: () => {},
        });
    }

    // ------------------------------------------------------------------ qator hisobi
    product(id) {
        return id ? this.state.products[id] : null;
    }
    linePcs(line) {
        const p = this.product(line.product_id);
        const per = p ? p.per_pack : 0;
        return (Number(line.packs) || 0) * per + (Number(line.extra) || 0);
    }
    lineKg(line) {
        const p = this.product(line.product_id);
        return p ? this.linePcs(line) * (p.kg_pc || 0) : 0;
    }
    avail(order, productId) {
        const p = this.product(productId);
        if (!p || !p.avail || !(order.location_id in p.avail)) {
            return null;
        }
        return p.avail[order.location_id];
    }
    need(order, productId) {
        return order.lines
            .filter((l) => l.product_id === productId)
            .reduce((s, l) => s + this.linePcs(l), 0);
    }
    lineShortHere(order, line) {
        if (!line.product_id) {
            return false;
        }
        const have = this.avail(order, line.product_id);
        return have !== null && this.need(order, line.product_id) > have + 1e-6;
    }
    lineShort(order, line) {
        // hamma sotuv joylarida ham yetmasa
        if (!this.lineShortHere(order, line)) {
            return false;
        }
        const p = this.product(line.product_id);
        const all = p && p.avail_all !== undefined ? p.avail_all : null;
        return all === null || this.need(order, line.product_id) > all + 1e-6;
    }
    availOther(order, line) {
        const p = this.product(line.product_id);
        if (!p || p.avail_all === undefined) {
            return "";
        }
        return packsText(p.avail_all, p.per_pack);
    }
    availShort(p, have) {
        if (have === null || have === undefined) {
            return "";
        }
        return have < 0 ? `${fmtNum(have)} dona` : packsText(have, p && p.per_pack);
    }
    availText(order, line) {
        const have = this.avail(order, line.product_id);
        if (have === null) {
            return "";
        }
        const p = this.product(line.product_id);
        return have < 0 ? `${fmtNum(have)} dona` : packsText(have, p.per_pack);
    }
    lineBad(line) {
        const qty = (Number(line.packs) || 0) + (Number(line.extra) || 0);
        if (!qty) {
            return false;
        }
        if (!line.product_id) {
            return true;
        }
        const p = this.product(line.product_id);
        return Boolean(line.packs) && !(p && p.per_pack);
    }
    orderTotals(order) {
        let pcs = 0;
        let kg = 0;
        let packs = 0;
        let extra = 0;
        for (const l of order.lines) {
            pcs += this.linePcs(l);
            kg += this.lineKg(l);
            packs += Number(l.packs) || 0;
            extra += Number(l.extra) || 0;
        }
        return { pcs, kg, packs, extra, count: order.lines.filter((l) => this.linePcs(l) > 0).length };
    }
    orderProblems(order, forGive = true) {
        const out = [];
        if (!(order.customer || "").trim() && !order.partner) {
            out.push("Mijoz yozilmagan");
        }
        const bad = order.lines.filter((l) => this.lineBad(l));
        if (bad.length) {
            out.push(`${bad.length} ta qatorda mahsulot tanlanmagan`);
        }
        if (!this.orderTotals(order).count) {
            out.push("Miqdor yo'q");
        }
        if (forGive && !this.state.init.settings.allow_negative) {
            const short = new Set(order.lines.filter((l) => this.lineShortHere(order, l)).map((l) => l.product_id));
            if (short.size) {
                out.push(`${short.size} ta mahsulot qoldig'i yetmaydi`);
            }
        }
        if (order.duplicate && !order.force) {
            out.push(`Avval kiritilgan: ${order.duplicate.name}`);
        }
        if (forGive && !(order.truck || "").trim()) {
            out.push("Mashina raqami yozilmagan");
        }
        return out;
    }
    canGive(order) {
        return !this.state.busy && this.orderProblems(order, true).length === 0;
    }
    canSend(order) {
        return !this.state.busy && this.orderProblems(order, false).length === 0;
    }
    shortCount(order) {
        return new Set(order.lines.filter((l) => this.lineShort(order, l)).map((l) => l.product_id)).size;
    }
    get readyOrders() {
        return this.state.orders.filter((o) => this.canSend(o));
    }
    get giveReadyOrders() {
        return this.state.orders.filter((o) => this.canGive(o));
    }

    // ------------------------------------------------------------------ tahrirlash
    onCustomer(order, ev) {
        order.customer = ev.target.value;
        order.partner = false;
        order.partner_is_new = true;
        this.state.partnerDrop = { key: order.key, results: [] };
        this.searchPartners(order);
        this.saveDraft();
    }
    async _searchPartners(order) {
        const q = (order.customer || "").trim();
        if (q.length < 2) {
            if (this.state.partnerDrop && this.state.partnerDrop.key === order.key) {
                this.state.partnerDrop.results = [];
            }
            return;
        }
        const results = await this.orm.call(MODEL, "search_partners", [q]);
        if (this.state.partnerDrop && this.state.partnerDrop.key === order.key) {
            this.state.partnerDrop.results = results;
            const exact = results.find((r) => r.name.toLowerCase() === q.toLowerCase());
            if (exact) {
                order.partner = exact;
                order.partner_is_new = false;
            }
        }
    }
    pickPartner(order, partner) {
        order.partner = partner;
        order.partner_is_new = false;
        if (!(order.customer || "").trim()) {
            order.customer = partner.name;
        }
        this.state.partnerDrop = null;
        this.saveDraft();
    }
    closePartnerDrop() {
        setTimeout(() => {
            this.state.partnerDrop = null;
        }, 200);
    }
    async setLocation(order, locId) {
        order.location_id = locId;
        const ids = [...new Set(order.lines.map((l) => l.product_id).filter(Boolean))];
        const missing = ids.filter((id) => {
            const p = this.product(id);
            return !p || !p.avail || !(locId in p.avail);
        });
        if (missing.length) {
            await this._loadStockInfo(missing, locId);
        }
        this.saveDraft();
    }
    async _loadStockInfo(ids, locId) {
        const res = await this.orm.call(MODEL, "stock_info", [ids, locId]);
        for (const [id, info] of Object.entries(res)) {
            const cur = this.state.products[id];
            if (cur) {
                cur.avail = Object.assign(cur.avail || {}, info.avail || {});
            } else {
                this.state.products[id] = info;
            }
        }
    }
    onDate(order, ev) {
        order.date = (ev.target.value || "").replace("T", " ");
        this.saveDraft();
    }
    onQty(line, field, ev) {
        const v = parseInt(ev.target.value, 10);
        line[field] = Number.isFinite(v) && v > 0 ? v : 0;
        this.saveDraft();
    }
    step(line, field, delta) {
        line[field] = Math.max(0, (Number(line[field]) || 0) + delta);
        this.saveDraft();
    }
    removeLine(order, line) {
        const i = order.lines.indexOf(line);
        if (i >= 0) {
            order.lines.splice(i, 1);
        }
        this.saveDraft();
    }
    addLine(order) {
        const line = {
            uid: `n${Date.now()}`,
            raw: "",
            packs: 1,
            extra: 0,
            product_id: false,
            parsed_product_id: false,
            status: "error",
            msg: "",
            learn_key: "",
            suggestion_ids: [],
            pack_ids: [],
        };
        order.lines.push(line);
        this.openPicker(order, line);
    }
    forceOrder(order) {
        order.force = true;
        this.saveDraft();
    }
    toggleRaw(order) {
        this.state.expanded[order.key] = !this.state.expanded[order.key];
    }

    // ------------------------------------------------------------------ mahsulot tanlash oynasi
    openPicker(order, line) {
        const suggestions = (line.suggestion_ids || []).map((id) => this.product(id)).filter(Boolean);
        this.state.picker = { order, line, query: "", results: [], suggestions, loading: false };
        this._searchProducts();
    }
    closePicker() {
        const picker = this.state.picker;
        if (picker && !picker.line.product_id && !picker.line.raw) {
            this.removeLine(picker.order, picker.line);
        }
        this.state.picker = null;
    }
    onPickerQuery(ev) {
        this.state.picker.query = ev.target.value;
        this.searchProducts();
    }
    async _searchProducts() {
        const picker = this.state.picker;
        if (!picker) {
            return;
        }
        picker.loading = true;
        const results = await this.orm.call(MODEL, "search_products", [picker.query, picker.order.location_id]);
        if (this.state.picker !== picker) {
            return;
        }
        for (const r of results) {
            const cur = this.state.products[r.id] || { ...r, avail: {} };
            cur.avail = Object.assign(cur.avail || {}, { [picker.order.location_id]: r.avail });
            this.state.products[r.id] = cur;
        }
        picker.results = results;
        picker.loading = false;
    }
    async pickProduct(p) {
        const { order, line } = this.state.picker;
        if (!this.state.products[p.id]) {
            this.state.products[p.id] = { ...p, avail: {} };
        }
        line.product_id = p.id;
        line.status = "ok";
        line.msg = line.learn_key && line.parsed_product_id !== p.id ? "Tanlandi — keyingi safar o'zi taniydi" : "";
        this.state.picker = null;
        if (this.avail(order, p.id) === null) {
            await this._loadStockInfo([p.id], order.location_id);
        }
        this.saveDraft();
    }

    // ------------------------------------------------------------------ skaner
    onScanInput(order, ev) {
        order.scan = ev.target.value;
        if (ev.key === "Enter") {
            this.doScan(order);
        }
    }
    async cameraScan(order) {
        try {
            const code = await scanBarcode(this.env);
            if (code) {
                order.scan = code;
                await this.doScan(order);
            }
        } catch (e) {
            this.notification.add(`Kamera: ${this.errorText(e)}`, { type: "warning" });
        }
    }
    async doScan(order) {
        const code = (order.scan || "").trim();
        if (!code) {
            return;
        }
        try {
            const res = await this.orm.call(MODEL, "scan", [code, order.location_id]);
            const pid = res.product.id;
            const cur = this.state.products[pid] || { ...res.product, avail: {} };
            cur.avail = Object.assign(cur.avail || {}, { [order.location_id]: res.product.avail });
            this.state.products[pid] = cur;
            if (res.pack && order.lines.some((l) => (l.pack_ids || []).includes(res.pack.id))) {
                this.notification.add(`${res.pack.name} allaqachon qo'shilgan`, { type: "warning" });
            } else {
                let line = order.lines.find((l) => l.product_id === pid && (l.pack_ids || []).length);
                if (line && res.pack) {
                    line.packs += res.packs;
                    line.extra += res.extra;
                    line.pack_ids.push(res.pack.id);
                    line.raw = `${line.raw}, ${res.pack.name}`;
                } else {
                    line = {
                        uid: `s${Date.now()}`,
                        raw: res.pack ? res.pack.name : code,
                        packs: res.packs,
                        extra: res.extra,
                        product_id: pid,
                        parsed_product_id: pid,
                        status: "ok",
                        msg: res.warn || "",
                        learn_key: "",
                        suggestion_ids: [],
                        pack_ids: res.pack ? [res.pack.id] : [],
                    };
                    order.lines.push(line);
                }
                this.notification.add(`${res.product.name}${res.pack ? " · " + res.pack.name : ""}`, {
                    type: res.warn ? "warning" : "success",
                });
            }
            order.scan = "";
            this.saveDraft();
        } catch (e) {
            this.notification.add(this.errorText(e), { type: "danger" });
        }
    }

    // ------------------------------------------------------------------ Berildi
    payload(order) {
        return {
            key: false,
            customer: order.customer,
            partner_id: order.partner ? order.partner.id : false,
            location_id: order.location_id,
            date: false,
            raw: order.raw,
            note: order.note || "",
            truck: this.normTruck(order.truck),
            force: order.force,
            lines: order.lines
                .filter((l) => this.linePcs(l) > 0 || l.product_id)
                .map((l) => ({
                    product_id: l.product_id,
                    parsed_product_id: l.parsed_product_id,
                    packs: Number(l.packs) || 0,
                    extra: Number(l.extra) || 0,
                    raw: l.raw,
                    learn_key: l.learn_key,
                    pack_ids: l.pack_ids || [],
                })),
        };
    }
    summary(order) {
        const t = this.orderTotals(order);
        const name = order.partner ? order.partner.name : order.customer;
        return `${name} — ${t.count} xil mahsulot, ${fmtNum(t.packs)} pachka` +
            (t.extra ? ` + ${fmtNum(t.extra)} dona` : "") +
            `, ${fmtNum(t.kg)} kg «${this.locLabel(order.location_id)}» dan beriladi.`;
    }
    onNote(order, ev) {
        order.note = ev.target.value;
        this.saveDraft();
    }
    normTruck(value) {
        return (value || "").trim().replace(/\s+/g, " ").toUpperCase();
    }
    onTruck(order, ev) {
        order.truck = this.normTruck(ev.target.value);
        ev.target.value = order.truck;
        this.saveDraft();
    }
    rememberTruck(truck) {
        const list = this.state.init.trucks || [];
        if (truck && !list.includes(truck)) {
            list.unshift(truck);
            this.state.init.trucks = list.slice(0, 40);
        }
    }
    send(order) {
        this._submit([order], "send");
    }
    sendAll() {
        const ready = this.readyOrders;
        if (ready.length) {
            this.dialog.add(ConfirmationDialog, {
                title: `${ready.length} ta buyurtma`,
                body: `${ready.length} ta buyurtma yuklovchiga yuboriladi.`,
                confirmLabel: "Yuborish",
                confirm: () => this._submit(ready, "send"),
                cancel: () => {},
            });
        }
    }
    give(order) {
        this.dialog.add(ConfirmationDialog, {
            title: "O'zim yukladim — Berildi",
            body: this.summary(order),
            confirmLabel: "Berildi",
            confirm: () => this._submit([order], "berildi"),
            cancel: () => {},
        });
    }
    giveAll() {
        const ready = this.giveReadyOrders;
        if (!ready.length) {
            return;
        }
        const t = ready.reduce(
            (acc, o) => {
                const x = this.orderTotals(o);
                acc.packs += x.packs;
                acc.kg += x.kg;
                return acc;
            },
            { packs: 0, kg: 0 }
        );
        this.dialog.add(ConfirmationDialog, {
            title: `${ready.length} ta sotuv`,
            body: `${ready.length} ta sotuv bajariladi: jami ${fmtNum(t.packs)} pachka, ${fmtNum(t.kg)} kg. ` +
                "Xato chiqqanlari ro'yxatda qoladi.",
            confirmLabel: "Hammasini berish",
            confirm: () => this._submit(ready, "berildi"),
            cancel: () => {},
        });
    }
    async _submit(orders, method) {
        this.state.busy = true;
        orders.forEach((o) => this.rememberTruck(this.normTruck(o.truck)));
        try {
            const results = await this.orm.call(MODEL, method, [orders.map((o) => this.payload(o))]);
            let ok = 0;
            results.forEach((res, i) => {
                const order = orders[i];
                if (res.ok) {
                    ok++;
                    this.state.done.unshift(res.order);
                    this.removeOrder(order);
                } else {
                    order.error = res.error;
                }
            });
            const failed = results.length - ok;
            if (ok) {
                this.notification.add(
                    method === "send"
                        ? `${ok} ta buyurtma yuklovchiga yuborildi — mahsulot band qilindi`
                        : `${ok} ta sotuv berildi — qoldiq kamaydi`,
                    { type: "success" }
                );
                this.state.sales = null;
                this.state.stock = null;
                this.state.load.queue = null;
                const q = await this.orm.call(MODEL, "load_queue", []);
                this.state.init.queue_count = q.count;
            }
            if (failed) {
                this.notification.add(`${failed} ta sotuv bajarilmadi — kartochkadagi xabarni o'qing`, {
                    type: "danger",
                });
            }
            this.saveDraft();
        } finally {
            this.state.busy = false;
        }
    }
    openOrder(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    // ------------------------------------------------------------------ Sotuvlar
    async loadSales(day) {
        this.state.sales = await this.orm.call(MODEL, "day_sales", [day || (this.state.sales && this.state.sales.date) || false]);
    }
    onSalesDate(ev) {
        if (ev.target.value) {
            this.loadSales(ev.target.value);
        }
    }
    async giveExisting(card) {
        if (["queue", "loading"].includes(card.load_state)) {
            await this.openLoad(card);
            return;
        }
        try {
            await this.orm.call(MODEL, "berildi_existing", [card.id]);
            this.notification.add(`${card.name} berildi`, { type: "success" });
            this.state.stock = null;
            await this.loadSales();
        } catch (e) {
            this.notification.add(this.errorText(e), { type: "danger" });
        }
    }
    markC1() {
        const s = this.state.sales;
        this.dialog.add(ConfirmationDialog, {
            title: "1C ga kiritildi",
            body: `${s.date_label} kunining ${s.c1_new} ta sotuvi «1C ga kiritildi» deb belgilanadi.`,
            confirmLabel: "Belgilash",
            confirm: async () => {
                const n = await this.orm.call(MODEL, "mark_c1", [s.date]);
                this.notification.add(`${n} ta sotuv belgilandi`, { type: "success" });
                await this.loadSales();
            },
            cancel: () => {},
        });
    }
    toggleCard(id) {
        this.state.expanded[`s${id}`] = !this.state.expanded[`s${id}`];
    }
    setSalesFilter(f) {
        this.state.salesFilter = f;
    }
    get salesOrders() {
        const s = this.state.sales;
        if (!s) {
            return [];
        }
        const f = this.state.salesFilter;
        if (f === "wait") {
            return s.orders.filter((o) => ["queue", "loading"].includes(o.load_state));
        }
        if (f === "done") {
            return s.orders.filter((o) => o.load_state === "done");
        }
        return s.orders;
    }
    statusClass(o) {
        return {
            queue: "cs-st-queue",
            loading: "cs-st-loading",
            done: "cs-st-done",
            cancel: "cs-st-cancel",
            draft: "cs-st-draft",
        }[o.load_state] || "";
    }
    ageText(min) {
        if (min < 1) {
            return "hozir";
        }
        if (min < 60) {
            return `${min} daq`;
        }
        const h = Math.floor(min / 60);
        return h < 24 ? `${h} soat ${min % 60} daq` : `${Math.floor(h / 24)} kun`;
    }

    // ------------------------------------------------------------------ Yuklash (yuklovchi)
    async loadQueue() {
        const q = await this.orm.call(MODEL, "load_queue", []);
        this.state.load.queue = q.orders;
        this.state.init.queue_count = q.count;
    }
    async openLoad(card) {
        // faqat ko'rish — holat «Qabul qilish» bosilganda o'zgaradi
        try {
            const res = await this.orm.call(MODEL, "load_order", [card.id]);
            this.state.load.current = res;
            this.state.load.result = null;
            this.state.load.edit = null;
            this.state.load.finish = false;
            this.state.load.scan = "";
            this.state.tab = "load";
        } catch (e) {
            this.notification.add(this.errorText(e), { type: "danger" });
            await this.loadQueue();
        }
    }
    ldMode(cur) {
        if (cur.load_state === "loading" && cur.is_mine) {
            return "mine";
        }
        if (cur.load_state === "loading" && cur.loader) {
            return "other";
        }
        return "new";
    }
    async acceptLoad(force = false) {
        const cur = this.state.load.current;
        if (!cur || this.state.load.busy) {
            return;
        }
        this.state.load.busy = true;
        try {
            const res = await this.orm.call(MODEL, "load_accept", [cur.id, force]);
            if (res.busy) {
                this.dialog.add(ConfirmationDialog, {
                    title: "Boshqa yuklovchi",
                    body: `${cur.partner} buyurtmasini ${res.busy} yuklamoqda. Uning o'rniga siz davom ettirasizmi?`,
                    confirmLabel: "Men davom ettiraman",
                    confirm: () => this.acceptLoad(true),
                    cancel: () => {},
                });
                return;
            }
            this.state.load.current = res;
            this.notification.add(`${res.name} · ${res.partner}: qabul qilindi — yuklanmoqda`, { type: "success" });
        } catch (e) {
            this.notification.add(this.errorText(e), { type: "danger" });
            await this.reloadCurrent();
        } finally {
            this.state.load.busy = false;
        }
    }
    _needAccept() {
        const cur = this.state.load.current;
        if (cur && this.ldMode(cur) !== "mine") {
            this.notification.add("Avval «Qabul qilish» ni bosing", { type: "warning" });
            return true;
        }
        return false;
    }
    async reloadCurrent() {
        const cur = this.state.load.current;
        if (!cur) {
            return;
        }
        try {
            const wasMine = this.ldMode(cur) === "mine";
            this.state.load.current = await this.orm.call(MODEL, "load_order", [cur.id]);
            const now = this.state.load.current;
            if (wasMine && this.ldMode(now) === "other") {
                this.state.load.edit = null;
                this.notification.add(`${now.name}: endi ${now.loader} yuklamoqda`, { type: "warning" });
            }
            if (!["queue", "loading"].includes(this.state.load.current.load_state)) {
                this.notification.add(`${cur.name}: ${this.state.load.current.load_label}`, { type: "info" });
                this.backToQueue();
            }
        } catch {
            this.backToQueue();
        }
    }
    backToQueue() {
        this.state.load.current = null;
        this.state.load.result = null;
        this.state.load.edit = null;
        this.state.load.finish = false;
        this.loadQueue();
    }
    async releaseCurrent() {
        const cur = this.state.load.current;
        await this.orm.call(MODEL, "load_release", [cur.id]);
        this.backToQueue();
    }
    async _loadCall(method, args) {
        this.state.load.busy = true;
        try {
            const res = await this.orm.call(MODEL, method, args);
            this.state.load.current = res;
            return res;
        } catch (e) {
            this.notification.add(this.errorText(e), { type: "danger" });
            return null;
        } finally {
            this.state.load.busy = false;
        }
    }
    toggleLoad(line) {
        if (this._needAccept()) {
            return;
        }
        this._loadCall("load_toggle", [this.state.load.current.id, line.move_id]);
    }
    async onLoadTruck(ev) {
        const cur = this.state.load.current;
        const truck = this.normTruck(ev.target.value);
        ev.target.value = truck;
        try {
            const res = await this.orm.call(MODEL, "load_truck", [cur.id, truck]);
            cur.truck = res.truck;
            this.rememberTruck(res.truck);
        } catch (e) {
            this.notification.add(this.errorText(e), { type: "danger" });
        }
    }
    editLoad(line) {
        if (this._needAccept()) {
            return;
        }
        const per = line.product.per_pack || 0;
        const anyAlloc = line.stock.some((s) => s.qty);
        const split = (pcs) => ({
            packs: per ? Math.floor(pcs / per) : 0,
            extra: per ? Math.round(pcs - Math.floor(pcs / per) * per) : Math.round(pcs),
        });
        this.state.load.edit = {
            move_id: line.move_id,
            per,
            rows: line.stock.map((s) => ({
                location_id: s.location_id,
                label: s.label,
                onhand_text: s.onhand_text,
                ...split(anyAlloc ? s.qty : s.primary ? line.demand : 0),
            })),
        };
    }
    onEditQty(row, field, ev) {
        const v = parseInt(ev.target.value, 10);
        row[field] = Number.isFinite(v) && v > 0 ? v : 0;
    }
    stepEdit(row, field, delta) {
        row[field] = Math.max(0, (Number(row[field]) || 0) + delta);
    }
    editTotal() {
        const e = this.state.load.edit;
        const pcs = e.rows.reduce((s, r) => s + (Number(r.packs) || 0) * e.per + (Number(r.extra) || 0), 0);
        return { pcs, text: packsText(pcs, e.per) };
    }
    async saveEdit() {
        const e = this.state.load.edit;
        const rows = e.rows.map((r) => ({ location_id: r.location_id, packs: Number(r.packs) || 0, extra: Number(r.extra) || 0 }));
        const res = await this._loadCall("load_set", [this.state.load.current.id, e.move_id, rows]);
        if (res) {
            this.state.load.edit = null;
        }
    }
    cancelEdit() {
        this.state.load.edit = null;
    }
    onLoadScanKey(ev) {
        this.state.load.scan = ev.target.value;
        if (ev.key === "Enter") {
            this.doLoadScan();
        }
    }
    async doLoadScan(code) {
        code = (code || this.state.load.scan || "").trim();
        if (!code) {
            return;
        }
        const res = await this._loadCall("load_scan", [this.state.load.current.id, code]);
        if (res && res.scanned) {
            this.notification.add(`${res.scanned.name}: ${res.scanned.product} +${res.scanned.pcs} dona`, {
                type: "success",
            });
            this.state.load.scan = "";
        }
    }
    async cameraLoadScan() {
        try {
            const code = await scanBarcode(this.env);
            if (code) {
                await this.doLoadScan(code);
            }
        } catch (e) {
            this.notification.add(`Kamera: ${this.errorText(e)}`, { type: "warning" });
        }
    }
    // ---------------------------------------------------------------- mashina rasmi
    tripPhotos(cur) {
        return (cur && cur.photos ? cur.photos : []).filter((p) => p.trip);
    }
    async onPhotoPick(ev) {
        const files = [...(ev.target.files || [])];
        ev.target.value = "";
        if (!files.length || this._needAccept()) {
            return;
        }
        const cur = this.state.load.current;
        this.state.load.photoBusy = true;
        try {
            for (const file of files) {
                const img = await this._shrinkImage(file);
                const res = await this.orm.call(MODEL, "load_photo", [cur.id, img.data, file.name, img.mimetype]);
                if (this.state.load.current && this.state.load.current.id === cur.id) {
                    this.state.load.current = res;
                }
            }
            this.notification.add(files.length > 1 ? `${files.length} ta rasm biriktirildi` : "Rasm biriktirildi", {
                type: "success",
            });
        } catch (e) {
            this.notification.add(this.errorText(e), { type: "danger" });
        } finally {
            this.state.load.photoBusy = false;
        }
    }
    async _shrinkImage(file, max = 1600, quality = 0.8) {
        // telefon rasmi 3–8 MB — yuborishdan oldin kichraytiramiz (~200–400 KB)
        try {
            const bmp = await createImageBitmap(file);
            const k = Math.min(1, max / Math.max(bmp.width, bmp.height));
            const canvas = document.createElement("canvas");
            canvas.width = Math.round(bmp.width * k);
            canvas.height = Math.round(bmp.height * k);
            canvas.getContext("2d").drawImage(bmp, 0, 0, canvas.width, canvas.height);
            if (bmp.close) {
                bmp.close();
            }
            const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
            if (blob) {
                return { data: await this._blobB64(blob), mimetype: "image/jpeg" };
            }
        } catch {
            // eski brauzer — asl fayl yuboriladi
        }
        return { data: await this._blobB64(file), mimetype: file.type || "image/jpeg" };
    }
    _blobB64(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(blob);
        });
    }
    removePhoto(photo) {
        this.dialog.add(ConfirmationDialog, {
            title: "Rasmni o'chirish",
            body: "Bu rasm o'chirilsinmi?",
            confirmLabel: "O'chirish",
            confirm: () => this._loadCall("load_photo_remove", [this.state.load.current.id, photo.id]),
            cancel: () => {},
        });
    }
    viewPhoto(photo) {
        this.state.photoView = photo.url;
    }
    closePhoto() {
        this.state.photoView = null;
    }
    loadStats(cur) {
        const lines = cur.lines_open || [];
        const done = lines.filter((l) => l.picked && l.loaded > 0);
        const full = lines.filter((l) => l.picked && l.loaded >= l.demand - 1e-6);
        let loadedKg = 0;
        let totalKg = 0;
        for (const l of lines) {
            totalKg += l.demand * (l.product.kg_pc || 0);
            loadedKg += (l.picked ? l.loaded : 0) * (l.product.kg_pc || 0);
        }
        return {
            total: lines.length,
            done: done.length,
            full: full.length,
            complete: lines.length > 0 && full.length === lines.length,
            pct: lines.length ? Math.round((done.length / lines.length) * 100) : 0,
            loadedKg,
            totalKg,
        };
    }
    loadPlaces(cur) {
        const names = [];
        for (const l of cur.lines_open || []) {
            for (const s of l.stock || []) {
                if (s.qty && !names.includes(s.label)) {
                    names.push(s.label);
                }
            }
        }
        return names.length ? names.map((n) => `«${n}»`).join(", ") : `«${cur.location}»`;
    }
    lineState(line) {
        if (!line.picked || !line.loaded) {
            return "todo";
        }
        if (line.loaded < line.demand - 1e-6) {
            return "less";
        }
        if (line.loaded > line.demand + 1e-6) {
            return "more";
        }
        return "ok";
    }
    finishLoad() {
        if (this._needAccept()) {
            return;
        }
        const cur = this.state.load.current;
        const st = this.loadStats(cur);
        if (!this.tripPhotos(cur).length) {
            this.notification.add("Avval yuklangan mashinani rasmga oling", { type: "warning" });
            return;
        }
        if (!st.done) {
            this.notification.add("Avval yuklangan qatorlarni belgilang", { type: "warning" });
            return;
        }
        if (st.complete) {
            this.dialog.add(ConfirmationDialog, {
                title: "Berildi",
                body: `${cur.partner}: ${st.total} qator to'liq yuklandi (${fmtNum(st.loadedKg)} kg). ` +
                    `Mashina ${cur.truck} (rasm: ${this.tripPhotos(cur).length}). Mahsulot ${this.loadPlaces(cur)} dan chiqariladi.`,
                confirmLabel: "Berildi",
                confirm: () => this._finish("backorder"),
                cancel: () => {},
            });
        } else {
            this.state.load.finish = true;
        }
    }
    closeFinish() {
        this.state.load.finish = false;
    }
    async _finish(rest) {
        const cur = this.state.load.current;
        this.state.load.finish = false;
        this.state.load.busy = true;
        try {
            const res = await this.orm.call(MODEL, "load_done", [cur.id, rest]);
            this.state.load.result = res;
            this.state.load.current = null;
            this.state.sales = null;
            this.state.stock = null;
            const q = await this.orm.call(MODEL, "load_queue", []);
            this.state.load.queue = q.orders;
            this.state.init.queue_count = q.count;
        } catch (e) {
            this.notification.add(this.errorText(e), { type: "danger" });
        } finally {
            this.state.load.busy = false;
        }
    }
    closeResult() {
        this.state.load.result = null;
    }

    // ------------------------------------------------------------------ Qoldiq
    async loadStock() {
        this.state.stock = await this.orm.call(MODEL, "stock_list", [
            this.state.stockLoc,
            this.state.stockQuery,
            this.state.stockAll,
        ]);
    }
    setStockLoc(id) {
        this.state.stockLoc = id;
        this.loadStock();
    }
    onStockQuery(ev) {
        this.state.stockQuery = ev.target.value;
        this.searchStock();
    }
    toggleStockAll() {
        this.state.stockAll = !this.state.stockAll;
        this.loadStock();
    }
    openProduct(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    // ------------------------------------------------------------------ sozlamalar
    toggleSettings() {
        this.state.settings = !this.state.settings;
    }
    async saveSetting(key, value) {
        try {
            this.state.init = await this.orm.call(MODEL, "save_settings", [{ [key]: value }]);
            this.notification.add("Saqlandi", { type: "success" });
        } catch (e) {
            this.notification.add(this.errorText(e), { type: "danger" });
        }
    }
    onDefaultLoc(ev) {
        this.saveSetting("location_id", parseInt(ev.target.value, 10));
    }
    openAction(xmlid) {
        this.state.settings = false;
        this.action.doAction(xmlid);
    }
}

registry.category("actions").add("craf_sotuv", CrafSotuv);
