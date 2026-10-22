import { registry } from "@web/core/registry";
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

/**
 * Ro'yxat pastidagi jami qatorida og'irlik bo'yicha o'rtacha:
 * <field name="yield_pct" avg="O'rtacha" options="{'weighted': ['output_kg', 'billet_qty', 100]}"/>
 * → Σ output_kg / Σ billet_qty × 100 (oddiy o'rtacha emas); 4-qiymat (ixtiyoriy) natijaga qo'shiladi. Surat va maxraj maydonlari ro'yxatda bo'lishi kerak
 * (yashirin optional ham bo'ladi). Guruh qatorlari server tomonda (_read_group_select) hisoblanadi.
 */
patch(ListRenderer.prototype, {
    computeAggregates() {
        const aggregates = super.computeAggregates(...arguments);
        const list = this.props.list;
        let values;
        if (list.selection.length) {
            values = list.selection.map((r) => r.data);
        } else if (list.isGrouped) {
            values = list.groups.map((g) => g.aggregates);
        } else {
            values = list.records.map((r) => r.data);
        }
        for (const column of this.columns) {
            const weighted = column.type === "field" && column.options?.weighted;
            if (!weighted || !(column.name in aggregates)) {
                continue;
            }
            const [num, den, factor = 1, offset = 0] = weighted;
            let sumNum = 0;
            let sumDen = 0;
            for (const v of values) {
                sumNum += v[num] || 0;
                sumDen += v[den] || 0;
            }
            if (!sumDen) {
                continue;
            }
            const value = (sumNum / sumDen) * factor + offset;
            const field = this.fields[column.name];
            const formatter = registry.category("formatters").get(column.widget, false) ||
                registry.category("formatters").get(field.type, false);
            aggregates[column.name] = {
                ...aggregates[column.name],
                value: formatter ? formatter(value, { digits: field.digits, escape: true }) : value,
                rawValue: value,
            };
        }
        return aggregates;
    },
});
