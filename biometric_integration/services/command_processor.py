# Copyright (c) 2026, Khaled Bin Amir
# SPDX-License-Identifier: MIT

"""
Command processor: fetches the next pending Attendance Device Command and builds
the brand-specific payload to return to the polling device.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Optional, Union

import frappe
from frappe.utils import cint, now, now_datetime, get_datetime


def process_device_command(device_sn: str) -> Optional[Union[str, dict]]:
    """Return the next pending command payload for the device, or None if none.

    ZKTeco commands return a string (ADMS protocol lines).
    EBKN commands return a dict with cmd_code/trans_id/body.
    """
    command_name = frappe.db.get_value(
        "Attendance Device Command",
        {"attendance_device": device_sn, "status": "Pending"},
        "name",
        order_by="creation asc",
    )
    if not command_name:
        # Queue drained — clear the sticky "pending command" indicator on the device.
        if frappe.db.get_value("Attendance Device", device_sn, "has_pending_command"):
            frappe.db.set_value("Attendance Device", device_sn, "has_pending_command", 0,
                                update_modified=False)
            frappe.db.commit()
        return None

    cmd_doc = frappe.get_doc("Attendance Device Command", command_name)

    if cmd_doc.command_type == "Restart Device":
        brand = frappe.db.get_value("Attendance Device", device_sn, "brand")
        cmd_doc.status = "Success"
        cmd_doc.closed_on = now_datetime()
        cmd_doc.save(ignore_permissions=True)
        frappe.db.commit()
        if brand == "EBKN":
            return {"trans_id": cmd_doc.name, "cmd_code": "RESET_FK", "body": ""}
        return f"C:{cmd_doc.name}:REBOOT"  # ZKTeco

    if cmd_doc.command_type == "Unlock Door":
        brand = frappe.db.get_value("Attendance Device", device_sn, "brand")
        # Leave as Pending — device will report result via devicecmd (ZKTeco) or
        # send_cmd_result (EBKN), which updates status to Success or Failed.
        cmd_doc.no_of_attempts = (cmd_doc.no_of_attempts or 0) + 1
        cmd_doc.save(ignore_permissions=True)
        frappe.db.commit()
        if brand == "EBKN":
            return {"trans_id": cmd_doc.name, "cmd_code": "OPEN_DOOR", "body": json.dumps({"door_no": 1})}
        return f"C:{cmd_doc.name}:CONTROL DEVICE 1"  # ZKTeco: door relay open

    if cmd_doc.command_type == "Sync User List":
        brand = frappe.db.get_value("Attendance Device", device_sn, "brand")
        cmd_doc.no_of_attempts = (cmd_doc.no_of_attempts or 0) + 1
        cmd_doc.save(ignore_permissions=True)
        frappe.db.commit()
        if brand == "EBKN":
            return {"trans_id": cmd_doc.name, "cmd_code": "GET_USER_ID_LIST", "body": ""}
        # ZKTeco: classic all-users query (widest firmware support — the newer
        # `DATA QUERY tablename=user,...` form is rejected Return=-1004 by classic
        # firmware). The device uploads USER records, ingested by _handle_operlog_user
        # (/iclock/cdata) or _handle_querydata (/iclock/querydata) depending on firmware.
        return f"C:{cmd_doc.name}:DATA QUERY USERINFO"

    if cmd_doc.command_type == "Set Device Time":
        brand = frappe.db.get_value("Attendance Device", device_sn, "brand")
        cmd_doc.no_of_attempts = (cmd_doc.no_of_attempts or 0) + 1
        cmd_doc.save(ignore_permissions=True)
        frappe.db.commit()
        if brand == "EBKN":
            time_str = _ebkn_now_for_device(device_sn)
            return {
                "trans_id": cmd_doc.name,
                "cmd_code": "SET_TIME",
                "body": json.dumps({"time": time_str}),
            }
        # ZKTeco devices sync clock via /iclock/rtdata?type=time on their own
        # cadence — there is no out-of-band SET_TIME equivalent. Mark Success
        # so the user gets feedback instead of a stuck Pending command.
        cmd_doc.status = "Success"
        cmd_doc.closed_on = now_datetime()
        cmd_doc.device_response = (
            "ZKTeco devices auto-sync via /iclock/rtdata; no command sent."
        )
        cmd_doc.save(ignore_permissions=True)
        frappe.db.commit()
        return None

    if cmd_doc.command_type == "Re-pull Attendance":
        # Ask the device to re-upload stored attendance logs for a date range.
        # ZKTeco answers a `DATA QUERY ATTLOG` by POSTing the records to
        # /iclock/cdata?table=ATTLOG, which the normal _process_attlog path ingests
        # (duplicates are rejected by Employee Checkin, so re-pulls are safe).
        # Marked done-on-send so it is emitted exactly once (not re-queried every poll).
        brand = frappe.db.get_value("Attendance Device", device_sn, "brand")
        if brand != "ZKTeco":
            cmd_doc.status = "Failed"
            cmd_doc.closed_on = now_datetime()
            cmd_doc.device_response = "Re-pull Attendance is only supported for ZKTeco devices."
            cmd_doc.save(ignore_permissions=True)
            frappe.db.commit()
            return None
        start_s = (
            get_datetime(cmd_doc.repull_start).strftime("%Y-%m-%d %H:%M:%S")
            if cmd_doc.repull_start else "2000-01-01 00:00:00"
        )
        end_s = (
            get_datetime(cmd_doc.repull_end).strftime("%Y-%m-%d %H:%M:%S")
            if cmd_doc.repull_end else now_datetime().strftime("%Y-%m-%d %H:%M:%S")
        )
        cmd_doc.no_of_attempts = (cmd_doc.no_of_attempts or 0) + 1
        cmd_doc.status = "Success"
        cmd_doc.closed_on = now_datetime()
        cmd_doc.device_response = f"Sent: DATA QUERY ATTLOG StartTime={start_s} EndTime={end_s}"
        cmd_doc.save(ignore_permissions=True)
        frappe.db.commit()
        return f"C:{cmd_doc.name}:DATA QUERY ATTLOG StartTime={start_s}\tEndTime={end_s}"

    try:
        payload = _build_payload(cmd_doc)
        if payload:
            cmd_doc.no_of_attempts = (cmd_doc.no_of_attempts or 0) + 1
            cmd_doc.save(ignore_permissions=True)
            frappe.db.commit()
        return payload
    except Exception as exc:
        _handle_build_failure(cmd_doc, exc)
        return None


def force_close_stale_commands() -> None:
    """Scheduled daily task: mark old uncompleted commands as Failed."""
    settings = frappe.get_cached_doc("Attendance Integration Settings")
    days = cint(settings.force_close_after_days) or 30
    cutoff = frappe.utils.add_to_date(now_datetime(), days=-days)

    stale = frappe.get_all(
        "Attendance Device Command",
        filters={"status": "Pending", "initiated_on": ["<", cutoff]},
        pluck="name",
    )
    for name in stale:
        frappe.db.set_value(
            "Attendance Device Command", name,
            {"status": "Failed", "closed_on": now_datetime()},
            update_modified=False,
        )
    if stale:
        frappe.db.commit()


# ---------------------------------------------------------------------------
# Build logic
# ---------------------------------------------------------------------------

def _build_payload(cmd_doc: Any) -> Optional[Union[str, dict]]:
    user_doc = frappe.get_doc("Attendance Device User", cmd_doc.attendance_device_user)
    brand = cmd_doc.brand
    if brand == "ZKTeco":
        return _zkteco(cmd_doc, user_doc)
    if brand == "EBKN":
        return _ebkn(cmd_doc, user_doc)
    raise ValueError(f"Unsupported brand: {brand}")


def _zkteco(cmd_doc: Any, user_doc: Any) -> Optional[str]:
    cmd_id = cmd_doc.name
    pin = user_doc.user_id
    name = user_doc.employee_name or ""

    if cmd_doc.command_type == "Delete User":
        return f"C:{cmd_id}:DATA DELETE USERINFO PIN={pin}"

    if cmd_doc.command_type == "Get Enroll Data":
        # Classic ADMS dialect — widest firmware support (verified against the live
        # ZKTeco fleet: USERINFO/FPTMP return 0, whereas the newer unified
        # `DATA QUERY tablename=biodata,...` form is rejected with Return=-1004).
        # FPTMP returns each fingerprint as an `FP PIN=.. FID=.. Size=.. TMP=..`
        # record, which carries everything FINGERTMP needs to re-enroll it.
        # Newer multi-modal firmware answers the same queries; if it instead pushes
        # unified `biodata` records, the ingest path (adapters/zkteco.py) parses those.
        return "\n".join([
            f"C:{cmd_id}:DATA QUERY USERINFO PIN={pin}",
            f"C:{cmd_id}:DATA QUERY FPTMP PIN={pin}",
        ])

    if cmd_doc.command_type == "Update User":
        return f"C:{cmd_id}:DATA UPDATE USERINFO\tPIN={pin}\tName={name}\tPri=0\tPasswd=\tCard=0"

    if cmd_doc.command_type == "Enroll User":
        blob = _load_blob(user_doc.zkteco_enroll_data)
        if not blob:
            raise FileNotFoundError(f"ZKTeco enroll data missing for user {user_doc.name}")

        try:
            enroll = json.loads(blob.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            enroll = None

        if enroll and enroll.get("version") == 2:
            # Current format — full JSON with all biometrics + credentials
            card = enroll.get("card", "0")
            passwd = enroll.get("passwd", "")
            # Cross-model guard: a fingerprint template only matches on a device with
            # the same FP algorithm version. If the target device's fp_version is known
            # and differs from a template's majorver, surface it (the device would
            # otherwise silently reject the biodata line with Return=-1).
            target_fp = frappe.db.get_value("Attendance Device", cmd_doc.attendance_device, "fp_version")
            if target_fp:
                for bio in enroll.get("biometrics", []):
                    mv = bio.get("majorver", 0)
                    if bio.get("type") == 1 and mv and int(mv) != int(target_fp):
                        frappe.log_error(
                            title="Biometric Enrollment Algorithm Mismatch",
                            message=(
                                f"User {user_doc.name} (PIN {pin}): fingerprint template "
                                f"majorver={mv} but target device {cmd_doc.attendance_device} "
                                f"fp_version={target_fp}. Template may be rejected — re-enroll "
                                f"the finger directly on this device model."
                            ),
                        )
                        break
            lines = [
                f"C:{cmd_id}:DATA UPDATE USERINFO\tPIN={pin}\tName={name}\tPri=0\tPasswd={passwd}\tCard={card}",
            ]
            for bio in enroll.get("biometrics", []):
                btype = bio.get("type", 1)
                if btype == 1:
                    # Fingerprint — classic FINGERTMP command. Verified Return=0 on
                    # the live fleet; supported by legacy firmware that rejects the
                    # unified `DATA UPDATE biodata` (Return=-1) and by modern FP
                    # firmware (kept for backward compatibility). Needs only
                    # FID/Size/Valid/TMP, all captured by the FPTMP pull.
                    lines.append(
                        f"C:{cmd_id}:DATA UPDATE FINGERTMP"
                        f"\tPIN={pin}"
                        f"\tFID={bio.get('no', 0)}"
                        f"\tSize={bio.get('size', 0)}"
                        f"\tValid={bio.get('valid', 1)}"
                        f"\tTMP={bio['tmp']}"
                    )
                else:
                    # Face / palm / other modalities exist only on newer firmware,
                    # which uses the unified template (lowercase fields + `format`,
                    # 0=ZK; capitalised names or a `Size` field → Return=-1).
                    lines.append(
                        f"C:{cmd_id}:DATA UPDATE biodata"
                        f"\tpin={pin}"
                        f"\tno={bio['no']}"
                        f"\tindex={bio.get('index', 0)}"
                        f"\tvalid={bio.get('valid', 1)}"
                        f"\tduress={bio.get('duress', 0)}"
                        f"\ttype={btype}"
                        f"\tmajorver={bio.get('majorver', 0)}"
                        f"\tminorver={bio.get('minorver', 0)}"
                        f"\tformat={bio.get('format', 0)}"
                        f"\ttmp={bio['tmp']}"
                    )
            return "\n".join(lines)
        elif enroll and "fid" in enroll:
            # Intermediate format — single FP JSON {"fid", "size", "tmp"}
            lines = [
                f"C:{cmd_id}:DATA UPDATE USERINFO\tPIN={pin}\tName={name}\tPri=0\tPasswd=\tCard=0",
                f"C:{cmd_id}:DATA UPDATE BIODATA\tPIN={pin}\tFID={enroll['fid']}\tSize={enroll['size']}\tValid=1\tTMP={enroll['tmp']}",
            ]
            return "\n".join(lines)
        else:
            # Legacy format — raw base64 string, assume single fingerprint FID=0
            tmp = blob.decode("utf-8").strip()
            size = len(base64.b64decode(tmp + "=="))
            return "\n".join([
                f"C:{cmd_id}:DATA UPDATE USERINFO\tPIN={pin}\tName={name}\tPri=0\tPasswd=\tCard=0",
                f"C:{cmd_id}:DATA UPDATE BIODATA\tPIN={pin}\tFID=0\tSize={size}\tValid=1\tTMP={tmp}",
            ])
    return None


def _ebkn(cmd_doc: Any, user_doc: Any) -> Optional[dict]:
    # EBKN user ids are numeric, zero-padded to 8. Attendance Device User is
    # shared with ZKTeco where alphanumeric PINs occur — fail with a clear
    # message instead of an opaque int() ValueError.
    raw_pin = str(user_doc.user_id or "").strip()
    if not raw_pin.isdigit():
        raise ValueError(
            f"EBKN commands need a numeric user id; user {user_doc.name} has {raw_pin!r}"
        )
    uid = raw_pin.zfill(8)

    if cmd_doc.command_type == "Delete User":
        return {
            "trans_id": cmd_doc.name,
            "cmd_code": "DELETE_USER",
            "body": json.dumps({"user_id": uid}),
        }

    if cmd_doc.command_type == "Get Enroll Data":
        return {
            "trans_id": cmd_doc.name,
            "cmd_code": "GET_USER_INFO",
            "body": json.dumps({"user_id": uid}),
        }

    if cmd_doc.command_type == "Update User":
        # SET_USER_PROFILE: name + privilege only, no biometrics required.
        # Registers the user on the device so they can clock in with their PIN.
        # NOTE (needs hardware verification): SET_USER_PROFILE is not in the
        # BS_FkWeb command table — the documented equivalents are SET_USER_NAME
        # ({user_id, user_name}) and SET_USER_PRIVILEGE ({user_id,
        # user_privilege: "USER"|...}). If a device leaves this Pending forever
        # (never sends send_cmd_result), switch to those.
        return {
            "trans_id": cmd_doc.name,
            "cmd_code": "SET_USER_PROFILE",
            "body": json.dumps({"user_id": uid, "user_name": user_doc.employee_name or "", "privilege": 0}),
        }

    if cmd_doc.command_type == "Enroll User":
        blob = _load_blob(user_doc.ebkn_enroll_data)
        if not blob:
            raise FileNotFoundError(f"EBKN enroll data missing for user {user_doc.name}")
        return {"trans_id": cmd_doc.name, "cmd_code": "SET_USER_INFO", "body": blob}

    return None


def _ebkn_now_for_device(device_sn: str) -> str:
    """Return current time as EBKN's YYYYMMDDhhmmss in the device's configured zone.

    Uses Attendance Device.device_timezone if set, else the site timezone. The
    string is a plain wall-clock value — EBKN's SET_TIME has no UTC marker.
    """
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        tz_name = (
            frappe.db.get_value("Attendance Device", device_sn, "device_timezone")
            or frappe.utils.get_system_timezone()
        )
        now_local = datetime.now(ZoneInfo(tz_name))
    except Exception:
        now_local = datetime.now()
    return now_local.strftime("%Y%m%d%H%M%S")


def _load_blob(url: str) -> Optional[bytes]:
    if not url:
        return None
    file_name = frappe.db.get_value("File", {"file_url": url}, "name")
    if not file_name:
        return None
    content = frappe.get_doc("File", file_name).get_content()
    return content if isinstance(content, bytes) else content.encode("utf-8")


def _handle_build_failure(cmd_doc: Any, exc: Exception) -> None:
    try:
        frappe.db.rollback()
        cmd_doc.reload()
        cmd_doc.no_of_attempts = (cmd_doc.no_of_attempts or 0) + 1
        line = f"[{now()}] Build Failed: {exc}"
        cmd_doc.device_response = (
            f"{cmd_doc.device_response}\n{line}" if cmd_doc.device_response else line
        )
        settings = frappe.get_cached_doc("Attendance Integration Settings")
        max_att = cint(settings.maximum_command_attempts) or 3
        if cmd_doc.no_of_attempts >= max_att:
            cmd_doc.status = "Failed"
            cmd_doc.closed_on = now_datetime()
        else:
            cmd_doc.status = "Pending"
        cmd_doc.save(ignore_permissions=True)
        frappe.db.commit()
        frappe.log_error(
            title="Command Build Failed",
            message=frappe.get_traceback(),
            reference_doctype="Attendance Device Command",
            reference_name=cmd_doc.name,
        )
    except Exception as inner:
        frappe.db.rollback()
        frappe.log_error(title="Command Error Handler Failed", message=str(inner))
