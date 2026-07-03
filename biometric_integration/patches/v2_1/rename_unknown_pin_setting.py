# Copyright (c) 2026, Khaled Bin Amir
# SPDX-License-Identifier: MIT

"""Rename the double-negative setting field
`do_not_skip_unknown_employee_checkin` -> `create_checkin_for_unknown_pin`
on Attendance Integration Settings (a Single doctype). Runs pre_model_sync so
the stored value is carried to the new fieldname before the schema syncs.
"""

import frappe
from frappe.model.utils.rename_field import rename_field


def execute():
    if not frappe.db.exists("DocType", "Attendance Integration Settings"):
        return
    # tabSingles stores Single-doctype values as (parent, field, value) rows.
    has_old = frappe.db.exists(
        "Singles",
        {"doctype": "Attendance Integration Settings",
         "field": "do_not_skip_unknown_employee_checkin"},
    )
    has_new = frappe.db.exists(
        "Singles",
        {"doctype": "Attendance Integration Settings",
         "field": "create_checkin_for_unknown_pin"},
    )
    if has_old and not has_new:
        try:
            rename_field(
                "Attendance Integration Settings",
                "do_not_skip_unknown_employee_checkin",
                "create_checkin_for_unknown_pin",
            )
        except Exception:
            # Fallback for Single doctypes: move the value row directly.
            frappe.db.sql(
                """UPDATE `tabSingles` SET field=%s
                   WHERE doctype=%s AND field=%s""",
                ("create_checkin_for_unknown_pin",
                 "Attendance Integration Settings",
                 "do_not_skip_unknown_employee_checkin"),
            )
            frappe.db.commit()
