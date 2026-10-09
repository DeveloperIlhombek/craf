import { Component, onWillStart, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class CrafKunlik extends Component {
    static template = "craf_hisobot.Kunlik";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({ date: null, data: null, loading: true, onlyLow: false });
        onWillStart(() => this.load());
    }

    async load(date) {
        this.state.loading = true;
        const data = await this.orm.call("craf.kunlik.hisobot", "get_data", [date || this.state.date || false]);
        this.state.data = data;
        this.state.date = data.date;
        this.state.loading = false;
    }

    fmt(value, digits = 2) {
        const v = Number(value || 0);
        if (Math.abs(v) < 0.005) {
            return "—";
        }
        return v.toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
    }

    fmtQty(value, digits = 2) {
        const v = Number(value || 0);
        return v.toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
    }

    go(date) {
        this.load(date);
    }
    onDateChange(ev) {
        if (ev.target.value) {
            this.load(ev.target.value);
        }
    }
    today() {
        this.load(false);
    }

    get rawRows() {
        const rows = this.state.data.raw;
        return this.state.onlyLow ? rows.filter((r) => r.low) : rows;
    }
    toggleLow() {
        this.state.onlyLow = !this.state.onlyLow;
    }

    openDoc(doc) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: doc.model,
            res_id: doc.id,
            views: [[false, "form"]],
        });
    }
    newDoc(dep) {
        this.actionService.doAction(
            {
                type: "ir.actions.act_window",
                name: dep.title,
                res_model: dep.model,
                views: [[false, "form"]],
                context: { default_date: this.state.date },
            },
            { onClose: () => this.load() }
        );
    }
    openProduct(row) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "product.product",
            res_id: row.product_id,
            views: [[false, "form"]],
        });
    }
    downloadXlsx() {
        window.location.href = `/craf/kunlik/xlsx?date=${this.state.date}`;
    }
    print() {
        window.print();
    }
    markC1() {
        const n = this.state.data.c1_new;
        this.dialog.add(ConfirmationDialog, {
            title: "1C ga kiritildi",
            body: `${this.state.data.date_label} kunining ${n} ta bajarilgan hujjati "1C ga kiritildi" deb belgilanadi. Davom etasizmi?`,
            confirmLabel: "Belgilash",
            confirm: async () => {
                const count = await this.orm.call("craf.kunlik.hisobot", "action_mark_c1", [this.state.date]);
                this.notification.add(`${count} ta hujjat 1C ga kiritildi deb belgilandi`, { type: "success" });
                await this.load();
            },
            cancel: () => {},
        });
    }
}

registry.category("actions").add("craf_kunlik", CrafKunlik);
