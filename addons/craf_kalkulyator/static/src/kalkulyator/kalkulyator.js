import { onWillStart, useState } from "@odoo/owl";
import { CrafKunlik } from "@craf_hisobot/kunlik/kunlik";
import { patch } from "@web/core/utils/patch";

const DEPS = [
    { key: "boyash", label: "Bo'yash va qadoqlash", short: "Bo'yash", kinds: ["painted", "kg"] },
    { key: "pech", label: "Pech", short: "Pech", kinds: ["kg"] },
    { key: "boshqa", label: "Boshqa bo'lim", short: "Boshqa", kinds: ["painted", "semi", "kg", "other"] },
];

let rowSeq = 1;
function newRow(values = {}) {
    return { key: rowSeq++, text: "", pid: false, a: "", b: "", edit: false, editVal: "", ...values };
}
function num(value) {
    const v = parseFloat(String(value ?? "").replace(",", ".").replace(/\s/g, ""));
    return Number.isFinite(v) ? v : 0;
}

patch(CrafKunlik.prototype, {
    setup() {
        super.setup(...arguments);
        this.calcDeps = DEPS;
        this.calc = useState({ dep: "boyash", rows: [newRow()], products: [], busy: false, collapsed: false });
        this.calcById = new Map();
        this.calcByText = new Map();
        onWillStart(async () => {
            const products = await this.orm.call("craf.kunlik.hisobot", "get_calc_products", []);
            this.calcIndex(products);
            this.calcRestore();
        });
    },

    async load(date) {
        if (this.calc && this.state.date) {
            this.calcStore();
        }
        await super.load(...arguments);
        if (this.calc && this.calc.products.length) {
            this.calcRestore();
        }
    },

    // ------------------------------------------------------------------ mahsulotlar
    calcIndex(products) {
        this.calc.products = products;
        this.calcById = new Map(products.map((p) => [p.id, p]));
        this.calcByText = new Map();
        for (const p of products) {
            this.calcByText.set(p.label.toLowerCase(), p);
            if (p.code && !this.calcByText.has(p.code.toLowerCase())) {
                this.calcByText.set(p.code.toLowerCase(), p);
            }
        }
    },
    get calcDep() {
        return DEPS.find((d) => d.key === this.calc.dep) || DEPS[0];
    },
    get calcOptions() {
        const kinds = this.calcDep.kinds;
        return this.calc.products.filter((p) => kinds.includes(p.kind));
    },
    calcFind(text) {
        const t = (text || "").trim().toLowerCase();
        if (!t) {
            return null;
        }
        if (this.calcByText.has(t)) {
            return this.calcByText.get(t);
        }
        const matches = this.calcMatches(t);
        return matches.length === 1 ? matches[0] : null;
    },
    calcMatches(text) {
        const t = (text || "").trim().toLowerCase();
        return t ? this.calcOptions.filter((p) => p.label.toLowerCase().includes(t)) : [];
    },
    calcProduct(row) {
        return row.pid ? this.calcById.get(row.pid) : null;
    },

    // ------------------------------------------------------------------ hisob
    calcUnits(row) {
        const p = this.calcProduct(row);
        if (!p) {
            return { a: "pachka / o'ram", b: "dona / kg" };
        }
        if (p.uom === "kg") {
            return { a: p.pkg_name || "o'ram", b: "kg" };
        }
        return { a: "pachka", b: p.uom || "dona" };
    },
    calcRow(row) {
        const p = this.calcProduct(row);
        const a = num(row.a);
        const b = num(row.b);
        if (!p) {
            let error = "";
            if (row.text) {
                const n = this.calcMatches(row.text).length;
                error = n > 1 ? `${n} ta mahsulot mos keladi — ro'yxatdan tanlang` : "Mahsulot topilmadi";
            }
            return { ok: false, empty: !row.text && !a && !b, error };
        }
        if (p.uom === "kg") {
            const missing = a && !p.pkg_kg;
            const kg = a * (p.pkg_kg || 0) + b;
            return {
                ok: !missing && Boolean(a || b), p, unit: "kg", qty: kg, kg, pcs: 0, missing: missing ? "pkg" : "",
                noUnit: !p.pkg_kg,
                hint: p.pkg_kg ? `1 ${p.pkg_name || "o'ram"} = ${this.fmtQty(p.pkg_kg, 3)} kg` : "o'ram og'irligi kiritilmagan — kg yozing",
            };
        }
        const missing = a && !p.per_pack;
        const pcs = a * (p.per_pack || 0) + b;
        let packs = "";
        if (p.per_pack && pcs >= p.per_pack) {
            const full = Math.floor(pcs / p.per_pack);
            const rest = Math.round(pcs - full * p.per_pack);
            packs = rest ? `${full} pachka + ${rest}` : `${full} pachka`;
        }
        return {
            ok: !missing && Boolean(a || b), p, unit: p.uom || "dona", qty: pcs, pcs, kg: pcs * (p.kg_pc || 0),
            packs, missing: missing ? "pack" : "", noUnit: !p.per_pack,
            hint: p.per_pack ? `1 pachka = ${p.per_pack} dona` : "dona/pachka kiritilmagan",
        };
    },
    get calcResults() {
        return this.calc.rows.map((row) => ({ row, res: this.calcRow(row) }));
    },
    get calcTotals() {
        const t = { pcs: 0, kg: 0, pcsKg: 0, kgOnly: 0, count: 0, errors: 0 };
        for (const { res } of this.calcResults) {
            if (res.ok) {
                t.count++;
                t.pcs += res.pcs || 0;
                t.kg += res.kg || 0;
                if (res.unit === "kg") {
                    t.kgOnly += res.kg;
                } else {
                    t.pcsKg += res.kg || 0;
                }
            } else if (res.error || res.missing) {
                t.errors++;
            }
        }
        return t;
    },
    /** 1C uchun: bir xil mahsulot qatorlari birlashtiriladi */
    get calcSummary() {
        const map = new Map();
        for (const { res } of this.calcResults) {
            if (!res.ok) {
                continue;
            }
            const item = map.get(res.p.id) || { p: res.p, unit: res.unit, qty: 0, kg: 0 };
            item.qty += res.qty;
            item.kg += res.kg;
            map.set(res.p.id, item);
        }
        return [...map.values()];
    },

    // ------------------------------------------------------------------ kiritish
    calcSetDep(key) {
        if (key === this.calc.dep) {
            return;
        }
        this.calcStore();
        this.calc.dep = key;
        this.calcRestore();
    },
    calcOnText(row, ev) {
        row.text = ev.target.value;
        const p = this.calcFind(row.text);
        row.pid = p ? p.id : false;
        this.calcStore();
    },
    calcOnTextChange(row, ev) {
        const p = this.calcProduct(row);
        if (p && ev.target.value !== p.label) {
            row.text = p.label;
            ev.target.value = p.label;
            this.calcStore();
        }
    },
    calcSet(row, field, ev) {
        row[field] = ev.target.value;
        this.calcStore();
    },
    calcOnKey(row, field, ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            const idx = this.calc.rows.indexOf(row);
            if (field === "b" && idx === this.calc.rows.length - 1) {
                this.calcAdd(true);
            } else {
                const inputs = [...document.querySelectorAll(".o_ck_calc input:not([type=hidden])")];
                const i = inputs.indexOf(ev.target);
                if (i >= 0 && inputs[i + 1]) {
                    inputs[i + 1].focus();
                }
            }
        }
    },
    calcAdd(focus = false) {
        this.calc.rows.push(newRow());
        this.calcStore();
        if (focus) {
            setTimeout(() => {
                const inputs = document.querySelectorAll(".o_ck_calc .o_ck_calc_prod");
                inputs[inputs.length - 1]?.focus();
            }, 30);
        }
    },
    calcRemove(row) {
        const idx = this.calc.rows.indexOf(row);
        if (idx >= 0) {
            this.calc.rows.splice(idx, 1);
        }
        if (!this.calc.rows.length) {
            this.calc.rows.push(newRow());
        }
        this.calcStore();
    },
    calcClear() {
        this.calc.rows = [newRow()];
        this.calcStore();
    },
    calcToggle() {
        this.calc.collapsed = !this.calc.collapsed;
    },

    // dona/pachka yoki o'ram og'irligini mahsulotga saqlash
    calcStartEdit(row) {
        const p = this.calcProduct(row);
        row.edit = true;
        row.editVal = p ? String((p.uom === "kg" ? p.pkg_kg : p.per_pack) || "") : "";
    },
    async calcSaveUnit(row) {
        const p = this.calcProduct(row);
        if (!p) {
            return;
        }
        const field = p.uom === "kg" ? "craf_pkg_kg" : "craf_pcs_per_pack";
        const value = p.uom === "kg" ? num(row.editVal) : Math.round(num(row.editVal));
        const info = await this.orm.call("craf.kunlik.hisobot", "calc_set_unit", [p.id, field, value]);
        Object.assign(p, info);
        this.calcIndex([...this.calc.products]);
        row.edit = false;
        this.notification.add(`${p.label}: saqlandi`, { type: "success" });
    },

    // ------------------------------------------------------------------ saqlash (shu brauzerda)
    calcKey(dep) {
        return `craf_kalk:${this.state.date || "bugun"}:${dep || this.calc.dep}`;
    },
    calcStore() {
        try {
            const rows = this.calc.rows
                .filter((r) => r.text || r.a || r.b)
                .map((r) => ({ text: r.text, pid: r.pid, a: r.a, b: r.b }));
            if (rows.length) {
                window.localStorage.setItem(this.calcKey(), JSON.stringify(rows));
            } else {
                window.localStorage.removeItem(this.calcKey());
            }
        } catch {
            // brauzer xotirasi yopiq bo'lsa — shunchaki saqlanmaydi
        }
    },
    calcRestore() {
        let rows = [];
        try {
            rows = JSON.parse(window.localStorage.getItem(this.calcKey()) || "[]");
        } catch {
            rows = [];
        }
        rows = (Array.isArray(rows) ? rows : [])
            .map((r) => newRow({ text: r.text || "", pid: this.calcById.has(r.pid) ? r.pid : false, a: r.a ?? "", b: r.b ?? "" }));
        this.calc.rows = rows.length ? rows : [newRow()];
    },

    // ------------------------------------------------------------------ natija
    async calcCopy() {
        const lines = [["Kod", "Mahsulot", "Miqdor", "Birlik", "kg"].join("\t")];
        for (const s of this.calcSummary) {
            lines.push([s.p.code, s.p.name, this.calcNum(s.qty, s.unit === "kg" ? 3 : 0), s.unit, this.calcNum(s.kg, 2)].join("\t"));
        }
        const t = this.calcTotals;
        if (t.pcs) {
            lines.push(["", "Jami profil", this.calcNum(t.pcs, 0), "dona", this.calcNum(t.pcsKg, 2)].join("\t"));
        }
        if (t.kgOnly) {
            lines.push(["", "Jami xom-ashyo", this.calcNum(t.kgOnly, 3), "kg", this.calcNum(t.kgOnly, 2)].join("\t"));
        }
        const text = lines.join("\n");
        try {
            await navigator.clipboard.writeText(text);
        } catch {
            const area = document.createElement("textarea");
            area.value = text;
            document.body.appendChild(area);
            area.select();
            document.execCommand("copy");
            area.remove();
        }
        this.notification.add("Nusxa olindi — 1C yoki Excel ga qo'yish mumkin", { type: "success" });
    },
    calcNum(value, digits) {
        // 1C / Excel uchun: bo'shliqsiz, vergul bilan, ortiqcha nollarsiz
        let text = Number(value || 0).toFixed(digits);
        if (text.includes(".")) {
            text = text.replace(/0+$/, "").replace(/\.$/, "");
        }
        return text.replace(".", ",");
    },
    async calcWrite() {
        const dep = this.calc.dep;
        const method = dep === "pech" ? "calc_to_melt" : "calc_to_paint";
        const rows = this.calcResults
            .filter(({ res }) => res.ok)
            .map(({ row }) => ({ product_id: row.pid, a: num(row.a), b: num(row.b) }));
        if (!rows.length) {
            this.notification.add("Avval qatorlarni to'ldiring", { type: "warning" });
            return;
        }
        this.calc.busy = true;
        try {
            const result = await this.orm.call("craf.kunlik.hisobot", method, [this.state.date, rows]);
            const names = result.docs.map((d) => d.name).join(", ");
            let message = `${names} — qoralamaga yozildi. Hujjatni ochib tekshiring va Tasdiqlang.`;
            if (result.skipped.length) {
                message += ` Yozilmadi: ${result.skipped.join(", ")}`;
            }
            this.notification.add(message, { type: result.skipped.length ? "warning" : "success", sticky: !!result.skipped.length });
            await this.load();
        } finally {
            this.calc.busy = false;
        }
    },
    itemTotals(rows) {
        let pcs = 0;
        let kg = 0;
        let hasPcs = false;
        for (const r of rows || []) {
            if (r.uom === "dona") {
                pcs += r.qty;
                hasPcs = true;
            }
            kg += r.kg || 0;
        }
        return { pcs, kg, hasPcs };
    },
});
