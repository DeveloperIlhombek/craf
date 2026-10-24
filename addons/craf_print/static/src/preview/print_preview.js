import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";
import { Dialog } from "@web/core/dialog/dialog";
import { downloadReport, getReportUrl } from "@web/webclient/actions/reports/utils";
import { Component, useRef, useState } from "@odoo/owl";

const VIEWER = "/web/static/lib/pdfjs/web/viewer.html";

/**
 * PDF hisobotni Odoo ichida ko'rsatadi (pdf.js) va shu yerdan chop etadi —
 * fayl yuklab olinmaydi, brauzerning alohida PDF oynasiga o'tilmaydi.
 */
export class CrafPrintPreview extends Component {
    static template = "craf_print.PrintPreview";
    static components = { Dialog };
    static props = {
        action: Object,
        pdfUrl: String,
        title: String,
        close: Function,
    };

    setup() {
        this.frame = useRef("frame");
        this.state = useState({ ready: false, printing: false, downloading: false });
        this.viewerUrl = `${VIEWER}?file=${encodeURIComponent(this.props.pdfUrl)}#pagemode=none`;
        this.timer = null;
    }

    get app() {
        try {
            return this.frame.el?.contentWindow?.PDFViewerApplication || null;
        } catch {
            return null;
        }
    }

    onFrameLoad() {
        // pdf.js hujjatni o'zi yuklaydi — u tayyor bo'lgach tugma yoqiladi
        const wait = () => {
            const app = this.app;
            if (app?.pdfDocument) {
                // odatiy 150 DPI da mayda matn va QR xira chiqadi
                this.frame.el.contentWindow.PDFViewerApplicationOptions?.set("printResolution", 300);
                this.state.ready = true;
                return;
            }
            this.timer = setTimeout(wait, 150);
        };
        wait();
    }

    print() {
        const win = this.frame.el?.contentWindow;
        if (!win) {
            return;
        }
        this.state.printing = true;
        try {
            const app = this.app;
            if (app?.triggerPrinting) {
                app.triggerPrinting();
            } else {
                win.focus();
                win.print();
            }
        } finally {
            setTimeout(() => (this.state.printing = false), 800);
        }
    }

    async download() {
        this.state.downloading = true;
        try {
            const context = { ...user.context, ...(this.props.action.context || {}) };
            await downloadReport(rpc, this.props.action, "pdf", context);
        } finally {
            this.state.downloading = false;
        }
    }

    close() {
        clearTimeout(this.timer);
        this.props.close();
    }
}

function pdfUrl(action) {
    let url = getReportUrl(action, "pdf", user.context);
    if (!url.includes("?")) {
        // ma'lumotsiz hisobotda kontekst (til, kompaniya) qo'shilmaydi — o'zimiz qo'shamiz
        const context = { ...user.context, ...(action.context || {}) };
        url += `?context=${encodeURIComponent(JSON.stringify(context))}`;
    }
    return url;
}

let wkhtmlStatus = null;

async function crafPrintHandler(action, options, env) {
    if (action.report_type !== "qweb-pdf" || action.context?.craf_print_download) {
        return false;
    }
    wkhtmlStatus ||= rpc("/report/check_wkhtmltopdf");
    if (!["ok", "upgrade"].includes(await wkhtmlStatus)) {
        return false; // Odoo o'zi HTML ko'rinishga o'tadi va sababini aytadi
    }
    env.services.dialog.add(CrafPrintPreview, {
        action,
        pdfUrl: pdfUrl(action),
        title: action.display_name || action.name || _t("Chop etish"),
    });
    return true;
}

registry.category("ir.actions.report handlers").add("craf_print_preview", crafPrintHandler);
