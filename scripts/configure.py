"""Create private configuration and a validated-shape Universal Tools registration."""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", required=True, help="name=absolute directory (repeatable)")
    parser.add_argument("--oda", help="Absolute installed ODAFileConverter.exe")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    local = repo / ".local"
    local.mkdir(exist_ok=True)
    config_path = local / "config.json"
    if config_path.exists():
        raise SystemExit("Existing configuration preserved; edit .local/config.json explicitly")
    roots = {}
    for value in args.root:
        key, directory = value.split("=", 1)
        if key in roots:
            raise ValueError("Duplicate root name")
        roots[key] = str(Path(directory).resolve(strict=True))
    config = {"roots": roots, "state_dir": str(local / "state")}
    if args.oda:
        config["oda_executable"] = str(Path(args.oda).resolve(strict=True))
    from autocad_mcp.config import Config

    temporary = local / "config.pending.json"
    temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
    Config.load(temporary)
    temporary.replace(config_path)
    manifest = {
        "schema_version": 1,
        "id": "autocad",
        "display_name": "AutoCAD MCP Server",
        "description": "Extract DWG/DXF/PDF text, attributes, dimensions, layers, references and project search.",
        "transport": {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-m", "autocad_mcp", "--config", str(config_path), "serve"],
            "cwd": str(repo),
            "env_vars": [],
        },
        "enabled": True,
        "session_mode": "transient",
        "allow_writes": True,
        "allowed_write_tools": ["cad_index_project", "cad_render_preview"],
        "timeout_seconds": 300.0,
    }
    registration = local / "autocad.service.json"
    registration.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"config": str(config_path), "broker_registration": str(registration)}))


if __name__ == "__main__":
    main()
