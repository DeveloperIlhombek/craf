import { patch } from "@web/core/utils/patch";
import { CrafZavodXarita } from "@craf_zavod/xarita/xarita";

patch(CrafZavodXarita.prototype, {
    openTransfer(zone, item) {
        const context = { default_location_id: zone.id };
        if (item) {
            context.default_product_id = item.id;
        }
        this.actionService.doAction(
            {
                type: "ir.actions.act_window",
                name: `Ko'chirish: ${zone.name}`,
                res_model: "craf.zavod.transfer",
                views: [[false, "form"]],
                target: "new",
                context,
            },
            { onClose: () => this.load() }
        );
    },
});
