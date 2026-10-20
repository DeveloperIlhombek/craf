import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";

/**
 * Yuklovchi uchun telefondagi pastki panel: Yuklash, Bugun, Qoldiq, Sanash, Yuk xati.
 * Bandlar serverdan keladi (session.craf_loader_nav) — faqat yuklovchi rolida.
 */
export class CrafLoaderNav extends Component {
    static template = "craf_sex.LoaderNav";
    static props = {};

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.ui = useState(useService("ui"));
        this.items = session.craf_loader_nav || [];
        this.state = useState({ active: null, counts: {} });
        this._onUpdate = () => {
            this.state.active = this.detect();
            this.refreshCounts();
        };
        onMounted(() => {
            if (!this.items.length) {
                return;
            }
            document.body.classList.add("o_craf_bottom_nav");
            this.env.bus.addEventListener("ACTION_MANAGER:UI-UPDATED", this._onUpdate);
            this._timer = setInterval(() => {
                if (document.visibilityState === "visible") {
                    this.refreshCounts();
                }
            }, 60000);
            this._onUpdate();
        });
        onWillUnmount(() => {
            document.body.classList.remove("o_craf_bottom_nav");
            this.env.bus.removeEventListener("ACTION_MANAGER:UI-UPDATED", this._onUpdate);
            clearInterval(this._timer);
        });
    }

    get visible() {
        return this.items.length > 0 && this.ui.isSmall;
    }

    detect() {
        const action = this.action.currentController && this.action.currentController.action;
        if (!action) {
            return null;
        }
        if (action.tag === "craf_sotuv") {
            return (action.context && action.context.craf_tab) || "load";
        }
        const item = this.items.find(
            (it) => it.action_id && (action.id === it.action_id || (it.res_model && action.res_model === it.res_model))
        );
        return item ? item.key : null;
    }

    async refreshCounts() {
        try {
            this.state.counts = await this.orm.silent.call("craf.sotuv", "loader_nav_counts", []);
        } catch {
            // tarmoq uzilgan bo'lsa — eski son qoladi
        }
    }

    async open(item) {
        if (item.tab) {
            await this.action.doAction(
                {
                    type: "ir.actions.client",
                    tag: "craf_sotuv",
                    name: item.label,
                    context: { craf_tab: item.tab },
                    target: "current",
                },
                { clearBreadcrumbs: true }
            );
        } else if (item.action_id) {
            await this.action.doAction(item.action_id, { clearBreadcrumbs: true });
        }
        this.state.active = item.key;
    }
}

registry.category("main_components").add("craf_loader_nav", { Component: CrafLoaderNav });
