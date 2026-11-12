import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const KIND_COLORS = {
    raw: "#d97706",
    process: "#2563eb",
    finished: "#059669",
    waste: "#dc2626",
    external: "#7c3aed",
};
const KIND_LABELS = {
    raw: "Xom-ashyo",
    process: "Sex / jarayon",
    finished: "Tayyor mahsulot",
    waste: "Chiqindi",
    external: "Tashqi",
};
const PERIODS = [
    { key: "today", label: "Bugun" },
    { key: "7", label: "7 kun" },
    { key: "30", label: "30 kun" },
];
const LS_KEY = "craf_zavod_xarita_period";

function lsGet(key, fallback) {
    try {
        return window.localStorage.getItem(key) || fallback;
    } catch {
        return fallback;
    }
}
function lsSet(key, value) {
    try {
        window.localStorage.setItem(key, value);
    } catch {
        // brauzer xotirasi yopiq — e'tiborsiz
    }
}

export class CrafZavodXarita extends Component {
    static template = "craf_zavod.Xarita";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.kindColors = KIND_COLORS;
        this.kindLabels = KIND_LABELS;
        this.kinds = ["raw", "process", "finished", "waste", "external"];
        this.periods = PERIODS;
        this.reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
        this.state = useState({
            zones: [],
            virtual: [],
            flows: [],
            kpis: [],
            period: lsGet(LS_KEY, "today"),
            periodLabel: "",
            selectedId: null,
            updated: "",
            loading: true,
            auto: true,
            mview: "list",
            canEdit: false,
            edit: false,
            dirty: false,
            search: "",
            moves: [],
            movesLoading: false,
            hoverFlow: null,
            focus: false, // foydalanuvchi blokni bosgan — boshqa oqimlar xiralashadi
        });
        // count-up animatsiya: ko'rsatiladigan qiymatlar
        this.disp = useState({});
        this.svgRef = useRef("svg");
        this.panelRef = useRef("panel");
        this.drag = null;
        onWillStart(() => this.load());
        onMounted(() => this.loadMoves());
        this.timer = setInterval(() => {
            if (this.state.auto && !this.state.edit && !document.hidden) {
                this.load();
            }
        }, 30000);
        onWillUnmount(() => {
            clearInterval(this.timer);
            if (this.raf) {
                cancelAnimationFrame(this.raf);
            }
        });
    }

    // ------------------------------------------------------------------ yuklash
    async load() {
        const data = await this.orm.call("craf.zavod.xarita", "get_map_data", [], {
            top_limit: 12,
            period: this.state.period,
        });
        if (this.state.edit) {
            return; // tartiblash paytida joylar qayta yozilmasin
        }
        Object.assign(this.state, {
            zones: data.zones,
            virtual: data.virtual,
            flows: data.flows,
            kpis: data.kpis,
            periodLabel: data.period_label,
            canEdit: data.can_edit,
            loading: false,
            updated: new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        });
        if (!this.nodes.find((n) => n.id === this.state.selectedId)) {
            const first = this.visibleZones.find((z) => z.kg_total > 0) || this.visibleZones[0];
            this.state.selectedId = first ? first.id : null;
        }
        this.animateNumbers();
    }

    async loadMoves() {
        const id = this.state.selectedId;
        if (!id || typeof id !== "number") {
            this.state.moves = [];
            return;
        }
        this.state.movesLoading = true;
        const moves = await this.orm.call("craf.zavod.xarita", "get_zone_moves", [id], {
            period: this.state.period,
            limit: 15,
        });
        if (this.state.selectedId === id) {
            this.state.moves = moves;
            this.state.movesLoading = false;
        }
    }

    animateNumbers() {
        const targets = {};
        for (const k of this.state.kpis) {
            targets["k_" + k.key] = k.value;
        }
        for (const z of this.state.zones) {
            targets["z_" + z.id] = z.kg_total;
        }
        for (const n of this.state.virtual) {
            targets["v_" + n.id] = n.kg;
        }
        const from = {};
        for (const key in targets) {
            from[key] = this.disp[key] ?? 0;
        }
        if (this.raf) {
            cancelAnimationFrame(this.raf);
        }
        if (this.reducedMotion) {
            Object.assign(this.disp, targets);
            return;
        }
        const t0 = performance.now();
        const dur = 900;
        const step = (now) => {
            const p = Math.min(1, (now - t0) / dur);
            const e = 1 - Math.pow(1 - p, 3);
            for (const key in targets) {
                this.disp[key] = from[key] + (targets[key] - from[key]) * e;
            }
            if (p < 1) {
                this.raf = requestAnimationFrame(step);
            }
        };
        this.raf = requestAnimationFrame(step);
    }

    // ------------------------------------------------------------------ tugunlar va geometriya
    get visibleZones() {
        return this.state.zones.filter((z) => this.state.edit || !z.hidden);
    }
    get visibleVirtual() {
        return this.state.virtual.filter((n) => this.state.edit || !n.hidden);
    }
    get nodes() {
        return [...this.visibleZones, ...this.visibleVirtual];
    }
    node(id) {
        return this.nodes.find((n) => n.id === id);
    }
    get selected() {
        return this.state.zones.find((z) => z.id === this.state.selectedId);
    }
    get selectedVirtual() {
        return this.state.virtual.find((n) => n.id === this.state.selectedId);
    }
    get mapW() {
        return Math.max(900, ...this.nodes.map((z) => z.x + z.w)) + 30;
    }
    get mapH() {
        return Math.max(420, ...this.nodes.map((z) => z.y + z.h)) + 40;
    }
    get viewBox() {
        return `0 0 ${this.mapW} ${this.mapH}`;
    }
    get maxKg() {
        return Math.max(1, ...this.state.zones.map((z) => z.kg_total));
    }
    get maxFlow() {
        return Math.max(1, ...this.state.flows.map((f) => f.kg));
    }
    get visibleFlows() {
        return this.state.flows.filter((f) => this.node(f.from) && this.node(f.to));
    }
    get activeFlows() {
        return this.visibleFlows.filter((f) => f.kg > 0).sort((a, b) => b.kg - a.kg);
    }
    level(zone) {
        // to'lish darajasi: log shkala — kichik qoldiq ham ko'rinsin
        if (!zone.kg_total || zone.kg_total <= 0) {
            return 0;
        }
        return Math.min(1, Math.max(0.04, Math.log10(1 + zone.kg_total) / Math.log10(1 + this.maxKg)));
    }
    flowWidth(flow) {
        if (!flow.kg) {
            return 1.5;
        }
        return 2.5 + 9 * Math.sqrt(flow.kg / this.maxFlow);
    }
    dashWidth(flow) {
        return Math.max(1.5, this.flowWidth(flow) / 3);
    }
    particleR(flow) {
        return Math.max(3, this.flowWidth(flow) / 2.2);
    }
    kpiUnit(k) {
        // «short» 10 000 dan katta kg ni «t» / «mln» bilan yozadi — birlik takrorlanmasin
        return k.unit === "kg" && Math.abs(k.value) >= 1e4 ? "" : k.unit;
    }
    flowDur(flow) {
        // ko'p oqim — tezroq zarrachalar
        return (6 - 4 * Math.sqrt(flow.kg / this.maxFlow)).toFixed(2);
    }
    particles(flow) {
        if (!flow.kg || this.reducedMotion || this.state.edit) {
            return [];
        }
        const n = Math.max(1, Math.round(1 + 4 * Math.sqrt(flow.kg / this.maxFlow)));
        const dur = Number(this.flowDur(flow));
        return Array.from({ length: n }, (_, i) => ({ i, begin: `-${((dur / n) * i).toFixed(2)}s` }));
    }
    flowColor(flow) {
        const src = this.node(flow.from);
        return src ? KIND_COLORS[src.kind] || KIND_COLORS.process : "#64748b";
    }
    anchor(a, b) {
        // a blokning b tomonga qaragan chetidagi nuqta va yo'nalish
        const ax = a.x + a.w / 2;
        const ay = a.y + a.h / 2;
        const bx = b.x + b.w / 2;
        const by = b.y + b.h / 2;
        const dx = bx - ax;
        const dy = by - ay;
        if (Math.abs(dx) * a.h >= Math.abs(dy) * a.w) {
            const s = Math.sign(dx) || 1;
            return { x: ax + (s * a.w) / 2, y: ay + Math.max(-a.h / 3, Math.min(a.h / 3, dy * 0.15)), nx: s, ny: 0 };
        }
        const s = Math.sign(dy) || 1;
        return { x: ax + Math.max(-a.w / 3, Math.min(a.w / 3, dx * 0.15)), y: ay + (s * a.h) / 2, nx: 0, ny: s };
    }
    flowPath(flow) {
        const a = this.node(flow.from);
        const b = this.node(flow.to);
        if (!a || !b) {
            return null;
        }
        const p = this.anchor(a, b);
        const q = this.anchor(b, a);
        const reverse = this.state.flows.some((f) => f.from === flow.to && f.to === flow.from);
        const dist = Math.hypot(q.x - p.x, q.y - p.y);
        const k = Math.max(40, dist * 0.4);
        // qarama-qarshi oqimlar bir-birining ustiga tushmasin: biri yon tomonga egiladi
        let off = 0;
        if (reverse) {
            off = String(flow.from) < String(flow.to) ? 26 : -26;
        }
        // yo'lda boshqa blok bo'lsa — yoy bo'lib ustidan (yoki chetidan) aylanib o'tadi
        const blocked = this.nodes.some((n) => n !== a && n !== b && this.segHitsRect(p, q, n, 12));
        if (blocked) {
            const nx = -(q.y - p.y) / (dist || 1);
            const ny = (q.x - p.x) / (dist || 1);
            // yuqoriga (y kamayadigan) tomonga egilsin
            const sign = ny > 0 ? -1 : ny < 0 ? 1 : nx > 0 ? -1 : 1;
            off = sign * Math.min(140, 60 + dist * 0.12);
        }
        const ox = (-(q.y - p.y) / (dist || 1)) * off;
        const oy = ((q.x - p.x) / (dist || 1)) * off;
        const p1 = { x: p.x + ox * 0.6, y: p.y + oy * 0.6 };
        const q1 = { x: q.x + ox * 0.6, y: q.y + oy * 0.6 };
        const c1 = { x: p1.x + p.nx * k + ox, y: p1.y + p.ny * k + oy };
        const c2 = { x: q1.x + q.nx * k + ox, y: q1.y + q.ny * k + oy };
        const d = `M${p1.x.toFixed(1)},${p1.y.toFixed(1)} C${c1.x.toFixed(1)},${c1.y.toFixed(1)} ${c2.x.toFixed(1)},${c2.y.toFixed(1)} ${q1.x.toFixed(1)},${q1.y.toFixed(1)}`;
        // egri chiziq o'rtasi (t = 0.5)
        const mx = 0.125 * p1.x + 0.375 * c1.x + 0.375 * c2.x + 0.125 * q1.x;
        const my = 0.125 * p1.y + 0.375 * c1.y + 0.375 * c2.y + 0.125 * q1.y;
        return { d, mx, my };
    }
    segHitsRect(p, q, r, pad = 0) {
        // kesma (p→q) to'rtburchakni kesib o'tadimi (Liang–Barsky)
        const x0 = r.x - pad;
        const y0 = r.y - pad;
        const x1 = r.x + r.w + pad;
        const y1 = r.y + r.h + pad;
        const dx = q.x - p.x;
        const dy = q.y - p.y;
        let t0 = 0;
        let t1 = 1;
        const checks = [
            [-dx, p.x - x0],
            [dx, x1 - p.x],
            [-dy, p.y - y0],
            [dy, y1 - p.y],
        ];
        for (const [pp, qq] of checks) {
            if (pp === 0) {
                if (qq < 0) {
                    return false;
                }
                continue;
            }
            const t = qq / pp;
            if (pp < 0) {
                t0 = Math.max(t0, t);
            } else {
                t1 = Math.min(t1, t);
            }
            if (t0 > t1) {
                return false;
            }
        }
        return true;
    }
    flowKey(flow) {
        return `${flow.from}-${flow.to}`;
    }
    pillWidth(flow) {
        const text = `${this.short(flow.kg)} kg`;
        return Math.max(48, text.length * 7.2 + 16);
    }
    flowText(flow) {
        return flow.kg ? `${flow.label} · ${this.short(flow.kg)} kg` : flow.label;
    }

    // ------------------------------------------------------------------ formatlash
    fmt(value, digits = 0) {
        return Number(value || 0).toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
    }
    short(value) {
        const v = Math.abs(value || 0);
        if (v >= 1e6) {
            return `${this.fmt(value / 1e6, 1)} mln`;
        }
        if (v >= 1e4) {
            return `${this.fmt(value / 1e3, 1)} t`;
        }
        return this.fmt(value);
    }
    num(key) {
        return this.disp[key] ?? 0;
    }
    unitsText(zone) {
        return zone.units
            .slice(0, 2)
            .map((u) => `${this.short(u.qty)} ${u.uom}`)
            .join(" · ");
    }
    zoneLines(zone) {
        const lines = [`${zone.product_count} xil mahsulot`];
        const units = this.unitsText(zone);
        if (units) {
            lines.push(units);
        }
        return lines;
    }
    zoneFlows(id) {
        const incoming = this.state.flows.filter((f) => f.to === id && f.kg > 0);
        const outgoing = this.state.flows.filter((f) => f.from === id && f.kg > 0);
        return { incoming, outgoing };
    }
    nodeName(id) {
        const n = this.state.zones.find((z) => z.id === id) || this.state.virtual.find((v) => v.id === id);
        return n ? n.name : id;
    }
    get filteredItems() {
        const z = this.selected;
        if (!z) {
            return [];
        }
        const s = this.state.search.trim().toLowerCase();
        const items = s ? z.items.filter((i) => `${i.name} ${i.code}`.toLowerCase().includes(s)) : z.items;
        return items.slice(0, s ? 60 : 12);
    }
    get panelZone() {
        // craf_kochirish va boshqa kengaytmalar «z» va «z.top» ni ishlatadi
        const z = this.selected;
        return z ? { ...z, top: this.filteredItems } : null;
    }

    // ------------------------------------------------------------------ harakatlar
    select(node, scrollToPanel = false) {
        if (this.drag?.moved) {
            return;
        }
        // shu blokni qayta bosish — fokusni olib tashlaydi
        this.state.focus = !(this.state.focus && this.state.selectedId === node.id);
        this.state.selectedId = node.id;
        this.state.search = "";
        this.loadMoves();
        if (scrollToPanel && window.innerWidth < 1200) {
            setTimeout(() => this.panelRef.el?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
        }
    }
    setPeriod(key) {
        this.state.period = key;
        lsSet(LS_KEY, key);
        this.load().then(() => this.loadMoves());
    }
    setMobileView(mode) {
        this.state.mview = mode;
    }
    toggleAuto(ev) {
        this.state.auto = ev.target.checked;
    }
    onSearch(ev) {
        this.state.search = ev.target.value;
    }
    setHover(flow) {
        this.state.hoverFlow = flow ? this.flowKey(flow) : null;
    }
    isDim(flow) {
        const h = this.state.hoverFlow;
        if (h) {
            return h !== this.flowKey(flow);
        }
        const sel = this.state.selectedId;
        return Boolean(this.state.focus && sel && flow.from !== sel && flow.to !== sel && this.selectedHasFlows);
    }
    get selectedHasFlows() {
        const sel = this.state.selectedId;
        return this.state.flows.some((f) => f.kg > 0 && (f.from === sel || f.to === sel));
    }

    // --- tartiblash (bloklarni surish, yashirish)
    toggleEdit() {
        if (this.state.edit && this.state.dirty) {
            this.saveLayout();
            return;
        }
        this.state.edit = !this.state.edit;
        if (!this.state.edit) {
            this.load();
        }
    }
    cancelEdit() {
        this.state.edit = false;
        this.state.dirty = false;
        this.load();
    }
    toggleHidden(node) {
        node.hidden = !node.hidden;
        this.state.dirty = true;
    }
    svgPoint(ev) {
        const svg = this.svgRef.el;
        const pt = svg.createSVGPoint();
        pt.x = ev.clientX;
        pt.y = ev.clientY;
        return pt.matrixTransform(svg.getScreenCTM().inverse());
    }
    onPointerDown(ev, node) {
        if (!this.state.edit) {
            return;
        }
        ev.preventDefault();
        const p = this.svgPoint(ev);
        this.drag = { node, dx: p.x - node.x, dy: p.y - node.y, moved: false };
        ev.currentTarget.setPointerCapture?.(ev.pointerId);
    }
    onPointerMove(ev) {
        if (!this.drag) {
            return;
        }
        const p = this.svgPoint(ev);
        const grid = 10;
        const x = Math.max(0, Math.round((p.x - this.drag.dx) / grid) * grid);
        const y = Math.max(0, Math.round((p.y - this.drag.dy) / grid) * grid);
        if (x !== this.drag.node.x || y !== this.drag.node.y) {
            this.drag.node.x = x;
            this.drag.node.y = y;
            this.drag.moved = true;
            this.state.dirty = true;
        }
    }
    onPointerUp() {
        const drag = this.drag;
        setTimeout(() => {
            if (this.drag === drag) {
                this.drag = null;
            }
        }, 0);
    }
    async saveLayout() {
        const positions = {};
        const hidden = [];
        for (const n of [...this.state.zones, ...this.state.virtual]) {
            positions[n.id] = { x: n.x, y: n.y };
            if (n.hidden) {
                hidden.push(String(n.id));
            }
        }
        await this.orm.call("craf.zavod.xarita", "save_layout", [positions, hidden]);
        this.state.edit = false;
        this.state.dirty = false;
        this.notification.add("Xarita tartibi saqlandi", { type: "success" });
        this.load();
    }

    // --- boshqa sahifalarga o'tish
    openZone(zone) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: zone.name,
            res_model: "stock.quant",
            views: [[false, "list"]],
            domain: [["location_id", "child_of", zone.id]],
            context: { search_default_productgroup: 1 },
        });
    }
    openProduct(item) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            res_id: item.id,
            views: [[false, "form"]],
        });
    }
    openMove(move) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "stock.move",
            res_id: move.id,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("craf_zavod_xarita", CrafZavodXarita);
