from odoo import api, fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    craf_work_stage = fields.Selection(selection_add=[("matritsa", "Matritsa (qoliplar)")],
                                       ondelete={"matritsa": "set null"})

    @api.model
    def _craf_own_apps(self):
        apps = super()._craf_own_apps()
        apps["matritsa"] = {"menu": "craf_matritsa.menu_craf_matritsa_root",
                            "action": "craf_matritsa.action_craf_matritsa",
                            "counts": ["craf.matritsa", "nav_counts"]}
        return apps

    def _craf_own_nav(self, key):
        if key != "matritsa":
            return super()._craf_own_nav(key)
        item = {"tag": "craf_matritsa", "context": {}}
        return [
            dict(item, key="matritsa", label="Matritsalar", icon="fa-th", tab="matritsa"),
            dict(item, key="gaz", label="Gaz", icon="fa-fire-extinguisher", tab="gaz"),
            dict(item, key="soda", label="Soda", icon="fa-flask", tab="soda"),
            dict(item, key="qoldiq", label="Qoldiq", icon="fa-archive", tab="qoldiq"),
        ]
