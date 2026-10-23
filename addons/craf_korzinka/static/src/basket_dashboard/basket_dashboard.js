import { Component, onWillStart, onWillUpdateProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { KanbanRenderer } from "@web/views/kanban/kanban_renderer";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { ListRenderer } from "@web/views/list/list_renderer";
import { listView } from "@web/views/list/list_view";

/** Korzinkalar sahifasi tepasidagi kichik dashboard: jami, bo'sh, to'la, yaroqsiz, profil kg, aylanish. */
export class CrafBasketDashboard extends Component {
    static template = "craf_korzinka.BasketDashboard";
    static props = { list: { type: Object, optional: true } };

    setup() {
        this.orm = useService("orm");
        onWillStart(() => this.load());
        onWillUpdateProps(() => this.load());
    }

    async load() {
        this.data = await this.orm.call("craf.basket", "get_dashboard", []);
    }

    fmt(value, digits = 0) {
        return (value || 0).toLocaleString("ru-RU", { maximumFractionDigits: digits }).replace(/,/g, ".");
    }

    /** Kartochka bosilsa — shu filtr bilan ro'yxat. */
    filter(name) {
        const sm = this.env.searchModel;
        const items = sm.getSearchItems((item) => ["empty", "filled", "broken", "stale"].includes(item.name));
        const target = items.find((item) => item.name === name);
        const active = target && target.isActive;
        sm.query = [];
        if (target && !active) {
            sm.toggleSearchItem(target.id);
        } else {
            sm.search();
        }
    }
}

export class CrafBasketListRenderer extends ListRenderer {
    static template = "craf_korzinka.BasketListRenderer";
    static components = { ...ListRenderer.components, CrafBasketDashboard };
}

export class CrafBasketKanbanRenderer extends KanbanRenderer {
    static template = "craf_korzinka.BasketKanbanRenderer";
    static components = { ...KanbanRenderer.components, CrafBasketDashboard };
}

registry.category("views").add("craf_basket_list", { ...listView, Renderer: CrafBasketListRenderer });
registry.category("views").add("craf_basket_kanban", { ...kanbanView, Renderer: CrafBasketKanbanRenderer });
