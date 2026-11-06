/** Telefonga bildirishnoma: har bir account uchun «Yoqish» banneri va foydalanuvchi menyusidagi band.
 *
 * Odoo ruxsat berilgach qurilmani o'zi ro'yxatga oladi (mail WebClient: _subscribePush). Biz faqat ruxsat
 * so'raymiz, yozilganini tekshirib sinov xabarini yuboramiz. iPhone'da veb-push faqat «Bosh ekranga qo'shish»
 * bilan o'rnatilgan ilovada ishlaydi (iOS 16.4+), oddiy Safari oynasida PushManager yo'q.
 */
import { Component, onMounted, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

const HIDE_KEY = "craf_push_hidden_until";
const JUST_KEY = "craf_push_just_enabled";
const HIDE_DAYS = 3;

function isIOS() {
    const ua = navigator.userAgent || "";
    return /iPad|iPhone|iPod/.test(ua) || (ua.includes("Mac") && "ontouchend" in document);
}

function isStandalone() {
    return (
        window.matchMedia?.("(display-mode: standalone)").matches || navigator.standalone === true
    );
}

/** default / granted / denied / ios (o'rnatish kerak) / unsupported */
export function pushState() {
    // `browser` — Odoo o'rami, `in` bilan tekshirib bo'lmaydi: haqiqiy window
    const ok = "Notification" in window && "serviceWorker" in navigator && "PushManager" in window;
    if (!ok) {
        return isIOS() && !isStandalone() ? "ios" : "unsupported";
    }
    return window.Notification.permission;
}

function storage(key, value) {
    try {
        if (value === undefined) {
            return browser.localStorage.getItem(key);
        }
        if (value === null) {
            browser.localStorage.removeItem(key);
        } else {
            browser.localStorage.setItem(key, value);
        }
    } catch {
        // xususiy oyna — saqlanmaydi
    }
    return null;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** Qurilma serverda yozilguncha kutib, sinov xabarini yuboradi. true — yuborildi. */
async function sendTest(orm, tries = 8) {
    for (let i = 0; i < tries; i++) {
        const n = await orm.call("res.users", "craf_push_test", []);
        if (n) {
            return true;
        }
        await sleep(1500);
    }
    return false;
}

/** Ruxsat so'rash. Natija: granted bo'lsa sinov yuboriladi (kerak bo'lsa sahifa yangilanadi). */
async function enable(orm, notification) {
    let perm;
    try {
        perm = await window.Notification.requestPermission();
    } catch {
        perm = pushState();
    }
    if (perm !== "granted") {
        if (perm === "denied") {
            notification.add(
                "Bildirishnoma bloklandi. Telefon sozlamalarida (Chrome → Sayt sozlamalari → Bildirishnomalar) shu saytga ruxsat bering.",
                { type: "warning", sticky: true }
            );
        }
        return perm;
    }
    notification.add("Bildirishnoma yoqildi — sinov xabari yuborilmoqda…", { type: "success" });
    if (await sendTest(orm, 6)) {
        notification.add("Sinov xabari yuborildi — bir necha soniyada telefonga keladi.", { type: "success" });
    } else {
        // ba'zi brauzerlar (iPhone) ruxsat o'zgarishini sezmaydi — qurilma sahifa yangilanganda yoziladi
        storage(JUST_KEY, "1");
        browser.location.reload();
    }
    return perm;
}

export class CrafPushBanner extends Component {
    static template = "craf_profile.PushBanner";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        const until = Number(storage(HIDE_KEY) || 0);
        this.state = useState({ perm: pushState(), hidden: until > Date.now() });
        onMounted(async () => {
            if (storage(JUST_KEY) && this.state.perm === "granted") {
                storage(JUST_KEY, null);
                await sleep(2500);
                if (await sendTest(this.orm)) {
                    this.notification.add("Sinov xabari yuborildi — bir necha soniyada telefonga keladi.", {
                        type: "success",
                    });
                }
            }
        });
    }

    get show() {
        return user.isInternalUser && !this.state.hidden && ["default", "denied", "ios"].includes(this.state.perm);
    }

    async onEnable() {
        this.state.perm = await enable(this.orm, this.notification);
    }

    onClose() {
        storage(HIDE_KEY, String(Date.now() + HIDE_DAYS * 24 * 3600 * 1000));
        this.state.hidden = true;
    }
}

registry.category("main_components").add("craf_push_banner", { Component: CrafPushBanner });

registry.category("user_menuitems").add("craf_push", (env) => ({
    type: "item",
    id: "craf_push",
    description: "Telefonga bildirishnoma",
    sequence: 15,
    callback: async () => {
        const { orm, notification } = env.services;
        const perm = pushState();
        if (perm === "granted") {
            const ok = await sendTest(orm, 3);
            notification.add(
                ok
                    ? "Bildirishnoma yoqilgan. Sinov xabari yuborildi."
                    : "Ruxsat bor, lekin qurilma hali yozilmagan. Sahifani yangilab, qayta urinib ko'ring.",
                { type: ok ? "success" : "warning" }
            );
        } else if (perm === "default") {
            await enable(orm, notification);
        } else if (perm === "denied") {
            notification.add(
                "Bildirishnoma bloklangan. Telefon sozlamalarida (Chrome → Sayt sozlamalari → Bildirishnomalar) shu saytga ruxsat bering.",
                { type: "warning", sticky: true }
            );
        } else if (perm === "ios") {
            notification.add(
                "iPhone: Safari'da «Ulashish» → «Bosh ekranga qo'shish», keyin ilovani bosh ekrandan oching va shu yerdan yoqing.",
                { type: "info", sticky: true }
            );
        } else {
            notification.add("Bu brauzer bildirishnomani qo'llamaydi. Chrome yoki Safari'dan foydalaning.", {
                type: "warning",
            });
        }
    },
}));
