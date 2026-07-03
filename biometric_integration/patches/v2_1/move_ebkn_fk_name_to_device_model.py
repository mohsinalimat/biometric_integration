# Copyright (c) 2026, Khaled Bin Amir
# SPDX-License-Identifier: MIT

"""Move EBKN device model names out of the mac_address field.

EBKN devices reported their model/product name (`fk_name`), which was wrongly
stored in `mac_address`. It now lives in the new `device_model` field. For EBKN
devices, move the value across and clear mac_address. ZKTeco devices store a real
MAC there, so they are left untouched.
"""

import frappe


def execute():
    if not frappe.db.has_column("Attendance Device", "device_model"):
        return
    ebkn_devices = frappe.get_all(
        "Attendance Device",
        filters={"brand": "EBKN", "mac_address": ["is", "set"]},
        fields=["name", "mac_address", "device_model"],
    )
    for d in ebkn_devices:
        updates = {"mac_address": None}
        if not d.device_model:
            updates["device_model"] = d.mac_address
        frappe.db.set_value("Attendance Device", d.name, updates, update_modified=False)
    if ebkn_devices:
        frappe.db.commit()
