"""Create the checkout-local Windows application shortcut with the bundled icon."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path


def create_shortcut() -> dict:
    if os.name != "nt":
        raise ValueError("Application shortcuts require Windows")
    import win32com.client

    repo = Path(__file__).resolve().parents[1]
    target = (repo / "InstallAndRun.cmd").resolve(strict=True)
    icon = (repo / "assets" / "autocad.ico").resolve(strict=True)
    destination = repo / "AutoCAD MCP Server.lnk"
    shell = win32com.client.Dispatch("WScript.Shell")
    if destination.exists():
        existing = shell.CreateShortcut(str(destination))
        if Path(existing.TargetPath).resolve() != target or existing.Arguments:
            raise ValueError("Existing AutoCAD MCP Server.lnk has a different target or arguments; preserved")
    temporary = repo / (".autocad-shortcut-" + uuid.uuid4().hex + ".lnk")
    try:
        shortcut = shell.CreateShortcut(str(temporary))
        shortcut.TargetPath = str(target)
        shortcut.WorkingDirectory = str(repo)
        shortcut.Arguments = ""
        shortcut.Description = "Install and run AutoCAD MCP Server"
        shortcut.IconLocation = str(icon) + ",0"
        shortcut.WindowStyle = 1
        shortcut.Save()
        check = shell.CreateShortcut(str(temporary))
        icon_path, index = check.IconLocation.rsplit(",", 1)
        if (
            Path(check.TargetPath).resolve() != target
            or check.Arguments
            or Path(check.WorkingDirectory).resolve() != repo
            or Path(icon_path).resolve() != icon
            or index != "0"
        ):
            raise ValueError("Application shortcut readback failed")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"shortcut": str(destination), "icon": str(icon), "readback_verified": True}


if __name__ == "__main__":
    print(json.dumps(create_shortcut()))
