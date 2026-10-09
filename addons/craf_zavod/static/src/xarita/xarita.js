import { Component, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

const KIND_COLORS = {
    raw: "#d97706",
    process: "#2563eb",
    finished: "#059669",
    waste: "#dc2626",
};
const KIND_LABELS = {
    raw: "Xom-ashyo",
    process: "Sex / jarayon",
    finished: "Tayyor mahsulot",
    waste: "Chiqindi",
};

export class CrafZavodXarita extends Component {
    static template = "craf_zavod.Xarita";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.kindColors = KIND_COLORS;
        this.kindLabels = KIND_LABELS;
        this.kinds = ["raw", "process", "finished", "waste"];
        this.state = useState({
            zones: [],
            flows: [],
            selectedId: null,
            updated: "",
            loading: true,
            auto: true,
            mview: "list", // telefonda: "list" yoki "scheme"
        });
        this.panelRef = useRef("panel");
        onWillStart(() => this.load());
        this.timer = setInterval(() => {
            if (this.state.auto) {
                this.load();
            }
        }, 30000);
        onWillUnmount(() => clearInterval(this.timer));
    }

    async load() {
        const data = await this.orm.call("craf.zavod.xarita", "get_map_data", []);
        this.state.zones = data.zones;
        this.state.flows = data.flows;
        this.state.updated = new Date().toLocaleTimeString("ru-RU", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
        });
        if (!this.state.zones.find((z) => z.id === this.state.selectedId)) {
            this.state.selectedId = data.zones.length ? data.zones[0].id : null;
        }
        this.state.loading = false;
    }

    // ---------- hisob-kitob ----------
    get mapW() {
        return Math.max(600, ...this.state.zones.map((z) => z.x + z.w)) + 40;
    }
    get mapH() {
        return Math.max(300, ...this.state.zones.map((z) => z.y + z.h)) + 80;
    }
    get viewBox() {
        return `0 0 ${this.mapW} ${this.mapH}`;
    }
    get maxKg() {
        return Math.max(1, ...this.state.zones.map((z) => z.kg_total));
    }
    get selected() {
        return this.state.zones.find((z) => z.id === this.state.selectedId);
    }
    ratio(zone) {
        return zone.kg_total / this.maxKg;
    }
    fillOpacity(zone) {
        return (0.08 + 0.3 * this.ratio(zone)).toFixed(3);
    }
    barWidth(zone) {
        return Math.max(4, (zone.w - 32) * this.ratio(zone));
    }
    fmt(value, digits = 0) {
        return Number(value || 0).toLocaleString("ru-RU", {
            maximumFractionDigits: digits,
            minimumFractionDigits: 0,
        });
    }
    flowGeom(flow) {
        const a = this.state.zones.find((z) => z.id === flow.from);
        const b = this.state.zones.find((z) => z.id === flow.to);
        if (!a || !b) {
            return null;
        }
        const ax = a.x + a.w / 2;
        const ay = a.y + a.h / 2;
        const bx = b.x + b.w / 2;
        const by = b.y + b.h / 2;
        const overlapX = a.x < b.x + b.w && b.x < a.x + a.w;
        const overlapY = a.y < b.y + b.h && b.y < a.y + a.h;
        let x1, y1, x2, y2, lx, ly, anchor;
        if (overlapY && !overlapX) {
            const y = (Math.max(a.y, b.y) + Math.min(a.y + a.h, b.y + b.h)) / 2;
            [x1, x2] = bx > ax ? [a.x + a.w, b.x] : [a.x, b.x + b.w];
            y1 = y2 = y;
            [lx, ly, anchor] = [(x1 + x2) / 2, y - 10, "middle"];
        } else if (overlapX && !overlapY) {
            const x = (Math.max(a.x, b.x) + Math.min(a.x + a.w, b.x + b.w)) / 2;
            [y1, y2] = by > ay ? [a.y + a.h, b.y] : [a.y, b.y + b.h];
            x1 = x2 = x;
            [lx, ly, anchor] = [x + 10, (y1 + y2) / 2 + 4, "start"];
        } else {
            [x1, x2] = [ax, bx];
            [y1, y2] = by < ay ? [a.y, b.y + b.h] : [a.y + a.h, b.y];
            [lx, ly, anchor] = [(x1 + x2) / 2 + 16, (y1 + y2) / 2 - 10, "start"];
        }
        return { x1, y1, x2, y2, lx, ly, anchor };
    }

    // ---------- harakatlar ----------
    select(zone, scrollToPanel = false) {
        this.state.selectedId = zone.id;
        if (scrollToPanel && window.innerWidth < 768) {
            // telefonda tanlangan zona tafsiloti ro'yxat ostida — unga silliq o'tamiz
            setTimeout(() => this.panelRef.el?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
        }
    }
    setMobileView(mode) {
        this.state.mview = mode;
    }
    toggleAuto(ev) {
        this.state.auto = ev.target.checked;
    }
    openZone(zone) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: zone.full_name,
            res_model: "stock.quant",
            views: [[false, "list"]],
            domain: [["location_id", "child_of", zone.id]],
            context: { create: false },
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
}

registry.category("actions").add("craf_zavod_xarita", CrafZavodXarita);
