import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";

/**
 * Telefondagi pastki panel (bottom bar).
 *  - Yuklovchi: maxsus bandlar (session.craf_loader_nav): Yuklash, Bugun, Qoldiq, Sanash, Yuk xati.
 *  - Boshqa barcha foydalanuvchilar: ochiq turgan ilovaning bo'limlari (menyudan avtomatik,
 *    ya'ni har kim faqat o'ziga ruxsat berilgan bo'limlarni ko'radi). 4 tadan ko'p bo'lsa —
 *    «Ko'proq» varag'i; ichki bo'limi bor band bosilsa — pastdan ro'yxat chiqadi.
 */
const MAX_ITEMS = 5;

// bo'lim nomidan ikonka (uz / ru / en)
const ICONS = [
    [/sotuv|savdo|продаж|sale/i, "fa-shopping-cart"],
    [/yukla|yuk xat|накладн|waybill/i, "fa-truck"],
    [/hisobot|отчет|report|tahlil/i, "fa-bar-chart"],
    [/sozlam|konfigur|настрой|config/i, "fa-cog"],
    [/mahsulot|товар|product|nomenklat/i, "fa-cubes"],
    [/operats|операц|operation|harakat/i, "fa-exchange"],
    [/umumiy|overview|обзор|panel|dashboard|bosh/i, "fa-th-large"],
    [/gaz/i, "fa-flask"],
    [/davomat|посещ|attendance|terminal|ish jadval/i, "fa-clock-o"],
    [/sana(sh|ld)|inventar|count/i, "fa-check-square-o"],
    [/qoldiq|ombor|склад|stock|warehouse/i, "fa-archive"],
    [/xarita|карта|map/i, "fa-map-o"],
    [/pul|kassa|qarz|касс|money|to'lov/i, "fa-money"],
    [/korzin|корзин|basket/i, "fa-shopping-basket"],
    [/ishlab chiq|производ|manufact|press|smena/i, "fa-industry"],
    [/bo'ya|окраск|paint|stiker/i, "fa-paint-brush"],
    [/литей|litey|erit|plavka/i, "fa-fire"],
    [/xodim|сотрудн|employee|ishchi/i, "fa-users"],
    [/telegram|xabar/i, "fa-paper-plane"],
    [/uskuna|maintenance|ta'mir/i, "fa-wrench"],
    [/mijoz|partner|клиент|customer/i, "fa-address-book-o"],
];
function iconFor(name) {
    const hit = ICONS.find(([re]) => re.test(name || ""));
    return hit ? hit[1] : "fa-circle-o";
}

export class CrafLoaderNav extends Component {
    static template = "craf_sex.LoaderNav";
    static props = {};

    setup() {
        this.action = useService("action");
        this.orm = useService("orm");
        this.menu = useService("menu");
        this.ui = useState(useService("ui"));
        this.loaderItems = session.craf_loader_nav || [];
        this.isLoader = this.loaderItems.length > 0;
        this.state = useState({ active: null, counts: {}, items: [], more: [], sheet: null });
        this._onUpdate = () => {
            this.rebuild();
            this.state.active = this.detect();
            if (this.isLoader) {
                this.refreshCounts();
            }
        };
        onMounted(() => {
            this.env.bus.addEventListener("ACTION_MANAGER:UI-UPDATED", this._onUpdate);
            this.env.bus.addEventListener("MENUS:APP-CHANGED", this._onUpdate);
            if (this.isLoader) {
                this._timer = setInterval(() => {
                    if (document.visibilityState === "visible") {
                        this.refreshCounts();
                    }
                }, 60000);
            }
            this._onUpdate();
        });
        onWillUnmount(() => {
            document.body.classList.remove("o_craf_bottom_nav", "o_craf_loader_bar");
            this.env.bus.removeEventListener("ACTION_MANAGER:UI-UPDATED", this._onUpdate);
            this.env.bus.removeEventListener("MENUS:APP-CHANGED", this._onUpdate);
            clearInterval(this._timer);
        });
    }

    get visible() {
        const show = this.ui.isSmall && this.state.items.length > 1;
        document.body.classList.toggle("o_craf_bottom_nav", show);
        document.body.classList.toggle("o_craf_loader_bar", show && this.isLoader);
        return show;
    }

    // ---------- bandlar ----------
    rebuild() {
        if (this.isLoader) {
            this.state.items = this.loaderItems;
            this.state.more = [];
            return;
        }
        const app = this.menu.getCurrentApp();
        if (!app) {
            this.state.items = [];
            return;
        }
        const tree = this.menu.getMenuAsTree(app.id);
        const sections = (tree.childrenTree || []).map((m) => this.toItem(m)).filter(Boolean);
        if (sections.length <= MAX_ITEMS) {
            this.state.items = sections;
            this.state.more = [];
        } else {
            this.state.items = [
                ...sections.slice(0, MAX_ITEMS - 1),
                { key: "__more", label: "Ko'proq", icon: "fa-ellipsis-h", more: true },
            ];
            this.state.more = sections.slice(MAX_ITEMS - 1);
        }
    }

    toItem(m) {
        const children = (m.childrenTree || []).map((c) => this.toItem(c)).filter(Boolean);
        if (!m.actionID && !children.length) {
            return null;
        }
        return {
            key: "m" + m.id,
            menuId: m.id,
            label: m.name,
            icon: iconFor(m.name),
            action_id: m.actionID || false,
            children,
            actionIds: [m.actionID, ...children.flatMap((c) => c.actionIds)].filter(Boolean),
        };
    }

    detect() {
        const action = this.action.currentController && this.action.currentController.action;
        if (!action) {
            return null;
        }
        if (this.isLoader) {
            if (action.tag === "craf_sotuv") {
                return (action.context && action.context.craf_tab) || "load";
            }
            const item = this.loaderItems.find(
                (it) => it.action_id && (action.id === it.action_id || (it.res_model && action.res_model === it.res_model))
            );
            return item ? item.key : null;
        }
        const own = this.state.items.find((it) => it.actionIds && it.actionIds.includes(action.id));
        if (own) {
            return own.key;
        }
        return this.state.more.some((it) => it.actionIds.includes(action.id)) ? "__more" : null;
    }

    async refreshCounts() {
        try {
            this.state.counts = await this.orm.silent.call("craf.sotuv", "loader_nav_counts", []);
        } catch {
            // tarmoq uzilgan bo'lsa — eski son qoladi
        }
    }

    // ---------- bosish ----------
    async open(item) {
        if (item.more) {
            this.toggleSheet({ title: "Ko'proq", items: this.state.more, key: "__more" });
            return;
        }
        if (item.children && item.children.length) {
            const items = item.action_id ? [{ ...item, children: [], label: item.label }, ...item.children] : item.children;
            this.toggleSheet({ title: item.label, items, key: item.key });
            return;
        }
        this.state.sheet = null;
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
        this.state.active = this.isLoader ? item.key : this.detect() || item.key;
    }

    toggleSheet(sheet) {
        this.state.sheet = this.state.sheet && this.state.sheet.key === sheet.key ? null : sheet;
    }

    closeSheet() {
        this.state.sheet = null;
    }

    isActive(item) {
        return this.state.active === item.key || (this.state.sheet && this.state.sheet.key === item.key);
    }
}

registry.category("main_components").add("craf_loader_nav", { Component: CrafLoaderNav });
