{
    "name": "Craf Bo'yash",
    "version": "19.0.1.2.0",
    "summary": "Bo'yash: rang, kukun va kimyo sarfi, brak; bo'yalmagan → bo'yalgan profil",
    "description": """
Bo'yash smenasi:
- rang tanlanadi, kukun bo'yoq rang kartochkasidan olinadi
- qatorlar: bo'yalmagan profil → shu rangdagi tayyor profil (o'zi topiladi), kirgan dona, brak dona
- maydon (m²) = perimetr × uzunlik × dona; kukun normasi g/m² bo'yicha reja, haqiqiy sarf alohida
- kimyo (POLITOKSAL, ALUPOL) sarfi
- tasdiqlanganda MRP buyurtmasi: Bo'yash sexidan sarf, bo'yalgan profil Qadoqlashga, brak Chiqindiga
- pachka yorliqlari bir tugmada
- guruh va jami qatorlarida brak %, kukun g/m2 va kukun farqi og'irlik bo'yicha (oddiy o'rtacha emas)
- rang bo'yicha kukun normasi (g/m2) va fakt; brak yoki kukun chegaradan oshsa smena belgilanadi, mas'ullarga eslatma
- materiallar (kukun, kimyo, plyonka, lenta) qoldig'i va prognoz: oxirgi N kun sarfi bo'yicha necha kunga yetishi
""",
    "author": "Craf",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "depends": ["craf_extrusion"],
    "data": [
        "security/ir.model.access.csv",
        "data/craf_paint_data.xml",
        "data/craf_paint_qadoq.xml",
        "data/craf_paint_norm_data.xml",
        "views/craf_paint_batch_views.xml",
        "views/craf_paint_norm_views.xml",
        "views/craf_paint_menus.xml",
    ],
    "installable": True,
    "application": False,
}
