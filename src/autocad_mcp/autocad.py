"""Bounded, display-only highlighting of an already-open, unchanged AutoCAD drawing."""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from .owned_process import run_owned
from .service import sha256
from .worker_launch import worker_command


def highlight_document(application, filename: str, handle: str, enabled: bool, expected_type: str):
    """COM policy kept separate so rejection paths can be tested without AutoCAD."""
    target = Path(filename).resolve()
    matches = [doc for doc in application.Documents if Path(doc.FullName).resolve() == target]
    if len(matches) != 1:
        raise ValueError("The exact source drawing must already be open in AutoCAD")
    document = matches[0]
    if not document.Saved or int(document.GetVariable("DBMOD")) != 0:
        raise ValueError("Open drawing has unsaved changes; highlighting requires the unchanged source")
    entity = document.HandleToObject(handle)
    if str(entity.Handle).casefold() != handle.casefold():
        raise ValueError("AutoCAD returned a different object handle")
    expected_names = {
        "INSERT": "AcDbBlockReference",
        "LINE": "AcDbLine",
        "TEXT": "AcDbText",
        "MTEXT": "AcDbMText",
    }
    if expected_type in expected_names and entity.ObjectName != expected_names[expected_type]:
        raise ValueError("Object type differs from extracted evidence")
    outcome = {"status": "COM_call_completed"}
    try:
        document.Activate()
        entity.Highlight(enabled)
        entity.Update()
    except Exception:
        outcome = {
            "status": "unknown",
            "error": "Display operation did not confirm completion; inspect AutoCAD before retrying",
        }
    return {
        **outcome,
        "object_handle": handle,
        "enabled": enabled,
        "object_name": str(entity.ObjectName),
        "scope": "exact top-level object",
        "display_verified": False,
        "drawing_saved": False,
    }


def run_worker(request_file, response_file):
    request = json.loads(Path(request_file).read_text(encoding="utf-8"))
    try:
        if os.name != "nt":
            raise ValueError("AutoCAD ActiveX highlighting requires Windows")
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        application = None
        try:
            # GetActiveObject never starts AutoCAD or opens a drawing.
            application = win32com.client.GetActiveObject("AutoCAD.Application")
            if sha256(Path(request["filename"])) != request["sha256"]:
                raise ValueError("Source changed before highlighting")
            result = highlight_document(
                application,
                request["filename"],
                request["handle"],
                request["enabled"],
                request["expected_type"],
            )
        finally:
            # The attachment is user-owned. Release our COM reference without
            # Quit/Close/save, including on failure or dirty-state refusal.
            application = None
            pythoncom.CoUninitialize()
    except Exception as error:
        result = {"status": "failed", "error": f"{type(error).__name__}: {error}"}
    result["resource_ownership"] = {
        "application": "attached_user_owned",
        "cleanup": "release_COM_references_only",
        "application_close_requested": False,
    }
    Path(response_file).write_text(json.dumps(result), encoding="utf-8", newline="\n")


def highlight(service, source: dict, enabled=True):
    drawing = source.get("drawing") or {}
    if not drawing.get("sha256") or not source.get("object_handle"):
        raise ValueError("Source has no bound drawing hash and object handle")
    path = service.config.resolve(drawing["root_id"], drawing["relative_path"])
    if sha256(path) != drawing["sha256"]:
        raise ValueError("Source snapshot is stale; rebuild before highlighting")
    handle = source["object_handle"]
    if not re.fullmatch(r"[a-fA-F0-9]{1,32}", handle):
        raise ValueError("Invalid AutoCAD object handle")
    if source.get("reference_path") != [handle]:
        raise ValueError(
            "Nested placements cannot be highlighted exactly through ActiveX; use their reference path in AutoCAD"
        )
    doc = service.load(drawing["root_id"], drawing["relative_path"], cached_only=True)
    matches = [
        r
        for r in doc.get("entities", [])
        if r["handle"].casefold() == handle.casefold() and r["layout"] != "@block"
    ]
    if len(matches) != 1:
        raise ValueError("Handle does not identify one extracted top-level object")
    folder = service.config.state / "electrical" / "highlight"
    folder.mkdir(parents=True, exist_ok=True)
    request = folder / (uuid.uuid4().hex + ".request.json")
    response = request.with_suffix(".result.json")
    request.write_text(
        json.dumps(
            {
                "filename": str(path),
                "sha256": drawing["sha256"],
                "handle": handle,
                "expected_type": matches[0]["type"],
                "enabled": enabled,
            }
        ),
        encoding="utf-8",
        newline="\n",
    )
    with service.coordinator.lock("ui:autocad"), service.coordinator.worker():
        try:
            run_owned(
                worker_command("_highlight", str(request), str(response)),
                resource_kind="highlight-helper",
                timeout=30,
                check=True,
            )
            result = json.loads(response.read_text(encoding="utf-8"))
        except Exception:
            result = {
                "status": "unknown",
                "error": "Highlight worker did not confirm completion; inspect AutoCAD before retrying",
            }
    result["source"] = source
    result["audit_path"] = str(response)
    response.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8", newline="\n")
    request.unlink(missing_ok=True)
    return result
