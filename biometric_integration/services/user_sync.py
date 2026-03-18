# Copyright (c) 2026, Khaled Bin Amir
# SPDX-License-Identifier: MIT

"""
User sync service: reacts to Employee lifecycle events and propagates changes
to biometric devices.

  Employee created (after_insert)         → create/link Device User, queue Update User (if sync enabled)
  Employee attendance_device_id changes   → same as above (if sync enabled)
  Employee goes inactive/left             → queue Delete User on all devices
  Employee reactivated                    → queue Enroll User on all devices (if template exists)
  Employee name changes                   → queue Update User on ZKTeco devices
  Attendance Device User gets employee link → queue Update User on ZKTeco devices
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

def on_employee_create(doc, method=None) -> None:
    """Frappe doc_events after_insert hook — fires when a new Employee is saved."""
    settings = frappe.get_cached_doc("Attendance Integration Settings")
    if not settings.sync_employee_to_devices_on_create:
        return
    sync_employee_to_devices(doc)


def on_employee_update(doc, method=None) -> None:
    """Frappe doc_events on_update hook — called on every Employee save."""
    before = doc.get_doc_before_save()
    if not before:
        return

    # Always handle status/name changes regardless of sync setting
    user_doc = _find_device_user(doc.name)
    if user_doc:
        status_before = before.status or "Active"
        status_after = doc.status or "Active"
        name_before = before.employee_name or ""
        name_after = doc.employee_name or ""

        if status_before != status_after:
            if status_after in _INACTIVE_STATUSES:
                _delete_from_all_devices(user_doc, doc)
            elif status_after == "Active" and status_before in _INACTIVE_STATUSES:
                _re_enroll_on_all_devices(user_doc, doc)

        if name_before != name_after and status_after not in _INACTIVE_STATUSES:
            _update_user_info(user_doc, doc)

    # Trigger device sync when attendance_device_id is set or changes
    settings = frappe.get_cached_doc("Attendance Integration Settings")
    if settings.sync_employee_to_devices_on_create:
        device_id_before = (before.get("attendance_device_id") or "").strip()
        device_id_after = (doc.get("attendance_device_id") or "").strip()
        if device_id_after and device_id_before != device_id_after:
            sync_employee_to_devices(doc)


# ---------------------------------------------------------------------------
# Called from attendance_device_user.py when employee link is set
# ---------------------------------------------------------------------------

def on_employee_linked(user_doc) -> None:
    """Sync updated employee name to all devices when user gets linked to employee."""
    _update_user_info(user_doc)


# ---------------------------------------------------------------------------
# Core sync: create/link Device User and push basic info to devices
# ---------------------------------------------------------------------------

def sync_employee_to_devices(employee_doc) -> bool:
    """Create or link Attendance Device User for employee, queue Update User on ZKTeco devices.

    Returns True if any commands were queued.
    """
    device_id = (employee_doc.get("attendance_device_id") or "").strip()
    if not device_id:
        return False

    # Find or create Attendance Device User
    existing_name = frappe.db.get_value("Attendance Device User", {"user_id": device_id})
    if existing_name:
        user_doc = frappe.get_doc("Attendance Device User", existing_name)
        # Link employee if not yet linked
        if not user_doc.employee:
            user_doc.employee = employee_doc.name
            user_doc.employee_name = employee_doc.employee_name
            user_doc.save(ignore_permissions=True)
    else:
        user_doc = frappe.get_doc({
            "doctype": "Attendance Device User",
            "user_id": device_id,
            "employee": employee_doc.name,
            "employee_name": employee_doc.employee_name,
        })
        user_doc.insert(ignore_permissions=True)

    # Queue Update User on all applicable devices.
    # ZKTeco: DATA UPDATE USERINFO (name + PIN, no biometrics needed)
    # EBKN: SET_USER_PROFILE (name + privilege, no biometrics needed)
    company = _employee_company(employee_doc)
    queued = 0
    for dev_id, brand in _get_user_devices(user_doc, company=company).items():
        add_command(dev_id, user_doc.name, brand, "Update User")
        queued += 1
    if queued:
        frappe.db.commit()
    return queued > 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_device_user(employee_name: str) -> Optional[object]:
    doc_name = frappe.db.get_value("Attendance Device User", {"employee": employee_name})
    if not doc_name:
        return None
    return frappe.get_doc("Attendance Device User", doc_name)


def _employee_company(employee_doc) -> Optional[str]:
    """Return employee's company if devices_are_company_specific is on, else None."""
    settings = frappe.get_cached_doc("Attendance Integration Settings")
    if settings.devices_are_company_specific:
        return employee_doc.get("company")
    return None


def _get_user_devices(user_doc, company: Optional[str] = None) -> dict:
    """Return {device_id: brand} for all active devices this user should be on.

    If company is given, only devices belonging to that company are included.
    """
    if user_doc.allow_in_all_devices:
        filters = {"disabled": 0}
        if company:
            filters["company"] = company
        devices = frappe.get_all("Attendance Device", filters=filters, fields=["name", "brand"])
        return {d.name: d.brand for d in devices}

    result = {}
    for row in user_doc.get("devices", []):
        if not row.attendance_device:
            continue
        if company:
            dev_company = frappe.db.get_value("Attendance Device", row.attendance_device, "company")
            if dev_company != company:
                continue
        result[row.attendance_device] = row.brand
    return result


def _delete_from_all_devices(user_doc, employee_doc=None) -> None:
    company = _employee_company(employee_doc) if employee_doc else None
    for device_id, brand in _get_user_devices(user_doc, company=company).items():
        add_command(device_id, user_doc.name, brand, "Delete User")
    frappe.db.commit()


def _re_enroll_on_all_devices(user_doc, employee_doc=None) -> None:
    company = _employee_company(employee_doc) if employee_doc else None
    for device_id, brand in _get_user_devices(user_doc, company=company).items():
        blob_field = _BRAND_BLOB_FIELD.get(brand, "")
        if blob_field and user_doc.get(blob_field):
            add_command(device_id, user_doc.name, brand, "Enroll User")
    frappe.db.commit()


def _update_user_info(user_doc, employee_doc=None) -> None:
    """Queue Update User on all devices (ZKTeco: USERINFO, EBKN: SET_USER_PROFILE)."""
    company = _employee_company(employee_doc) if employee_doc else None
    for device_id, brand in _get_user_devices(user_doc, company=company).items():
        add_command(device_id, user_doc.name, brand, "Update User")
    frappe.db.commit()
