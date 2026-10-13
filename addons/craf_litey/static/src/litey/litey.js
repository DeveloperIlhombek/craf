import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

function addDays(iso, n) {
    const d = new Date(iso + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
}

export class CrafLitey extends Component {
    static template = "craf_litey.Litey";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({ data: null, loading: true, tab: "harakat", from: false, to: false, onlyActive: false });
        onWillStart(() => this.load());
    }

    async load(from, to) {
        this.state.loading = true;
        const f = from === undefined ? this.state.from : from;
        const t = to === undefined ? this.state.to : to;
        const data = await this.orm.call("craf.litey.hisobot", "get_data", [f || false, t || false]);
        this.state.data = data;
        this.state.from = data.date_from;
        this.state.to = data.date_to;
        this.state.loading = false;
    }

    // ---------------------------------------------------------------- format
    fmt(value, digits = 1) {
        const v = Number(value || 0);
        if (Math.abs(v) < 0.005) {
            return "—";
        }
        return v.toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
    }
    num(value, digits = 1) {
        return Number(value || 0).toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
    }
    lossClass(state) {
        return { ok: "text-success", warn: "o_cl_warn", bad: "text-danger", none: "text-muted" }[state] || "";
    }
    get kpiLossState() {
        const k = this.state.data.kpi;
        if (!k.metal) {
            return "none";
        }
        if (k.loss_pct < 0 || k.loss_pct > 5) {
            return "bad";
        }
        return k.loss_pct > 3 ? "warn" : "ok";
    }

    // ---------------------------------------------------------------- davr
    onFrom(ev) {
        if (ev.target.value) {
            this.load(ev.target.value, this.state.to);
        }
    }
    onTo(ev) {
        if (ev.target.value) {
            this.load(this.state.from, ev.target.value);
        }
    }
    preset(kind) {
        const today = this.state.data.today;
        if (kind === "today") {
            this.load(today, today);
        } else if (kind === "7") {
            this.load(addDays(today, -6), today);
        } else if (kind === "30") {
            this.load(addDays(today, -29), today);
        } else if (kind === "month") {
            this.load(today.slice(0, 8) + "01", today);
        }
    }
    shift(days) {
        const span = Math.round((new Date(this.state.to) - new Date(this.state.from)) / 86400000) + 1;
        const step = days * span;
        this.load(addDays(this.state.from, step), addDays(this.state.to, step));
    }
    setTab(tab) {
        this.state.tab = tab;
    }

    // ---------------------------------------------------------------- jadvallar
    get movementRows() {
        const rows = this.state.data.movement;
        if (!this.state.onlyActive) {
            return rows;
        }
        return rows.filter((r) =>
            ["kirim", "chiqish_plavka", "chiqish_boshqa", "sarf_plavka", "sarf_boshqa", "tuzatish", "boshqa"].some(
                (k) => Math.abs(r[k]) > 0.005
            )
        );
    }
    toggleActive() {
        this.state.onlyActive = !this.state.onlyActive;
    }
    get movementTotals() {
        const t = {};
        for (const k of ["chiqish_plavka", "sarf_plavka"]) {
            t[k] = this.state.data.movement.filter((r) => r.uom === "kg").reduce((s, r) => s + r[k], 0);
        }
        return t;
    }
    meltQty(melt, col) {
        return melt.qty[String(col.product_id)] || 0;
    }
    meltText(melt, col) {
        return melt.text[String(col.product_id)] || "";
    }

    // ---------------------------------------------------------------- amallar
    openMoves(row) {
        this.orm
            .call("craf.litey.hisobot", "action_open_moves", [row.product_id, this.state.from, this.state.to])
            .then((action) => this.actionService.doAction(action));
    }
    openMelt(melt) {
        this.actionService.doAction(
            { type: "ir.actions.act_window", res_model: "craf.foundry.melt", res_id: melt.id, views: [[false, "form"]] },
            { onClose: () => this.load() }
        );
    }
    openPicking(r) {
        this.actionService.doAction({
            type: "ir.actions.act_window", res_model: "stock.picking", res_id: r.picking_id, views: [[false, "form"]],
        });
    }
    newMelt() {
        this.actionService.doAction(
            {
                type: "ir.actions.act_window",
                name: "Plavka",
                res_model: "craf.foundry.melt",
                views: [[false, "form"]],
                context: { default_date: this.state.to },
            },
            { onClose: () => this.load() }
        );
    }
    openMelts() {
        this.actionService.doAction("craf_foundry.action_craf_foundry_melt");
    }
    newKirim() {
        this.actionService.doAction("craf_litey.action_craf_litey_kirim", {
            additionalContext: { default_date: this.state.to },
            onClose: () => this.load(),
        });
    }
    importExcel() {
        this.actionService.doAction("craf_litey.action_craf_litey_import", { onClose: () => this.load() });
    }
    async inventory() {
        const action = await this.orm.call("craf.litey.hisobot", "action_inventory", []);
        this.actionService.doAction(action);
    }
    downloadXlsx() {
        window.location.href = `/craf/litey/xlsx?date_from=${this.state.from}&date_to=${this.state.to}`;
    }
    print() {
        window.print();
    }
}

registry.category("actions").add("craf_litey", CrafLitey);
