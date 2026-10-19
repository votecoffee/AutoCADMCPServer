from types import SimpleNamespace

import pytest

from autocad_mcp.autocad import highlight, highlight_document


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
