# Copyright (c) 2026, Khaled Bin Amir
# SPDX-License-Identifier: MIT

"""
Attendance Monitor — net-time-on-site computation from raw biometric punches.

The devices stamp an unreliable IN/OUT flag (status 255 on every scan), so we
never trust it. Instead we pair a day's punches by CHRONOLOGICAL ORDER:

    scan 1 = IN  (arrival)
    scan 2 = OUT (break start)
    scan 3 = IN  (break end)
    scan 4 = OUT (departure)

Work time  = sum of each IN->OUT pair (odd->even), i.e. (s2-s1)+(s4-s3).
Break time = the OUT->IN gaps between pairs (even->odd), excluded from work.

Repeat scans within a short window (double-taps / double reads) collapse to the
first punch of the burst. An odd punch count means a missed scan -> the day is
flagged for supervisor correction rather than silently miscomputed.

These are pure helpers (no Frappe dependency) so they are unit-testable and are
reused by both the monitoring API here and the Shift-Type attendance engine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


def dedup_punches(times: list[datetime], window_seconds: int = 180) -> list[datetime]:
    """Sort ascending and drop any punch within `window_seconds` of the last kept
    one (collapses double-taps / double reads to the first of the burst)."""
    kept: list[datetime] = []
    for t in sorted(times):
        if not kept or (t - kept[-1]).total_seconds() >= window_seconds:
            kept.append(t)
    return kept


def compute_day(times: list[datetime], window_seconds: int = 180,
                expected_punches: Optional[int] = 4) -> dict:
    """Turn one employee-day's raw punches into work/break seconds + segments.

    Returns:
        {
          "scans":   [datetime, ...]            # deduped, ordered
          "work_seconds":  int,
          "break_seconds": int,
          "segments": [{"type": "work"|"break", "start": dt, "end": dt}, ...],
          "complete": bool,                      # even count (all pairs closed)
          "flag": None | "missing_punch" | "unexpected_count",
        }
    """
    scans = dedup_punches(times, window_seconds)
    n = len(scans)
    segments: list[dict] = []
    work = 0
    brk = 0

    # Pair (IN, OUT) = (scans[0],scans[1]), (scans[2],scans[3]), ...
    i = 0
    while i + 1 < n:
        start, end = scans[i], scans[i + 1]
        work += int((end - start).total_seconds())
        segments.append({"type": "work", "start": start, "end": end})
        # break = gap to the next IN, if there is another pair
        if i + 3 < n:
            b_start, b_end = scans[i + 1], scans[i + 2]
            brk += int((b_end - b_start).total_seconds())
            segments.append({"type": "break", "start": b_start, "end": b_end})
        i += 2

    # Odd count: the trailing punch can't be paired — the stretch leading up to
    # it is unclassifiable (was it work or break?). Surface it as "unknown" so
    # the UI shows an honest gray gap instead of clean background.
    if n >= 3 and n % 2 == 1:
        segments.append({"type": "unknown", "start": scans[-2], "end": scans[-1]})

    complete = (n % 2 == 0) and n > 0
    flag = None
    if n == 0:
        flag = None
    elif n % 2 == 1:
        flag = "missing_punch"          # odd -> a scan was missed
    elif expected_punches and n != expected_punches:
        flag = "unexpected_count"       # e.g. only 2 on a 4-punch policy

    return {
        "scans": scans,
        "work_seconds": work,
        "break_seconds": brk,
        "segments": segments,
        "complete": complete,
        "flag": flag,
    }


def _h(seconds: int) -> float:
    return round(seconds / 3600.0, 2)


# ---------------------------------------------------------------------------
# Whitelisted API (consumed by the desk Vue page now, a mobile view later)
# ---------------------------------------------------------------------------

import frappe
from frappe.utils import getdate, get_datetime

_ALLOWED_ROLES = ("Site Supervisor", "HR User", "HR Manager", "System Manager")


def _guard():
    if not set(_ALLOWED_ROLES) & set(frappe.get_roles()):
        frappe.throw(frappe._("Not permitted"), frappe.PermissionError)


def _permitted_companies() -> list[str] | None:
    """Companies the session user is restricted to via User Permission.

    Returns None when unrestricted (no Company User Permissions), else the list.
    """
    rows = frappe.get_all(
        "User Permission",
        filters={"user": frappe.session.user, "allow": "Company"},
        pluck="for_value",
    )
    return rows or None


def _check_company(company: str) -> None:
    allowed = _permitted_companies()
    if allowed is not None and company not in allowed:
        frappe.throw(frappe._("Not permitted for company {0}").format(company),
                     frappe.PermissionError)


def _check_employee(employee: str) -> None:
    """Corrections may only touch employees of a permitted company."""
    company = frappe.db.get_value("Employee", employee, "company")
    _check_company(company)


@frappe.whitelist()
def get_monitor_companies() -> list[str]:
    """Companies selectable in the monitor: the user's permitted list, or all."""
    _guard()
    allowed = _permitted_companies()
    if allowed is not None:
        return allowed
    return frappe.get_all("Company", pluck="name", order_by="name")


@frappe.whitelist()
def get_attendance_monitor(from_date, to_date=None, company="VGH B.V.",
                           window_seconds=180, expected_punches=4,
                           include_absent=0):
    """Per employee-per-day net-time-on-site for a company's crew.

    Returns rows: {employee, employee_name, date, scans[iso], work_hours,
    break_hours, complete, flag, checkins:[{name,time}]}. Scoped by company
    (User Permission on Company further limits what the caller can see).

    include_absent: on a single-day query, also return a row (empty scans,
    flag "no_scans") for every active employee without a punch that day, so
    supervisors see who did not show up.
    """
    _guard()
    _check_company(company)
    from_date = getdate(from_date)
    to_date = getdate(to_date or from_date)
    window_seconds = int(window_seconds)
    expected_punches = int(expected_punches) if expected_punches else None
    include_absent = int(include_absent or 0) and from_date == to_date

    emps = frappe.get_all("Employee", filters={"company": company, "status": "Active"},
                          fields=["name", "employee_name"])
    emp_names = {e.name: e.employee_name for e in emps}
    if not emp_names:
        return []

    rows = frappe.get_all(
        "Employee Checkin",
        filters={"employee": ["in", list(emp_names)],
                 "time": ["between", [f"{from_date} 00:00:00", f"{to_date} 23:59:59"]]},
        fields=["name", "employee", "time"],
        order_by="time asc",
    )
    # group by (employee, date)
    buckets: dict = {}
    for r in rows:
        d = get_datetime(r.time)
        buckets.setdefault((r.employee, d.date()), []).append((r.name, d))

    out = []
    for (emp, day), items in sorted(buckets.items(), key=lambda x: (emp_names.get(x[0][0], ""), x[0][1])):
        times = [t for _, t in items]
        res = compute_day(times, window_seconds, expected_punches)
        out.append({
            "employee": emp,
            "employee_name": emp_names.get(emp, emp),
            "date": str(day),
            "scans": [t.isoformat() for t in res["scans"]],
            "checkins": [{"name": nm, "time": t.isoformat()} for nm, t in sorted(items, key=lambda x: x[1])],
            "work_hours": _h(res["work_seconds"]),
            "break_hours": _h(res["break_seconds"]),
            "segments": [{"type": s["type"], "start": s["start"].isoformat(), "end": s["end"].isoformat()}
                         for s in res["segments"]],
            "complete": res["complete"],
            "flag": res["flag"],
        })

    if include_absent:
        scanned = {emp for (emp, _day) in buckets}
        for emp in sorted(set(emp_names) - scanned, key=lambda e: emp_names.get(e, e)):
            out.append({
                "employee": emp,
                "employee_name": emp_names.get(emp, emp),
                "date": str(from_date),
                "scans": [],
                "checkins": [],
                "work_hours": 0.0,
                "break_hours": 0.0,
                "segments": [],
                "complete": False,
                "flag": "no_scans",
            })
    return out


@frappe.whitelist()
def add_checkin(employee, time, device_id=None):
    """Supervisor quick-correction: add a missing punch."""
    _guard()
    _check_employee(employee)
    doc = frappe.new_doc("Employee Checkin")
    doc.employee = employee
    doc.time = get_datetime(time)
    if device_id:
        doc.device_id = device_id
    doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return doc.name


@frappe.whitelist()
def update_checkin(name, time):
    """Supervisor quick-correction: move a punch to the correct time."""
    _guard()
    _check_employee(frappe.db.get_value("Employee Checkin", name, "employee"))
    frappe.db.set_value("Employee Checkin", name, "time", get_datetime(time))
    frappe.db.commit()
    return True


@frappe.whitelist()
def delete_checkin(name):
    """Supervisor quick-correction: remove a stray/duplicate punch."""
    _guard()
    _check_employee(frappe.db.get_value("Employee Checkin", name, "employee"))
    frappe.delete_doc("Employee Checkin", name, ignore_permissions=True)
    frappe.db.commit()
    return True
