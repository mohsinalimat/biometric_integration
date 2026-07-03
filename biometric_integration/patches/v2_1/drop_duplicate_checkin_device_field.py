# Copyright (c) 2026, Khaled Bin Amir
# SPDX-License-Identifier: MIT

"""Remove the redundant `Employee Checkin.attendance_device` custom field.

`device_id` (a property-set Link to Attendance Device) is the single source of
truth for the originating device; `attendance_device` duplicated it and was never
read by anything. Deleting the Custom Field drops its column from the (high-volume)
Employee Checkin table.
"""

import frappe


def execute():
    name = "Employee Checkin-attendance_device"
    if frappe.db.exists("Custom Field", name):
        frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
        frappe.db.commit()
