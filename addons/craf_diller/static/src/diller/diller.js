/** Diller portali: bitta sahifa, telefon birinchi. Server bilan faqat /diller/api/<usul> orqali. */
import { Component, mount, onMounted, onWillStart, reactive, useState, xml } from "@odoo/owl";

async function api(method, params = {}) {
    const res = await fetch("/diller/api/" + method, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", method: "call", id: Date.now(), params }),
    });
    const data = await res.json();
    if (data.error) {
        if (data.error.code === 100) {
            location.href = "/diller/login";
        }
        throw new Error(data.error.data?.message || data.error.message || "Xato");
    }
    return data.result;
}

const fmt = (v) => Math.round(v || 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, " ");
const store = {
    get(key, def) {
        try {
            return JSON.parse(localStorage.getItem(key)) ?? def;
        } catch {
            return def;
        }
    },
    set(key, value) {
        try {
            localStorage.setItem(key, JSON.stringify(value));
        } catch {
            // xususiy oyna: savat faqat shu sessiyada qoladi
        }
    },
};
const uid4 = () => Math.random().toString(36).slice(2) + Date.now().toString(36);

/** Umumiy holat: katalog, savat, ochiq sahifa. */
const S = reactive({
    me: null, rows: [], byId: {}, cart: [], tab: "katalog", page: null, toast: null, unread: 0,
    form: { need_date: "", truck: "", note: "" }, editId: null,
});

function toast(text, bad = false) {
    S.toast = { text, bad };
    setTimeout(() => (S.toast = null), bad ? 6000 : 3000);
}
async function guard(fn) {
    try {
        return await fn();
    } catch (err) {
        toast(err.message, true);
    }
}
function saveCart() {
    store.set("craf_cart_" + S.me.uid, S.cart);
}
function cartItem(id) {
    return S.cart.find((c) => c.id === id);
}
function setQty(id, packs, extra) {
    packs = Math.max(0, parseInt(packs) || 0);
    extra = Math.max(0, parseInt(extra) || 0);
    const item = cartItem(id);
    if (!packs && !extra) {
        S.cart = S.cart.filter((c) => c.id !== id);
    } else if (item) {
        item.packs = packs;
        item.extra = extra;
    } else {
        S.cart.push({ id, packs, extra });
    }
    saveCart();
}
function totals() {
    let pcs = 0, kg = 0, sum = 0, unpriced = 0;
    for (const c of S.cart) {
        const p = S.byId[c.id];
        if (!p) {
            continue;
        }
        const n = c.packs * (p.per_pack || 0) + c.extra;
        pcs += n;
        kg += n * p.kg_pc;
        sum += n * p.price;
        if (!p.price) {
            unpriced++;
        }
    }
    return { pcs, kg, sum, unpriced };
}
const LEVELS = { "ko'p": "Ko'p bor", kam: "Kam", "yo'q": "Buyurtma asosida" };

class Qty extends Component {
    static props = ["product"];
    static template = xml`
        <div class="d-qty-wrap">
            <div t-if="props.product.per_pack">
                <small>Pachka (<t t-esc="props.product.per_pack"/> dona)</small>
                <div class="d-qty">
                    <button aria-label="Kamaytirish" t-on-click="() => this.set(item.packs - 1, item.extra)">−</button>
                    <input type="number" min="0" inputmode="numeric" aria-label="Pachka" t-att-value="item.packs"
                           t-on-change="(ev) => this.set(ev.target.value, item.extra)"/>
                    <button aria-label="Ko'paytirish" t-on-click="() => this.set(item.packs + 1, item.extra)">+</button>
                </div>
            </div>
            <div>
                <small>Dona</small>
                <div class="d-qty">
                    <button aria-label="Kamaytirish" t-on-click="() => this.set(item.packs, item.extra - 1)">−</button>
                    <input type="number" min="0" inputmode="numeric" aria-label="Dona" t-att-value="item.extra"
                           t-on-change="(ev) => this.set(item.packs, ev.target.value)"/>
                    <button aria-label="Ko'paytirish" t-on-click="() => this.set(item.packs, item.extra + 1)">+</button>
                </div>
            </div>
        </div>`;
    setup() {
        this.s = useState(S);
    }
    get item() {
        return this.s.cart.find((c) => c.id === this.props.product.id) || { packs: 0, extra: 0 };
    }
    set(packs, extra) {
        setQty(this.props.product.id, packs, extra);
    }
}

class ProductCard extends Component {
    static components = { Qty };
    static props = ["product"];
    static template = xml`
        <div class="d-card">
            <div class="d-prod">
                <img t-if="p.image" class="d-thumb" loading="lazy" t-att-src="'/diller/rasm/' + p.id" t-att-alt="p.name"/>
                <div t-else="" class="d-thumb" t-esc="p.type.slice(0, 3)"/>
                <div class="d-grow">
                    <div class="d-row d-between">
                        <div class="d-prod-name d-grow" t-esc="p.name"/>
                        <button class="d-star" t-att-class="{on: p.favorite}" aria-label="Sevimli"
                                t-on-click="toggle">★</button>
                    </div>
                    <div class="d-muted"><t t-esc="p.code"/><t t-if="p.length"> · <t t-esc="p.length"/> m</t><t t-if="p.kg_pc"> · <t t-esc="p.kg_pc.toFixed(3)"/> kg/dona</t></div>
                    <div class="d-row d-between d-wrap">
                        <span class="d-price"><t t-if="p.price"><t t-esc="money(p.price)"/> / dona</t><t t-else="">Narx kelishiladi</t></span>
                        <span class="d-level" t-attf-class="d-lv-#{p.level}" t-esc="levels[p.level]"/>
                    </div>
                </div>
            </div>
            <Qty product="p"/>
        </div>`;
    setup() {
        this.levels = LEVELS;
    }
    get p() {
        return this.props.product;
    }
    money(v) {
        return fmt(v) + " " + S.me.currency;
    }
    toggle() {
        const on = !this.p.favorite;
        S.byId[this.p.id].favorite = on;
        guard(() => api("favorite", { product_id: this.p.id, on }));
    }
}

class Catalog extends Component {
    static components = { ProductCard };
    static props = [];
    static template = xml`
        <div>
            <input type="search" placeholder="Qidirish: TB oq, L antrasid…" aria-label="Qidirish"
                   t-att-value="st.query" t-on-input="onSearch"/>
            <div class="d-chips" style="margin-top:8px">
                <button class="d-chip" t-att-class="{on: st.mode == 'all'}" t-on-click="() => this.st.mode = 'all'">Hammasi</button>
                <button class="d-chip" t-att-class="{on: st.mode == 'top'}" t-on-click="() => this.st.mode = 'top'">Ko'p oladiganlarim</button>
                <button class="d-chip" t-att-class="{on: st.mode == 'fav'}" t-on-click="() => this.st.mode = 'fav'">★ Sevimlilar</button>
            </div>
            <div class="d-chips">
                <button t-foreach="types" t-as="t" t-key="t" class="d-chip" t-att-class="{on: st.type == t}"
                        t-on-click="() => this.pick('type', t)" t-esc="t"/>
            </div>
            <div class="d-filters">
                <select aria-label="Seriya" t-on-change="(ev) => this.st.series = ev.target.value">
                    <option value="">Seriya</option>
                    <option t-foreach="facet('series')" t-as="v" t-key="v" t-att-value="v" t-esc="v" t-att-selected="v == st.series"/>
                </select>
                <select aria-label="Rang" t-on-change="(ev) => this.st.color = ev.target.value">
                    <option value="">Rang</option>
                    <option t-foreach="facet('color')" t-as="v" t-key="v" t-att-value="v" t-esc="v" t-att-selected="v == st.color"/>
                </select>
                <select aria-label="Uzunlik" t-on-change="(ev) => this.st.length = ev.target.value">
                    <option value="">Uzunlik</option>
                    <option t-foreach="facet('length')" t-as="v" t-key="v" t-att-value="v" t-att-selected="v == st.length"><t t-esc="v"/> m</option>
                </select>
            </div>
            <p t-if="!list.length" class="d-muted">Mos mahsulot topilmadi.</p>
            <ProductCard t-foreach="list.slice(0, st.show)" t-as="p" t-key="p.id" product="p"/>
            <button t-if="list.length > st.show" class="d-btn d-block" t-on-click="() => this.st.show += 30">Yana ko'rsatish</button>
            <div t-if="s.cart.length" class="d-sum" t-on-click="() => this.s.tab = 'savat'">
                <span><t t-esc="s.cart.length"/> xil · <t t-esc="money(sum.sum)"/></span><b>Savat →</b>
            </div>
        </div>`;
    setup() {
        this.s = useState(S);
        this.st = useState({ query: "", found: null, mode: "all", type: "", series: "", color: "", length: "", show: 30 });
    }
    get sum() {
        return totals();
    }
    money(v) {
        return fmt(v) + " " + S.me.currency;
    }
    get base() {
        const { found, mode } = this.st;
        let rows = this.s.rows;
        if (found) {
            const ids = new Set(found);
            rows = rows.filter((r) => ids.has(r.id));
        }
        if (mode === "fav") {
            rows = rows.filter((r) => this.s.byId[r.id].favorite);
        } else if (mode === "top") {
            rows = rows.filter((r) => r.top);
        }
        return rows;
    }
    get types() {
        return [...new Set(this.base.map((r) => r.type))].sort();
    }
    facet(field) {
        const rows = this.base.filter((r) => !this.st.type || r.type === this.st.type);
        return [...new Set(rows.map((r) => r[field]).filter(Boolean))].sort();
    }
    get list() {
        const { type, series, color, length } = this.st;
        return this.base.filter((r) => (!type || r.type === type) && (!series || r.series === series)
            && (!color || r.color === color) && (!length || String(r.length) === length));
    }
    pick(field, value) {
        this.st[field] = this.st[field] === value ? "" : value;
        this.st.series = "";
        this.st.color = "";
        this.st.length = "";
    }
    onSearch(ev) {
        const query = ev.target.value;
        this.st.query = query;
        clearTimeout(this.timer);
        this.timer = setTimeout(() => guard(async () => {
            const found = query.trim() ? await api("search", { query }) : null;
            if (this.st.query === query) {
                this.st.found = found;
            }
        }), 250);
    }
}

class Cart extends Component {
    static components = { Qty };
    static props = [];
    static template = xml`
        <div>
            <div t-if="s.editId" class="d-warnbox">Buyurtmani o'zgartiryapsiz.
                <button class="d-btn d-small" t-on-click="stopEdit">Bekor</button></div>
            <p t-if="!s.cart.length" class="d-muted">Savat bo'sh. Katalogdan mahsulot tanlang.</p>
            <div t-foreach="items" t-as="c" t-key="c.product.id" class="d-card">
                <div class="d-prod-name" t-esc="c.product.name"/>
                <div class="d-muted"><t t-esc="c.pcs"/> dona · <t t-esc="c.kg.toFixed(1)"/> kg<t t-if="c.product.price"> · <t t-esc="money(c.sum)"/></t></div>
                <Qty product="c.product"/>
            </div>
            <div t-if="s.cart.length" class="d-card">
                <label for="d-date" style="margin-top:0">Kerakli sana</label>
                <input id="d-date" type="date" t-att-min="s.me.today" t-model="s.form.need_date"/>
                <label for="d-truck">Mashina raqami (keyin ham yozsa bo'ladi)</label>
                <input id="d-truck" placeholder="01 A 777 AA" t-model="s.form.truck"/>
                <label for="d-note">Izoh</label>
                <input id="d-note" t-model="s.form.note"/>
                <div class="d-tr" style="margin-top:10px"><span>Jami</span>
                    <b class="d-end"><t t-esc="fmtn(sum.pcs)"/> dona · <t t-esc="fmtn(sum.kg)"/> kg</b></div>
                <div class="d-tr"><span>Summa (taxminiy)</span><b class="d-end" t-esc="money(sum.sum)"/></div>
                <p t-if="sum.unpriced" class="d-muted"><t t-esc="sum.unpriced"/> ta mahsulot narxini zavod belgilaydi.</p>
                <button class="d-btn d-primary d-block" t-att-disabled="st.busy" t-on-click="send">
                    <t t-if="s.editId">O'zgarishni saqlash</t><t t-else="">Buyurtma berish</t></button>
            </div>
        </div>`;
    setup() {
        this.s = useState(S);
        this.st = useState({ busy: false });
    }
    get sum() {
        return totals();
    }
    fmtn(v) {
        return fmt(v);
    }
    money(v) {
        return fmt(v) + " " + S.me.currency;
    }
    get items() {
        return this.s.cart.filter((c) => this.s.byId[c.id]).map((c) => {
            const product = this.s.byId[c.id];
            const pcs = c.packs * (product.per_pack || 0) + c.extra;
            return { product, pcs, kg: pcs * product.kg_pc, sum: pcs * product.price };
        });
    }
    stopEdit() {
        S.editId = null;
        S.cart = store.get("craf_cart_" + S.me.uid + "_saved", []);
        saveCart();
    }
    async send() {
        this.st.busy = true;
        const data = { ...S.form, lines: S.cart, key: S.cartKey };
        await guard(async () => {
            const editing = S.editId;
            const row = editing ? await api("update", { order_id: editing, data }) : await api("submit", { data });
            S.cart = editing ? store.get("craf_cart_" + S.me.uid + "_saved", []) : [];
            S.editId = null;
            S.cartKey = uid4();
            saveCart();
            S.form = { need_date: "", truck: "", note: "" };
            toast(row.name + ": " + row.status_label);
            S.tab = "buyurtmalar";
            S.page = { kind: "order", id: row.id };
        });
        this.st.busy = false;
    }
}

const FILTERS = [["", "Hammasi"], ["submitted", "Yuborildi"], ["credit", "Qarz tasdig'i"], ["queue", "Navbatda"],
    ["loading", "Yuklanmoqda"], ["partial", "Qisman"], ["done", "Berildi"], ["cancel", "Bekor"]];

class Orders extends Component {
    static props = [];
    static template = xml`
        <div>
            <div class="d-chips">
                <button t-foreach="filters" t-as="f" t-key="f[0]" class="d-chip" t-att-class="{on: st.status == f[0]}"
                        t-on-click="() => this.setStatus(f[0])" t-esc="f[1]"/>
            </div>
            <div class="d-filters">
                <input type="date" aria-label="Sanadan" t-model="st.date_from" t-on-change="load"/>
                <input type="date" aria-label="Sanagacha" t-model="st.date_to" t-on-change="load"/>
                <input placeholder="Mahsulot" aria-label="Mahsulot" t-model="st.product" t-on-change="load"/>
            </div>
            <p t-if="!st.rows.length" class="d-muted">Buyurtma topilmadi.</p>
            <div t-foreach="st.rows" t-as="o" t-key="o.id" class="d-card d-click" t-on-click="() => this.open(o.id)">
                <div class="d-row d-between"><b t-esc="o.name"/><span class="d-st" t-attf-class="d-st-#{o.status}" t-esc="o.status_label"/></div>
                <div class="d-muted" t-esc="o.date"/>
                <div><t t-esc="o.packs"/> pachka · <t t-esc="fmtn(o.kg)"/> kg · <t t-if="o.unpriced">narx aniqlanadi</t><t t-else=""><t t-esc="fmtn(o.amount)"/> <t t-esc="cur"/></t></div>
            </div>
        </div>`;
    setup() {
        this.filters = FILTERS;
        this.cur = S.me.currency;
        this.st = useState({ status: "", date_from: "", date_to: "", product: "", rows: [] });
        this.load = this.load.bind(this);
        onWillStart(this.load);
    }
    fmtn(v) {
        return fmt(v);
    }
    setStatus(status) {
        this.st.status = status;
        this.load();
    }
    async load() {
        const { status, date_from, date_to, product } = this.st;
        await guard(async () => {
            this.st.rows = await api("orders", { status, date_from, date_to, product });
        });
    }
    open(id) {
        S.page = { kind: "order", id };
    }
}

class OrderPage extends Component {
    static props = ["id"];
    static template = xml`
        <div t-if="o">
            <div class="d-row d-between"><h2 t-esc="o.name"/><span class="d-st" t-attf-class="d-st-#{o.status}" t-esc="o.status_label"/></div>
            <p class="d-muted"><t t-esc="o.date"/><t t-if="o.by"> · <t t-esc="o.by"/></t></p>
            <div t-if="o.credit_note" class="d-warnbox" t-esc="o.credit_note"/>
            <div t-if="o.reject_note" class="d-error" t-esc="o.reject_note"/>
            <div class="d-card" t-if="o.status != 'cancel' and o.status != 'rejected'">
                <ul class="d-steps"><li t-foreach="o.steps" t-as="x" t-key="x.label" t-att-class="{on: x.done}">
                    <t t-esc="x.label"/> <span t-if="x.done" class="d-muted" t-esc="x.time"/></li></ul>
            </div>
            <div class="d-card">
                <div t-foreach="o.lines" t-as="l" t-key="l.id" class="d-tr">
                    <div class="d-grow"><div t-esc="l.product"/>
                        <div class="d-muted"><t t-esc="l.text"/> · <t t-esc="l.kg"/> kg</div>
                        <div t-if="l.changed" class="d-muted" style="color:var(--d-warn)">Siz so'ragan: <t t-esc="l.changed"/>, zavod o'zgartirdi</div>
                        <div t-if="l.delivered" class="d-muted">Berildi: <t t-esc="l.delivered"/></div>
                        <div t-if="l.rest" class="d-muted" style="color:var(--d-warn)">Kutilmoqda: <t t-esc="l.rest"/></div>
                    </div>
                    <div class="d-end"><t t-if="l.price" t-esc="fmtn(l.total)"/><t t-else="">—</t></div>
                </div>
                <div class="d-tr"><b>Jami</b><b class="d-end"><t t-esc="fmtn(o.amount)"/> <t t-esc="cur"/></b></div>
                <p t-if="o.unpriced" class="d-muted"><t t-esc="o.unpriced"/> ta mahsulot narxini zavod belgilaydi.</p>
            </div>
            <div class="d-card" t-if="o.note or o.need_date or o.request">
                <div t-if="o.need_date">Kerakli sana: <t t-esc="o.need_date"/></div>
                <div t-if="o.note">Izoh: <t t-esc="o.note"/></div>
                <div t-if="o.request">So'rovingiz: <t t-esc="o.request"/></div>
            </div>
            <div class="d-card" t-if="o.can_truck">
                <label for="d-tr" style="margin-top:0">Mashina raqami</label>
                <div class="d-row"><input id="d-tr" t-model="st.truck" placeholder="01 A 777 AA"/>
                    <button class="d-btn" t-on-click="saveTruck">Saqlash</button></div>
            </div>
            <div class="d-card" t-if="o.truck and !o.can_truck">Mashina: <b t-esc="o.truck"/></div>
            <div class="d-card" t-if="o.photos.length"><b>Mashina rasmi</b>
                <div class="d-photos"><a t-foreach="o.photos" t-as="ph" t-key="ph.id" t-att-href="'/diller/foto/' + ph.id" target="_blank">
                    <img loading="lazy" t-att-src="'/diller/foto/' + ph.id + '?size=256'" alt="Mashina"/></a></div>
            </div>
            <div class="d-card" t-if="o.invoices.length"><b>Hisob-faktura</b>
                <div t-foreach="o.invoices" t-as="m" t-key="m.id" class="d-tr">
                    <a t-att-href="'/diller/faktura/' + m.id" target="_blank"><t t-esc="m.name"/> (PDF)</a>
                    <span class="d-end"><t t-esc="fmtn(m.amount)"/></span></div>
            </div>
            <div class="d-card" t-if="o.returns.length"><b>Qaytarish</b>
                <div t-foreach="o.returns" t-as="r" t-key="r.id" class="d-tr"><span t-esc="r.name"/><span class="d-end" t-esc="r.state_label"/></div>
            </div>
            <div class="d-row d-wrap">
                <button t-if="o.can_edit" class="d-btn" t-on-click="edit">O'zgartirish</button>
                <button t-if="o.can_edit" class="d-btn d-danger" t-on-click="cancel">Bekor qilish</button>
                <button class="d-btn" t-on-click="repeat">Takrorlash</button>
                <button t-if="o.can_return" class="d-btn" t-on-click="() => this.s.page = {kind: 'return', id: o.id}">Qaytarish</button>
            </div>
            <div class="d-card" t-if="o.can_request" style="margin-top:10px">
                <label for="d-rq" style="margin-top:0">Zavodga o'zgartirish so'rovi</label>
                <div class="d-row"><input id="d-rq" t-model="st.request"/><button class="d-btn" t-on-click="sendRequest">Yuborish</button></div>
            </div>
        </div>`;
    setup() {
        this.s = useState(S);
        this.cur = S.me.currency;
        this.st = useState({ order: null, truck: "", request: "" });
        onWillStart(() => this.load());
    }
    get o() {
        return this.st.order;
    }
    fmtn(v) {
        return fmt(v);
    }
    async load() {
        await guard(async () => {
            this.st.order = await api("order", { order_id: this.props.id });
            this.st.truck = this.st.order.truck;
        });
    }
    saveTruck() {
        guard(async () => {
            await api("truck", { order_id: this.props.id, truck: this.st.truck });
            toast("Saqlandi");
            await this.load();
        });
    }
    sendRequest() {
        guard(async () => {
            await api("request", { order_id: this.props.id, text: this.st.request });
            this.st.request = "";
            toast("So'rov yuborildi");
            await this.load();
        });
    }
    cancel() {
        if (confirm(this.o.name + " bekor qilinsinmi?")) {
            guard(async () => {
                await api("cancel", { order_id: this.props.id });
                await this.load();
            });
        }
    }
    edit() {
        store.set("craf_cart_" + S.me.uid + "_saved", S.cart);
        const o = this.o;
        S.cart = o.lines.map((l) => ({ id: l.product_id, packs: l.packs, extra: l.extra }));
        S.form = { need_date: o.need_date, truck: o.truck, note: o.note };
        S.editId = o.id;
        saveCart();
        S.page = null;
        S.tab = "savat";
    }
    repeat() {
        guard(async () => {
            const res = await api("repeat", { order_id: this.props.id });
            for (const l of res.lines) {
                setQty(l.id, l.packs, l.extra);
            }
            toast(res.missing.length ? "Katalogda yo'q: " + res.missing.join(", ") : "Savatga qo'shildi");
            S.page = null;
            S.tab = "savat";
        });
    }
}

class ReturnPage extends Component {
    static props = ["id"];
    static template = xml`
        <div t-if="st.info">
            <h2>Qaytarish: <t t-esc="st.info.name"/></h2>
            <p t-if="!st.info.lines.length" class="d-muted">Qaytarsa bo'ladigan mahsulot qolmagan.</p>
            <div t-foreach="st.info.lines" t-as="l" t-key="l.id" class="d-card">
                <div class="d-prod-name" t-esc="l.product"/>
                <div class="d-muted">Ko'pi bilan: <t t-esc="l.max_text"/></div>
                <div class="d-row" style="margin-top:6px">
                    <div t-if="l.per_pack" class="d-grow"><label style="margin:0">Pachka</label>
                        <input type="number" min="0" inputmode="numeric" t-model.number="st.qty[l.id].packs"/></div>
                    <div class="d-grow"><label style="margin:0">Dona</label>
                        <input type="number" min="0" inputmode="numeric" t-model.number="st.qty[l.id].extra"/></div>
                </div>
            </div>
            <div class="d-card" t-if="st.info.lines.length">
                <label for="d-rs" style="margin-top:0">Sabab</label>
                <select id="d-rs" t-model="st.reason">
                    <option value="">Tanlang</option>
                    <option t-foreach="me.reasons" t-as="r" t-key="r.id" t-att-value="r.id" t-esc="r.label"/>
                </select>
                <label for="d-rn">Izoh</label>
                <input id="d-rn" t-model="st.note"/>
                <label for="d-rp">Rasm</label>
                <input id="d-rp" type="file" accept="image/*" capture="environment" multiple="multiple" t-on-change="pick"/>
                <p t-if="st.photos.length" class="d-muted"><t t-esc="st.photos.length"/> ta rasm tanlandi</p>
                <button class="d-btn d-primary d-block" style="margin-top:10px" t-att-disabled="st.busy" t-on-click="save">So'rov yuborish</button>
            </div>
        </div>`;
    setup() {
        this.me = S.me;
        this.st = useState({ info: null, qty: {}, reason: "", note: "", photos: [], busy: false });
        onWillStart(() => guard(async () => {
            const info = await api("return_info", { order_id: this.props.id });
            for (const l of info.lines) {
                this.st.qty[l.id] = { packs: 0, extra: 0 };
            }
            this.st.info = info;
        }));
    }
    async pick(ev) {
        const read = (f) => new Promise((ok, no) => {
            const r = new FileReader();
            r.onload = () => ok(r.result);
            r.onerror = no;
            r.readAsDataURL(f);
        });
        this.st.photos = await Promise.all([...ev.target.files].slice(0, 5).map(read));
    }
    async save() {
        this.st.busy = true;
        const { reason, note, photos, qty } = this.st;
        const lines = Object.entries(qty).map(([id, q]) => ({ id: +id, packs: q.packs || 0, extra: q.extra || 0 }));
        await guard(async () => {
            const row = await api("return_save", { order_id: this.props.id, data: { reason, note, photos, lines } });
            toast(row.name + " yuborildi");
            S.page = { kind: "order", id: this.props.id };
        });
        this.st.busy = false;
    }
}

class Finance extends Component {
    static props = [];
    static template = xml`
        <div t-if="d">
            <div class="d-kpi">
                <div><span class="d-muted">Joriy qarz</span><b><t t-esc="fmtn(d.debt)"/></b></div>
                <div><span class="d-muted">Chegara</span><b><t t-if="d.limit" t-esc="fmtn(d.limit)"/><t t-else="">Yo'q</t></b></div>
                <div><span class="d-muted">Ochiq buyurtmalar bilan</span><b t-esc="fmtn(d.exposure)"/></div>
                <div t-if="d.limit"><span class="d-muted">Bo'sh limit</span><b t-esc="fmtn(d.free)"/></div>
            </div>
            <div class="d-card" t-if="d.payments.length"><b>Oxirgi to'lovlar</b>
                <div t-foreach="d.payments" t-as="p" t-key="p.name" class="d-tr">
                    <div class="d-grow"><t t-esc="p.date"/><div class="d-muted" t-esc="p.label"/></div>
                    <b class="d-end" t-esc="fmtn(-p.amount)"/></div>
            </div>
            <div class="d-card"><b>Akt sverka</b>
                <div class="d-row" style="margin-top:6px">
                    <input type="date" aria-label="Sanadan" t-model="st.from"/><input type="date" aria-label="Sanagacha" t-model="st.to"/>
                    <button class="d-btn" t-on-click="load">Ko'rish</button>
                </div>
                <div class="d-row" style="margin:8px 0">
                    <a class="d-btn d-small" target="_blank" t-att-href="'/diller/akt.pdf?' + query">PDF</a>
                    <a class="d-btn d-small" t-att-href="'/diller/akt.xlsx?' + query">Excel</a>
                </div>
                <div class="d-tr"><span>Boshlang'ich qoldiq</span><b class="d-end" t-esc="fmtn(d.opening)"/></div>
                <div t-foreach="d.rows" t-as="r" t-key="r_index" class="d-tr">
                    <div class="d-grow"><t t-esc="r.date"/><div class="d-muted" t-esc="r.label"/></div>
                    <div class="d-end"><t t-esc="fmtn(r.amount)"/><div class="d-muted" t-esc="fmtn(r.balance)"/></div></div>
                <div class="d-tr"><b>Oxirgi qoldiq</b><b class="d-end" t-esc="fmtn(d.closing)"/></div>
            </div>
            <p class="d-muted">To'lov zavod kassasida kiritiladi, shu yerda ko'rinadi.</p>
        </div>`;
    setup() {
        this.st = useState({ data: null, from: "", to: "" });
        this.load = this.load.bind(this);
        onWillStart(this.load);
    }
    get d() {
        return this.st.data;
    }
    get query() {
        return new URLSearchParams({ date_from: this.d.date_from, date_to: this.d.date_to }).toString();
    }
    fmtn(v) {
        return fmt(v).replace("-", "−");
    }
    async load() {
        await guard(async () => {
            const data = await api("finance", { date_from: this.st.from, date_to: this.st.to });
            this.st.data = data;
            this.st.from = data.date_from;
            this.st.to = data.date_to;
        });
    }
}

class More extends Component {
    static props = [];
    static template = xml`
        <div>
            <div class="d-card">
                <b t-esc="me.user"/><div class="d-muted"><t t-esc="me.dealer"/></div>
            </div>
            <div class="d-card" t-if="st.stats"><b>Statistika (12 oy)</b>
                <p t-if="!st.stats.months.length" class="d-muted">Hali berilgan mahsulot yo'q.</p>
                <div t-foreach="st.stats.months" t-as="m" t-key="m.month" class="d-tr">
                    <div class="d-grow"><t t-esc="m.month"/><div class="d-bar" t-attf-style="width:#{pct(m)}%"/></div>
                    <div class="d-end"><t t-esc="fmtn(m.kg)"/> kg<div class="d-muted"><t t-esc="fmtn(m.amount)"/> <t t-esc="me.currency"/></div></div>
                </div>
                <div t-if="st.stats.top.length" style="margin-top:10px"><b>Eng ko'p olinganlar</b>
                    <div t-foreach="st.stats.top" t-as="t" t-key="t.name" class="d-tr"><span t-esc="t.name"/><span class="d-end"><t t-esc="fmtn(t.pcs)"/> dona</span></div>
                </div>
            </div>
            <div class="d-card" t-if="st.returns.length"><b>Qaytarish so'rovlari</b>
                <div t-foreach="st.returns" t-as="r" t-key="r.id" class="d-tr d-click" t-on-click="() => this.open(r.order_id)">
                    <div class="d-grow"><t t-esc="r.name"/><div class="d-muted"><t t-esc="r.order"/> · <t t-esc="r.reason"/></div></div>
                    <span class="d-end" t-esc="r.state_label"/></div>
            </div>
            <button t-if="!me.telegram" class="d-btn d-block" t-on-click="telegram">Telegram ulash</button>
            <a class="d-btn d-block" style="margin-top:8px" href="/web/session/logout?redirect=/diller/login">Chiqish</a>
        </div>`;
    setup() {
        this.me = S.me;
        this.st = useState({ stats: null, returns: [] });
        onWillStart(() => guard(async () => {
            this.st.stats = await api("stats");
            this.st.returns = await api("returns");
        }));
    }
    fmtn(v) {
        return fmt(v);
    }
    pct(m) {
        const max = Math.max(...this.st.stats.months.map((x) => x.kg), 1);
        return Math.round((m.kg / max) * 100);
    }
    open(id) {
        S.page = { kind: "order", id };
    }
    telegram() {
        guard(async () => {
            location.href = (await api("telegram")).url;
        });
    }
}

class Notices extends Component {
    static props = [];
    static template = xml`
        <div>
            <h2>Xabarlar</h2>
            <p t-if="!st.rows.length" class="d-muted">Xabar yo'q.</p>
            <div t-foreach="st.rows" t-as="n" t-key="n.id" class="d-card" t-att-class="{'d-click': n.order_id}"
                 t-attf-style="#{n.new ? 'border-color:var(--d-brand)' : ''}" t-on-click="() => this.open(n)">
                <b t-esc="n.title"/><div t-esc="n.body"/><div class="d-muted" t-esc="n.time"/>
            </div>
        </div>`;
    setup() {
        this.st = useState({ rows: [] });
        onWillStart(() => guard(async () => {
            this.st.rows = (await api("notices")).rows;
            await api("notices_seen");
            S.unread = 0;
        }));
    }
    open(n) {
        if (n.order_id) {
            S.page = { kind: "order", id: n.order_id };
        }
    }
}

const TITLES = { katalog: "Katalog", savat: "Savat", buyurtmalar: "Buyurtmalar", moliya: "Moliya", yana: "Yana" };

class App extends Component {
    static components = { Catalog, Cart, Orders, OrderPage, ReturnPage, Finance, More, Notices };
    static props = [];
    static template = xml`
        <t t-if="s.me">
            <header class="d-top">
                <button t-if="s.page" class="d-icon-btn" aria-label="Orqaga" t-on-click="() => this.s.page = null">←</button>
                <h1 t-esc="s.page ? s.me.dealer : titles[s.tab]"/>
                <button class="d-icon-btn" aria-label="Xabarlar" t-on-click="() => this.s.page = {kind: 'notices'}">🔔
                    <span t-if="s.unread" class="d-badge" t-esc="s.unread"/></button>
            </header>
            <main class="d-main">
                <OrderPage t-if="s.page and s.page.kind == 'order'" id="s.page.id" t-key="'o' + s.page.id"/>
                <ReturnPage t-elif="s.page and s.page.kind == 'return'" id="s.page.id" t-key="'r' + s.page.id"/>
                <Notices t-elif="s.page and s.page.kind == 'notices'"/>
                <Catalog t-elif="s.tab == 'katalog'"/>
                <Cart t-elif="s.tab == 'savat'"/>
                <Orders t-elif="s.tab == 'buyurtmalar'"/>
                <Finance t-elif="s.tab == 'moliya'"/>
                <More t-else=""/>
            </main>
            <nav class="d-nav">
                <button t-foreach="tabs" t-as="t" t-key="t[0]" t-att-class="{on: s.tab == t[0] and !s.page}" t-on-click="() => this.go(t[0])">
                    <b t-esc="t[1]"/><t t-esc="t[2]"/>
                    <span t-if="t[0] == 'savat' and s.cart.length" class="d-badge" t-esc="s.cart.length"/>
                </button>
            </nav>
            <div t-if="s.toast" class="d-toast" t-att-class="{bad: s.toast.bad}" role="status" t-esc="s.toast.text"/>
        </t>
        <div t-elif="st.error" class="d-auth"><p class="d-error" t-esc="st.error"/>
            <a class="d-btn d-block" href="/web/session/logout?redirect=/diller/login">Chiqish</a></div>
        <div t-else="" class="d-splash">Yuklanmoqda…</div>`;
    setup() {
        this.s = useState(S);
        this.st = useState({ error: "" });
        this.titles = TITLES;
        this.tabs = [["katalog", "▦", "Katalog"], ["savat", "🛒", "Savat"], ["buyurtmalar", "☰", "Buyurtmalar"],
            ["moliya", "💰", "Moliya"], ["yana", "⋯", "Yana"]];
        onWillStart(async () => {
            try {
                const [me, cat] = await Promise.all([api("init"), api("catalog")]);
                S.rows = cat.rows;
                S.byId = Object.fromEntries(cat.rows.map((r) => [r.id, r]));
                S.me = me;
                S.unread = me.unread;
                S.cartKey = uid4();
                S.cart = store.get("craf_cart_" + me.uid, []).filter((c) => S.byId[c.id]);
            } catch (err) {
                this.st.error = err.message;
            }
        });
        onMounted(() => {
            this.timer = setInterval(() => guard(async () => {
                if (S.me && !document.hidden) {
                    S.unread = (await api("notices")).unread;
                }
            }), 60000);
        });
    }
    go(tab) {
        S.page = null;
        S.tab = tab;
    }
}

function start() {
    const root = document.getElementById("diller-app");
    root.textContent = "";
    mount(App, root);
}
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
} else {
    start();
}
if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/diller/sw.js", { scope: "/diller" }).catch(() => {});
}
