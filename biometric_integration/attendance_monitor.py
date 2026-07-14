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
                expected_punches: Optional[int] = 4, mode: str = "pairs") -> dict:
    """Turn one employee-day's raw punches into work/break seconds + segments.

    mode:
      "pairs"      — 4-scan model: work = sum of IN->OUT pairs, break = the
                     gaps between pairs (VGH construction crew).
      "span"       — first-in / last-out: work = last - first, no break
                     tracking (e.g. Vincitool, contract-hours style).

    Returns:
        {
          "scans":   [datetime, ...]            # deduped, ordered
          "work_seconds":  int,
          "break_seconds": int,
          "segments": [{"type": "work"|"break"|"unknown", "start": dt, "end": dt}, ...],
          "complete": bool,
          "flag": None | "missing_punch" | "unexpected_count",
        }
    """
    scans = dedup_punches(times, window_seconds)
    n = len(scans)

    if mode == "span":
        if n == 0:
            return {"scans": [], "work_seconds": 0, "break_seconds": 0,
                    "segments": [], "complete": False, "flag": None}
        work = int((scans[-1] - scans[0]).total_seconds())
        return {
            "scans": scans,
            "work_seconds": work,
            "break_seconds": 0,
            "segments": [{"type": "work", "start": scans[0], "end": scans[-1]}] if n >= 2 else [],
            "complete": n >= 2,
            "flag": None if n >= 2 else "missing_punch",
        }

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
from frappe.utils import getdate, get_datetime, cint

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
def get_monitor_config() -> dict:
    """UI bootstrap: what the current user may do + how the page behaves."""
    _guard()
    return {
        "can_correct": _corrections_enabled(),
        "companies": get_monitor_companies(),
    }


def _corrections_enabled() -> bool:
    return bool(cint(frappe.db.get_single_value(
        "Attendance Integration Settings", "allow_checkin_corrections")))


def _assert_corrections_enabled():
    if not _corrections_enabled():
        frappe.throw(frappe._("Check-in corrections are disabled for this site."),
                     frappe.PermissionError)


def _run_processor(employee: str, day):
    """Invoke the configured attendance-processor Server Script for one
    employee-day, if one is set. Blank → rely on Frappe's native Shift Type
    auto-attendance (or nothing). The script receives a `doc` (Employee Checkin)
    carrying the employee + the day to rebuild."""
    script = frappe.db.get_single_value("Attendance Integration Settings", "attendance_processor")
    if not script:
        return
    stub = frappe.new_doc("Employee Checkin")
    stub.employee = employee
    stub.time = f"{getdate(day)} 12:00:00"
    frappe.get_doc("Server Script", script).execute_doc(stub)


def _release_day_lock(employee: str, day):
    """Cancel + remove the day's Attendance and unlink its check-ins, so an edit
    or delete isn't blocked by 'attendance record is linked to this checkin'.
    The processor rebuilds a fresh Attendance afterwards.

    Messages are muted: HRMS emits an 'Unlinked Attendance record from Employee
    Checkins' msgprint on cancel, which would otherwise pop a modal on every
    correction.
    """
    day = getdate(day)
    prev_mute = frappe.flags.mute_messages
    frappe.flags.mute_messages = True
    try:
        for a in frappe.get_all("Attendance",
                                filters={"employee": employee, "attendance_date": day,
                                         "docstatus": ["!=", 2]},
                                fields=["name", "docstatus"]):
            # preserve HR-set leave/holiday/half-day days — only clear worked ones
            status = frappe.db.get_value("Attendance", a.name, "status")
            if status not in ("Present", "Absent", None, ""):
                continue
            if a.docstatus == 1:
                frappe.get_doc("Attendance", a.name).cancel()
            frappe.delete_doc("Attendance", a.name, force=True, ignore_permissions=True)
        # unlink the day's check-ins
        for c in frappe.get_all("Employee Checkin",
                                filters={"employee": employee,
                                         "time": ["between", [f"{day} 00:00:00", f"{day} 23:59:59"]],
                                         "attendance": ["is", "set"]},
                                pluck="name"):
            frappe.db.set_value("Employee Checkin", c, "attendance", None, update_modified=False)
    finally:
        frappe.flags.mute_messages = prev_mute


@frappe.whitelist()
def get_attendance_monitor(from_date, to_date=None, company="VGH B.V.",
                           window_seconds=180, expected_punches=4,
                           include_absent=0, mode=None):
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
                          fields=["name", "employee_name", "department", "default_shift"])
    emp_names = {e.name: e.employee_name for e in emps}
    emp_dept = {e.name: (e.department or "") for e in emps}
    emp_default_shift = {e.name: e.default_shift for e in emps}
    if not emp_names:
        return []

    mode_of = _shift_mode_resolver(list(emp_names), emp_default_shift, from_date, to_date)

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
        row_mode = mode or mode_of(emp, day)
        res = compute_day(times, window_seconds, expected_punches, mode=row_mode)
        out.append({
            "employee": emp,
            "employee_name": emp_names.get(emp, emp),
            "department": emp_dept.get(emp, ""),
            "date": str(day),
            "mode": row_mode,
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
        leave_map = _leaves_on(list(emp_names), from_date)
        for emp in sorted(set(emp_names) - scanned, key=lambda e: emp_names.get(e, e)):
            leave = leave_map.get(emp)
            out.append({
                "employee": emp,
                "employee_name": emp_names.get(emp, emp),
                "department": emp_dept.get(emp, ""),
                "date": str(from_date),
                "mode": mode or mode_of(emp, from_date),
                "scans": [],
                "checkins": [],
                "work_hours": 0.0,
                "break_hours": 0.0,
                "segments": [],
                "complete": False,
                "flag": "on_leave" if leave else "no_punches",
                "leave_type": leave,
            })

    # Holiday label is the same for the whole company/day — stamp it on every
    # row so the UI can show one banner (only meaningful on a single-day view).
    holiday = _holiday_on(company, from_date) if from_date == to_date else None
    if holiday:
        for r in out:
            r["holiday"] = holiday
    return out


def _shift_mode_resolver(employees: list[str], emp_default_shift: dict, from_date, to_date):
    """Build a fast `mode_of(employee, day) -> "pairs"|"span"` closure.

    An employee's attendance mode follows their Shift Type's native
    "Working Hours Calculation Based On" field:
      "First Check-in and Last Check-out"    → span  (whole first->last, no break)
      "Every Valid Check-in and Check-out"   → pairs (sum of IN->OUT pairs)
    The shift for a day is the active Shift Assignment covering it, else the
    employee's default shift. No shift / blank field → pairs (safe default).
    """
    shift_mode: dict = {}
    for st in frappe.get_all("Shift Type", fields=["name", "working_hours_calculation_based_on"]):
        shift_mode[st.name] = ("span" if st.working_hours_calculation_based_on
                               == "First Check-in and Last Check-out" else "pairs")

    assigns = frappe.get_all(
        "Shift Assignment",
        filters={"employee": ["in", employees], "docstatus": 1, "status": "Active",
                 "start_date": ["<=", to_date]},
        fields=["employee", "shift_type", "start_date", "end_date"],
        order_by="start_date asc",
    ) if employees else []
    by_emp: dict = {}
    for a in assigns:
        by_emp.setdefault(a.employee, []).append(a)

    def mode_of(emp, day):
        shift = None
        for a in by_emp.get(emp, []):
            if a.start_date <= day and (not a.end_date or a.end_date >= day):
                shift = a.shift_type  # last match wins → most recent covering assignment
        shift = shift or emp_default_shift.get(emp)
        return shift_mode.get(shift, "pairs")

    return mode_of


def _leaves_on(employees: list[str], day) -> dict:
    """{employee: leave_type} for approved Leave Applications covering `day`."""
    if not employees:
        return {}
    rows = frappe.get_all(
        "Leave Application",
        filters={"employee": ["in", employees], "status": "Approved",
                 "from_date": ["<=", day], "to_date": [">=", day]},
        fields=["employee", "leave_type"],
    )
    return {r.employee: r.leave_type for r in rows}


def _holiday_on(company: str, day):
    """Holiday description if `day` is a holiday in the company's default list."""
    hl = frappe.db.get_value("Company", company, "default_holiday_list")
    if not hl:
        return None
    return frappe.db.get_value("Holiday", {"parent": hl, "holiday_date": day}, "description")


@frappe.whitelist()
def add_checkin(employee, time, device_id=None):
    """Supervisor quick-correction: add a missing punch.

    The insert fires Employee Checkin's After-Insert events (incl. a processor
    bound there), so no extra processor call is needed here.
    """
    _guard()
    _assert_corrections_enabled()
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
    """Supervisor quick-correction: move a punch to the correct time.

    Uses the doc API (not db.set_value) so validation + doc_events fire. The
    day's Attendance is released first (so the edit isn't blocked by a linked
    submitted Attendance), then the processor rebuilds it from the new punches.
    """
    _guard()
    _assert_corrections_enabled()
    row = frappe.db.get_value("Employee Checkin", name, ["employee", "time"], as_dict=True)
    _check_employee(row.employee)
    employee = row.employee
    old_day = getdate(row.time)
    new_dt = get_datetime(time)
    new_day = getdate(new_dt)

    # Release the day's Attendance + unlink its check-ins FIRST, then load the
    # checkin fresh so its `attendance` link is already cleared (a stale link to
    # a just-deleted Attendance would fail save's link validation).
    _release_day_lock(employee, old_day)
    if new_day != old_day:
        _release_day_lock(employee, new_day)

    doc = frappe.get_doc("Employee Checkin", name)
    doc.time = new_dt
    doc.save(ignore_permissions=True)
    frappe.db.commit()

    _run_processor(employee, new_day)
    if new_day != old_day:
        _run_processor(employee, old_day)
    frappe.db.commit()
    return True


@frappe.whitelist()
def delete_checkin(name):
    """Supervisor quick-correction: remove a stray/duplicate punch."""
    _guard()
    _assert_corrections_enabled()
    doc = frappe.get_doc("Employee Checkin", name)
    _check_employee(doc.employee)
    employee = doc.employee
    day = getdate(doc.time)

    _release_day_lock(employee, day)
    frappe.delete_doc("Employee Checkin", name, ignore_permissions=True)
    frappe.db.commit()

    _run_processor(employee, day)
    frappe.db.commit()
    return True
