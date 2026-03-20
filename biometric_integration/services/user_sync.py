# Copyright (c) 2026, Khaled Bin Amir
# SPDX-License-Identifier: MIT

"""
User sync service: reacts to Employee lifecycle events and propagates changes
to biometric devices.

  Employee save with create_user_in_device=1  → create/link Device User for
                                                selected device, queue Update User
  Employee attendance_device_id changes        → same as above (if checkbox is on)
  Employee goes inactive/left                  → queue Delete User on all devices
  Employee reactivated                         → queue Enroll User on all devices
  Employee name changes                        → queue Update User on all devices
  Attendance Device User gets employee link    → queue Update User on all devices
"""

from __future__ import annotations

from typing import Optional

import frappe

from biometric_integration.biometric_integration.doctype.attendance_device_command.attendance_device_command import (
    add_command,
)

_INACTIVE_STATUSES = {"Left", "Inactive"}
_BRAND_BLOB_FIELD = {"ZKTeco": "zkteco_enroll_data", "EBKN": "ebkn_enroll_data"}


# ---------------------------------------------------------------------------
# Employee hooks
# ---------------------------------------------------------------------------

def validate_employee(doc, method=None) -> None:
    """Frappe doc_events validate hook — runs before save."""
    if not doc.get("create_user_in_device"):
        return
    device_id = str(doc.get("attendance_device_id") or "").strip()
    if device_id and not device_id.isdigit():
        frappe.throw(
            frappe._("Attendance Device ID must be a numeric value. "
                     "ZKTeco and EBKN devices only support integer user IDs."),
            title=frappe._("Invalid Device ID"),
        )


def on_employee_update(doc, method=None) -> None:
    """Frappe doc_events on_update hook — called on every Employee save."""
    before = doc.get_doc_before_save()
    if not before:
        # New employee — handle device user creation if checkbox set
        if doc.get("create_user_in_device") and doc.get("biometric_device"):
            _handle_device_user_creation(doc)
        return

    # --- Status / name changes (always active, no toggle) ---
    user_doc = _find_device_user(doc.name)
    if user_doc:
        status_before = before.status or "Active"
        status_after = doc.status or "Active"
        name_before = before.employee_name or ""
        name_after = doc.employee_name or ""

        if status_before != status_after:
            if status_after in _INACTIVE_STATUSES:
                _delete_from_all_devices(user_doc)
            elif status_after == "Active" and status_before in _INACTIVE_STATUSES:
                _re_enroll_on_all_devices(user_doc)

        if name_before != name_after and status_after not in _INACTIVE_STATUSES:
            _update_user_info(user_doc)

    # --- Device user creation via checkbox ---
    checkbox_before = before.get("create_user_in_device")
    checkbox_after = doc.get("create_user_in_device")
    device_id_before = str(before.get("attendance_device_id") or "").strip()
    device_id_after = str(doc.get("attendance_device_id") or "").strip()

    # Trigger when checkbox just turned on, OR device ID changed while checkbox is on
    if checkbox_after and (
        (not checkbox_before)
        or (device_id_after and device_id_before != device_id_after)
    ):
        if doc.get("biometric_device") and device_id_after:
            _handle_device_user_creation(doc)


# ---------------------------------------------------------------------------
# Called from attendance_device_user.py when employee link is set
# ---------------------------------------------------------------------------

def on_employee_linked(user_doc) -> None:
    """Sync updated employee name to all devices when user gets linked to employee."""
    _update_user_info(user_doc)


# ---------------------------------------------------------------------------
# Device user creation
# ---------------------------------------------------------------------------

def _handle_device_user_creation(employee_doc) -> None:
    """Create or link Attendance Device User and queue Update User on the selected device.

    - Finds existing Device User by attendance_device_id (user_id)
    - Creates one if not found, links employee
    - Adds the selected biometric_device to child table (if not already there)
    - Queues Update User command on that device
    """
    device_id = str(employee_doc.get("attendance_device_id") or "").strip()
    target_device = employee_doc.get("biometric_device")
    if not device_id or not target_device:
        return

    brand = frappe.db.get_value("Attendance Device", target_device, "brand")
    if not brand:
        return

    # Find or create the Device User record
    existing_name = frappe.db.get_value("Attendance Device User", {"user_id": device_id})
    if existing_name:
        user_doc = frappe.get_doc("Attendance Device User", existing_name)
        changed = False
        if not user_doc.employee:
            user_doc.employee = employee_doc.name
            user_doc.employee_name = employee_doc.employee_name
            changed = True
        # Add device to child table if not already there
        existing_devices = {row.attendance_device for row in user_doc.get("devices", [])}
        if target_device not in existing_devices:
            user_doc.append("devices", {"attendance_device": target_device, "brand": brand})
            changed = True
        if changed:
            user_doc.save(ignore_permissions=True)
    else:
        user_doc = frappe.get_doc({
            "doctype": "Attendance Device User",
            "user_id": device_id,
            "employee": employee_doc.name,
            "employee_name": employee_doc.employee_name,
            "devices": [{"attendance_device": target_device, "brand": brand}],
        })
        user_doc.insert(ignore_permissions=True)

    add_command(target_device, user_doc.name, brand, "Update User")
    frappe.db.commit()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_device_user(employee_name: str) -> Optional[object]:
    doc_name = frappe.db.get_value("Attendance Device User", {"employee": employee_name})
    if not doc_name:
        return None
    return frappe.get_doc("Attendance Device User", doc_name)


def _get_user_devices(user_doc) -> dict:
    """Return {device_id: brand} for all active devices this user should be on."""
    if user_doc.allow_in_all_devices:
        devices = frappe.get_all("Attendance Device", filters={"disabled": 0}, fields=["name", "brand"])
        return {d.name: d.brand for d in devices}
    return {
        row.attendance_device: row.brand
        for row in user_doc.get("devices", [])
        if row.attendance_device
    }


def _delete_from_all_devices(user_doc) -> None:
    for device_id, brand in _get_user_devices(user_doc).items():
        add_command(device_id, user_doc.name, brand, "Delete User")
    frappe.db.commit()


def _re_enroll_on_all_devices(user_doc) -> None:
    for device_id, brand in _get_user_devices(user_doc).items():
        blob_field = _BRAND_BLOB_FIELD.get(brand, "")
        if blob_field and user_doc.get(blob_field):
            add_command(device_id, user_doc.name, brand, "Enroll User")
    frappe.db.commit()


def _update_user_info(user_doc) -> None:
    """Queue Update User on all devices (ZKTeco: USERINFO, EBKN: SET_USER_PROFILE)."""
    for device_id, brand in _get_user_devices(user_doc).items():
        add_command(device_id, user_doc.name, brand, "Update User")
    frappe.db.commit()
