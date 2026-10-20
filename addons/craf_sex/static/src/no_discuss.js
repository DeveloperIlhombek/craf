import { registry } from "@web/core/registry";

// Muhokama (Discuss) ishlatilmaydi: tepadagi chat / xabarlar belgisi olib tashlanadi.
// Faoliyatlar (soat belgisi) va sotuv bildirishnomalari qoladi.
const systray = registry.category("systray");
if (systray.contains("mail.messaging_menu")) {
    systray.remove("mail.messaging_menu");
}
