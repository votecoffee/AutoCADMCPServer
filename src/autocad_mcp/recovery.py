"""Retire only proved-dead private claims; never stops processes or replays domain work."""

import ctypes
import re
from ctypes import wintypes as w

LABEL = re.compile(r"AutoCAD (?:extraction|render|pdf-tables|tables|codex-inventory) ([0-9a-f]{32})\Z")


def empty_private_job(token):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenJobObjectW.argtypes, kernel.OpenJobObjectW.restype = [w.DWORD, w.BOOL, w.LPCWSTR], w.HANDLE
    kernel.QueryInformationJobObject.argtypes = [
        w.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        w.DWORD,
        ctypes.c_void_p,
    ]
    kernel.QueryInformationJobObject.restype = w.BOOL
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
    handle = kernel.OpenJobObjectW(4, False, "Local\\AutoCADMCP-" + token)
    if not handle:
        code = ctypes.get_last_error()
        if code == 2:
            return "named_private_job_absent"
        raise ctypes.WinError(code)
    try:
        # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION has four LARGE_INTEGER values,
        # then four DWORD counts; ActiveProcesses is the third DWORD.
        class Accounting(ctypes.Structure):
            _fields_ = [
                ("times", ctypes.c_longlong * 4),
                ("faults", w.DWORD),
                ("total", w.DWORD),
                ("active", w.DWORD),
                ("terminated", w.DWORD),
            ]

        value = Accounting()
        if not kernel.QueryInformationJobObject(handle, 1, ctypes.byref(value), ctypes.sizeof(value), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return "named_private_job_empty" if value.active == 0 else None
    finally:
        # A query handle must never become a surviving owner of the job.
        kernel.CloseHandle(handle)


def reconcile_dead_claims(owner, *, job_probe=empty_private_job, maximum=128):
    ledger, driver = owner.ledger, owner.ledger.driver
    summary = {
        "examined": 0,
        "retired": [],
        "preserved": 0,
        "errors": 0,
        "policy": "Metadata-only retirement after exact dead owner/root/members and absent/empty named private job; journals and live peers preserved",
    }
    candidates = [
        row
        for row in ledger.records()
        if row.app_id == "autocad" and row.state not in {"released", "terminated", "failed"}
    ]
    for record in candidates[:maximum]:
        summary["examined"] += 1
        match = LABEL.fullmatch(record.label)
        if (
            record.state != "active"
            or record.ownership != "private"
            or record.cleanup_mode != "terminate"
            or record.containment != "windows_job"
            or record.process is None
            or record.receipt is not None
            or record.recovery_barrier
            or record.reconciliation is not None
            or not match
        ):
            summary["preserved"] += 1
            continue
        try:
            identities = [record.owner, record.process, *record.members]
            if any(
                driver.state(value.model_dump(mode="json")) not in {"absent", "different"}
                for value in identities
            ):
                summary["preserved"] += 1
                continue
            proof = job_probe(match[1])
            if not proof:
                summary["preserved"] += 1
                continue
            # ResourceOwner performs its own locked full-generation/revision recheck.
            updated = owner.reconcile(
                record.resource_id,
                record.revision,
                "Offline private claim: exact owner/root/recorded members absent or replaced; "
                + proof
                + "; no process stop, domain replay, journal reset or barrier clearance",
            )
            summary["retired"].append(updated.resource_id)
        except (OSError, ValueError):
            summary["errors"] += 1
            summary["preserved"] += 1
    summary["remaining_outside_scan"] = max(0, len(candidates) - maximum)
    return summary
