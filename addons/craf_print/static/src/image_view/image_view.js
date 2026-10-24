import { patch } from "@web/core/utils/patch";
import { imageUrl } from "@web/core/utils/urls";
import { isBinarySize } from "@web/core/utils/binary";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { FileModel } from "@web/core/file_viewer/file_model";
import { ImageField, fileTypeMagicWordMap } from "@web/views/fields/image/image_field";
import { Many2ManyBinaryField } from "@web/views/fields/many2many_binary/many2many_binary_field";

/**
 * Rasmlar yangi oynada ochilmaydi va yuklab olinmaydi — Odoo ichidagi ko'rish oynasida
 * (FileViewer: kattalashtirish, burish, yuklab olish, chop etish) ko'rinadi.
 */

// image_128 kabi kichik nusxa o'rniga to'liq rasm
function fullImageField(name) {
    return /^image_\d+$/.test(name) ? "image_1920" : name;
}

patch(ImageField.prototype, {
    setup() {
        super.setup(...arguments);
        this.crafViewer = useFileViewer();
    },

    get crafCanView() {
        // kanban/ro'yxatdagi kichik rasmlarda bosish yozuvni ochadi — faqat formada
        return (
            this.env.config?.viewType === "form" &&
            !!this.props.record.data[this.props.name] &&
            this.state.isValid
        );
    },

    crafViewImage(ev) {
        // formaning ichidagi kanban/ro'yxat kartochkasi — bosish o'sha yozuvni ochadi
        if (!this.crafCanView || ev.target.closest(".o_kanban_record, .o_data_row")) {
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();
        const value = this.props.record.data[this.props.name];
        let url;
        if (this.fieldType === "many2one") {
            const field = this.props.record.fields[this.props.name];
            url = imageUrl(field.relation, value.id, fullImageField(this.props.previewImage), {
                unique: this.rawCacheKey,
            });
        } else if (isBinarySize(value)) {
            const name = fullImageField(this.props.name);
            const field = name in this.props.record.fields ? name : this.props.name;
            url = imageUrl(this.props.record.resModel, this.props.record.resId, field, {
                unique: this.rawCacheKey,
            });
        } else {
            // saqlanmagan, hozirgina yuklangan rasm
            url = `data:image/${fileTypeMagicWordMap[value[0]] || "png"};base64,${value}`;
        }
        const download = url.startsWith("data:") ? url : `${url}${url.includes("?") ? "&" : "?"}download=true`;
        const label = this.props.record.fields[this.props.name].string;
        const recordName = this.props.record.data.display_name;
        this.crafViewer.open({
            name: recordName ? `${recordName} — ${label}` : label,
            isImage: true,
            isViewable: true,
            defaultSource: url,
            downloadUrl: download,
        });
    },
});

patch(Many2ManyBinaryField.prototype, {
    setup() {
        super.setup(...arguments);
        this.crafViewer = useFileViewer();
    },

    crafViewFile(ev, file) {
        const files = this.files.map((f) =>
            Object.assign(new FileModel(), { id: f.id, name: f.name, mimetype: f.mimetype })
        );
        const current = files.find((f) => f.id === file.id);
        if (!current?.isViewable) {
            return; // ko'rib bo'lmaydigan fayl (Excel, zip …) — odatdagidek yuklab olinadi
        }
        ev.preventDefault();
        ev.stopPropagation();
        this.crafViewer.open(current, files);
    },
});
