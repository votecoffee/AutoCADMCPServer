import hashlib
import json
import os
import sys
from types import ModuleType, SimpleNamespace

import pytest

from autocad_mcp.autocad import highlight, highlight_document, run_worker


class Entity:
    Handle = "AB"
    ObjectName = "AcDbBlockReference"

    def Highlight(self, enabled):
        self.enabled = enabled

    def Update(self):
        self.updated = True


class Document:
    Saved = True
    modified = 0

    def __init__(self, path):
        self.FullName = str(path)
        self.entity = Entity()
        self.activated = False

    def GetVariable(self, name):
        assert name == "DBMOD"
        return self.modified

    def HandleToObject(self, handle):
        return self.entity

    def Activate(self):
        self.activated = True


def test_highlight_policy_and_receipt(tmp_path):
    path = tmp_path / "drawing.dwg"
    doc = Document(path)
    result = highlight_document(SimpleNamespace(Documents=[doc]), str(path), "AB", True, "INSERT")
    assert result["status"] == "COM_call_completed" and not result["display_verified"]
    assert doc.entity.enabled and doc.entity.updated and doc.activated
    highlight_document(SimpleNamespace(Documents=[doc]), str(path), "AB", False, "INSERT")
    assert not doc.entity.enabled


@pytest.mark.parametrize("condition", ["unsaved", "dbmod", "path", "type", "handle"])
def test_rejections_happen_before_ui_mutation(tmp_path, condition):
    path = tmp_path / "drawing.dwg"
    doc = Document(path)
    if condition == "unsaved":
        doc.Saved = False
    elif condition == "dbmod":
        doc.modified = 1
    elif condition == "path":
        doc.FullName = str(tmp_path / "other.dwg")
    elif condition == "type":
        doc.entity.ObjectName = "AcDbLine"
    else:
        doc.entity.Handle = "FF"
    with pytest.raises(ValueError):
        highlight_document(SimpleNamespace(Documents=[doc]), str(path), "AB", True, "INSERT")
    assert not doc.activated and not hasattr(doc.entity, "enabled")


def test_unbound_evidence_rejected_without_native_access():
    with pytest.raises(ValueError, match="bound drawing hash"):
        highlight(None, {"drawing": None, "object_handle": "AB"})


def test_display_failure_after_highlight_is_unknown_and_does_not_claim_rollback(tmp_path):
    path = tmp_path / "drawing.dwg"
    doc = Document(path)

    def failed_update():
        raise RuntimeError("Synthetic failure after a possible display effect")

    doc.entity.Update = failed_update
    result = highlight_document(SimpleNamespace(Documents=[doc]), str(path), "AB", True, "INSERT")
    assert result["status"] == "unknown" and doc.entity.enabled
    assert not result["drawing_saved"] and not result["display_verified"]


@pytest.mark.skipif(os.name != "nt", reason="Windows-only attachment policy with stubbed COM APIs")
@pytest.mark.parametrize("dirty", [False, True])
def test_worker_releases_attachment_without_closing_or_saving_user_app(tmp_path, monkeypatch, dirty):
    path = tmp_path / "drawing.dwg"
    path.write_bytes(b"Synthetic drawing hash fixture; no CAD runtime")
    doc = Document(path)
    doc.modified = int(dirty)
    effects = []
    doc.Close = lambda *args: effects.append("Close")
    doc.Save = lambda *args: effects.append("Save")
    application = SimpleNamespace(Documents=[doc], Quit=lambda: effects.append("Quit"))
    client = ModuleType("win32com.client")
    client.GetActiveObject = lambda name: application
    package = ModuleType("win32com")
    package.client = client
    monkeypatch.setitem(sys.modules, "win32com", package)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setitem(
        sys.modules,
        "pythoncom",
        SimpleNamespace(
            CoInitialize=lambda: effects.append("CoInitialize"),
            CoUninitialize=lambda: effects.append("CoUninitialize"),
        ),
    )
    request, response = tmp_path / "request.json", tmp_path / "response.json"
    request.write_text(
        json.dumps(
            {
                "filename": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "handle": "AB",
                "enabled": True,
                "expected_type": "INSERT",
            }
        )
    )
    run_worker(request, response)
    result = json.loads(response.read_bytes())
    assert result["status"] == ("failed" if dirty else "COM_call_completed")
    assert result["resource_ownership"]["application"] == "attached_user_owned"
    assert not result["resource_ownership"]["application_close_requested"]
    assert effects == ["CoInitialize", "CoUninitialize"]
    assert doc.modified == int(dirty)
