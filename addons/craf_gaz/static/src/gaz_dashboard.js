/** @odoo-module **/
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const fmt = (n) => (Math.round((n || 0) * 100) / 100).toLocaleString("ru-RU");
const KIND = { fill: "To'ldirildi", use: "Sarf", adjust: "Sanash" };
const PALETTE = ["#3B82F6", "#F59E0B", "#8B5CF6", "#10B981", "#EF4444", "#EC4899", "#14B8A6", "#64748B"];

export class CrafGazDashboard extends Component {
    static template = "craf_gaz.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.state = useState({
            data: { ballons: [], types: [], moves: [], locations: [] },
            filter: 0, modal: null, form: {}, busy: false,
        });
        this.fmt = fmt;
        this.KIND = KIND;
        this.PALETTE = PALETTE;
        onWillStart(() => this.load());
    }

    async load() {
        this.state.data = await this.orm.call("craf.gaz.ballon", "craf_get_dashboard", []);
    }

    get ballons() {
        const f = this.state.filter;
        return this.state.data.ballons.filter((b) => !f || b.type_id === f);
    }

    // ballon ichidagi gaz balandligi (SVG: ichki bo'shliq y=38..218)
    fillY(b) { return 218 - (180 * b.percent) / 100; }
    fillH(b) { return (180 * b.percent) / 100; }
    gid(b) { return "gz" + b.id; }

    open(modal, form) {
        this.state.form = Object.assign({}, form);
        this.state.modal = modal;
        document.body.classList.add("overflow-hidden");
    }
    close() {
        this.state.modal = null;
        document.body.classList.remove("overflow-hidden");
    }

    newBallon() {
        const t = this.state.filter || (this.state.data.types[0] || {}).id;
        this.open("ballon", { name: "", type_id: t, capacity: 40, qty: 0, location_id: 0, note: "" });
    }
    editBallon(b) { this.open("ballon", { ...b }); }
    newType() { this.open("type", { name: "", code: "", color: PALETTE[this.state.data.types.length % 8], unit: "m3", note: "" }); }
    editType(t) { this.open("type", { ...t }); }
    move(b, kind) {
        const qty = kind === "fill" ? b.capacity - b.qty : kind === "adjust" ? b.qty : 0;
        this.open("move", { ballon_id: b.id, ballon: b, kind, qty: Math.round(qty * 100) / 100, note: "" });
    }

    async save() {
        const { modal, form } = this.state;
        const vals = { ...form };
        delete vals.ballon;
        this.state.busy = true;
        try {
            await this.orm.call("craf.gaz.ballon", "craf_save", [modal, vals]);
            this.notification.add("Saqlandi", { type: "success" });
            this.close();
            await this.load();
        } finally {
            this.state.busy = false;
        }
    }

    async remove(kind, id, label) {
        if (!window.confirm(`${label} — o'chirilsinmi?`)) return;
        await this.orm.call("craf.gaz.ballon", "craf_delete", [kind, id]);
        this.close();
        await this.load();
    }

    typePercent(t) { return t.capacity ? Math.round((t.qty / t.capacity) * 100) : 0; }
}

registry.category("actions").add("craf_gaz_dashboard", CrafGazDashboard);
