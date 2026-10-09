{
    "name": "Craf Литейка",
    "version": "19.0.1.0.0",
    "summary": "Литейка: plavka jurnali, shixta tarkibi, quyma partiyasi, шлак, угар %",
    "description": """
Plavka jurnali:
- shixta retsepti (Odoo BoM, namuna) dan reja; haqiqiy sarf har plavkada yoziladi
- chiqqan quyma (kg), шлак (kg), угар kg va %, chiqish %
- tasdiqlanganda MRP buyurtmasi: Литейка dan shixta sarflanadi, quyma Press sexiga, шлак Chiqindiga
- plavka raqami quyma partiyasi bo'lib, press smenasida ko'rsatiladi
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_production", "craf_nomenklatura"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_sequence_data.xml",
        "views/craf_foundry_melt_views.xml",
        "views/craf_foundry_menus.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
