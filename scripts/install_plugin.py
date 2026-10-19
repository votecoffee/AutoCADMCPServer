"""Prepare an independent app-owned Codex plugin with private local runtime bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

FILES = (
    "plugin.json",
    "mcp.json",
    ".mcp.json",
    ".codex-plugin/plugin.json",
    "assets/icon.png",
    "skills/drawing-analysis/SKILL.md",
)


def prepare(repo: Path):
    repo = repo.resolve()
    template = repo / "plugins" / "autocad"
    config = (repo / ".local" / "config.json").resolve(strict=True)
    python = repo / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.is_file():
        raise ValueError("Run InstallAndRun.cmd --install-only first")
    from autocad_mcp.config import Config

    Config.load(config)
    server = {
        "type": "stdio",
        "command": str(python),
        "args": ["-m", "autocad_mcp", "--config", str(config), "serve"],
        "cwd": str(repo),
    }
    portable = {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        "mcpServers": {"autocad": server},
    }
    legacy = {"mcpServers": {"autocad": server}}
    contents = {name: (template / name).read_bytes() for name in FILES}
    contents["mcp.json"] = (json.dumps(portable, indent=2) + "\n").encode()
    contents[".mcp.json"] = (json.dumps(legacy, indent=2) + "\n").encode()
    digest = hashlib.sha256(
        b"".join(name.encode() + b"\0" + contents[name] for name in sorted(contents))
    ).hexdigest()[:16]
    root = repo / ".local" / "codex-marketplace"
    package = root / "packages" / ("autocad-" + digest)
    for name, data in contents.items():
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != data:
            raise ValueError("Immutable plugin package identity conflict")
        if not path.exists():
            path.write_bytes(data)
    marketplace = {
        "name": "autocad-local",
        "interface": {"displayName": "AutoCAD MCP Server Local"},
        "plugins": [
            {
                "name": "autocad",
                "source": {"source": "local", "path": "./" + package.relative_to(root).as_posix()},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }
        ],
    }
    target = root / ".agents" / "plugins" / "marketplace.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    from autocad_mcp.electrical import atomic_json

    atomic_json(target, marketplace)
    return {
        "marketplace": str(root),
        "package": str(package),
        "plugin": "autocad@autocad-local",
        "transport": "stdio",
        "broker_required": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepare-only", action="store_true", help="Prepare local bindings without registering in Codex"
    )
    args = parser.parse_args()
    result = prepare(Path(__file__).resolve().parents[1])
    if not args.prepare_only:
        codex = shutil.which("codex")
        if not codex:
            raise ValueError("Codex CLI was not found; local plugin prepared but not registered")
        subprocess.run(
            [codex, "plugin", "marketplace", "add", result["marketplace"]], check=True, stdout=sys.stderr
        )
        subprocess.run([codex, "plugin", "add", result["plugin"], "--json"], check=True, stdout=sys.stderr)
        result["registration_requested"] = True
    print(json.dumps(result))


if __name__ == "__main__":
    main()
