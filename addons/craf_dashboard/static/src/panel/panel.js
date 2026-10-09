import { Component, onWillStart, useEffect, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

// Kategorik ranglar: tekshirilgan tartib (ko'k, to'q sariq, yashil-moviy)
const SERIES = [
    { key: "billet", label: "Quyma (Литейка)", color: "#2a78d6" },
    { key: "press", label: "Profil (press)", color: "#eb6834" },
    { key: "paint", label: "Bo'yalgan profil", color: "#1baf7a" },
];
const PERIODS = [
    ["today", "Bugun"],
    ["7", "7 kun"],
    ["30", "30 kun"],
];

function niceMax(value) {
    if (value <= 0) {
        return 1;
    }
    const pow = Math.pow(10, Math.floor(Math.log10(value)));
    for (const step of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) {
        if (step * pow >= value) {
            return step * pow;
        }
    }
    return 10 * pow;
}

export class CrafPanel extends Component {
    static template = "craf_dashboard.Panel";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.series = SERIES;
        this.periods = PERIODS;
        this.state = useState({ period: "7", data: null, loading: true, hover: null, showTable: false, chartW: 0 });
        this.chartRef = useRef("chartBox");
        useEffect(
            (el) => {
                if (!el) {
                    return;
                }
                const observer = new ResizeObserver((entries) => {
                    const w = Math.round(entries[0].contentRect.width);
                    if (w && Math.abs(w - this.state.chartW) > 2) {
                        this.state.chartW = w;
                    }
                });
                observer.observe(el);
                return () => observer.disconnect();
            },
            () => [this.chartRef.el]
        );
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const data = await this.orm.call("craf.dashboard", "get_data", [this.state.period]);
        this.state.data = data;
        this.state.hover = null;
        this.state.loading = false;
    }

    setPeriod(period) {
        if (period !== this.state.period) {
            this.state.period = period;
            this.load();
        }
    }

    fmt(value, digits = 0) {
        return Number(value || 0).toLocaleString("ru-RU", {
            maximumFractionDigits: digits,
            minimumFractionDigits: digits,
        });
    }

    compact(value) {
        const v = Number(value || 0);
        if (Math.abs(v) >= 1e9) {
            return this.fmt(v / 1e9, 1) + " mlrd";
        }
        if (Math.abs(v) >= 1e6) {
            return this.fmt(v / 1e6, 1) + " mln";
        }
        return this.fmt(v);
    }

    get kpi() {
        return this.state.data.kpi;
    }

    get norms() {
        return this.state.data.norms;
    }

    get periodText() {
        const d = this.state.data;
        const f = (s) => s.split("-").reverse().join(".");
        return d.start === d.end ? f(d.end) : `${f(d.start)} — ${f(d.end)}`;
    }

    // ---- me'yor holati (rang + belgi + matn, rang yolg'iz ma'no tashimaydi)
    status(value, norm, higherIsBetter, hasData) {
        if (!hasData) {
            return { cls: "o_craf_st_none", icon: "fa-minus-circle", text: "ma'lumot yo'q" };
        }
        const ok = higherIsBetter ? value >= norm : value <= norm;
        return ok
            ? { cls: "o_craf_st_good", icon: "fa-check-circle", text: "me'yorda" }
            : { cls: "o_craf_st_warn", icon: "fa-exclamation-triangle", text: "me'yordan tashqari" };
    }

    get stLoss() {
        return this.status(this.kpi.burn_loss_pct, this.norms.burn_loss, false, this.kpi.melt_count > 0);
    }
    get stYield() {
        return this.status(this.kpi.press_yield_pct, this.norms.press_yield, true, this.kpi.shift_count > 0);
    }
    get stDefect() {
        return this.status(this.kpi.defect_pct, this.norms.defect, false, this.kpi.batch_count > 0);
    }

    // ---- grafik (kenglik konteynerga moslashadi)
    get chart() {
        const W = Math.max(280, this.state.chartW || 900);
        return { W, H: W < 576 ? 220 : 280, L: W < 576 ? 44 : 56, R: 8, T: 14, B: 30 };
    }
    get plotW() {
        return this.chart.W - this.chart.L - this.chart.R;
    }
    get plotH() {
        return this.chart.H - this.chart.T - this.chart.B;
    }
    get yMax() {
        const values = this.state.data.series.flatMap((d) => SERIES.map((s) => d[s.key]));
        return niceMax(Math.max(1, ...values));
    }
    get ticks() {
        const max = this.yMax;
        const ticks = [];
        for (let i = 0; i <= 4; i++) {
            const v = (max * i) / 4;
            ticks.push({ v, y: this.yPos(v), label: this.compact(v) });
        }
        return ticks;
    }
    yPos(value) {
        return this.chart.T + this.plotH * (1 - value / this.yMax);
    }
    barPath(x, y, w, base) {
        const h = base - y;
        if (h <= 0.5) {
            return "";
        }
        const r = Math.min(4, h, w / 2);
        return `M${x},${base} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${base} Z`;
    }
    get groups() {
        const days = this.state.data.series;
        const n = days.length;
        const gw = this.plotW / n;
        const gap = 2;
        const bw = Math.max(2, Math.min(24, (gw * 0.72 - gap * 2) / 3));
        const total = bw * 3 + gap * 2;
        const base = this.chart.T + this.plotH;
        // x o'qidagi sanalar bir-biriga tegmasligi uchun (telefonda kamroq yorliq)
        const maxLabels = Math.max(2, Math.floor(this.plotW / 46));
        const step = Math.ceil(n / Math.min(10, maxLabels));
        return days.map((d, i) => {
            const gx = this.chart.L + gw * i;
            const x0 = gx + (gw - total) / 2;
            const bars = SERIES.map((s, j) => {
                const x = x0 + j * (bw + gap);
                const y = this.yPos(d[s.key]);
                return { key: s.key, color: s.color, path: this.barPath(x, y, bw, base) };
            });
            return {
                i,
                day: d,
                hitX: gx,
                hitW: gw,
                cx: gx + gw / 2,
                bars,
                showLabel: i % step === 0 || i === n - 1,
            };
        });
    }
    get hoverGroup() {
        return this.state.hover === null ? null : this.groups[this.state.hover];
    }
    get tooltipStyle() {
        const g = this.hoverGroup;
        if (!g) {
            return "display: none;";
        }
        const pct = (g.cx / this.chart.W) * 100;
        const flip = g.i > this.state.data.series.length / 2;
        return `left: ${pct}%; transform: translateX(${flip ? "calc(-100% - 12px)" : "12px"});`;
    }
    onHover(i) {
        this.state.hover = i;
    }
    onLeave() {
        this.state.hover = null;
    }
    toggleTable() {
        this.state.showTable = !this.state.showTable;
    }
    get seriesTotals() {
        const days = this.state.data.series;
        return SERIES.map((s) => ({ ...s, total: days.reduce((a, d) => a + d[s.key], 0) }));
    }
    get hasSeries() {
        return this.seriesTotals.some((s) => s.total > 0);
    }

    // ---- zavod nuqtalari
    get zoneRows() {
        const zones = [...this.state.data.zones].sort((a, b) => b.kg - a.kg);
        const max = Math.max(1, ...zones.map((z) => z.kg));
        return zones.map((z) => ({ ...z, width: Math.max(1, (z.kg / max) * 100) }));
    }

    // ---- ochish
    openZone(zone) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: zone.name,
            res_model: "stock.quant",
            views: [[false, "list"]],
            domain: [["location_id", "child_of", zone.id]],
            context: { create: false },
        });
    }
    openRecord(model, id) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: id,
            views: [[false, "form"]],
        });
    }
    openList(model, name, domain) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: model,
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain,
        });
    }
    openDrafts(row) {
        this.openList(row.model, `${row.label}: qoralama`, [["state", "=", "draft"]]);
    }
    openProduct(row) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "product.template",
            res_id: row.id,
            views: [[false, "form"]],
        });
    }
    openMap() {
        this.actionService.doAction("craf_zavod.action_craf_zavod_xarita");
    }
}

registry.category("actions").add("craf_dashboard", CrafPanel);
