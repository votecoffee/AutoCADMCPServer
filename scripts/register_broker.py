"""Register this app with an existing local Universal Tools broker, without restarting or upgrading it."""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--broker-python", required=True)
    parser.add_argument("--broker-state", required=True)
    parser.add_argument(
        "--replace", action="store_true", help="Explicitly replace this app's existing autocad registration"
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    config = repo / ".local/config.json"
    if not config.exists():
        raise SystemExit("Run configure.py first")
    # Read only schema field names from the selected installed broker, never its credential/settings.
    output = subprocess.check_output(
        [
            args.broker_python,
            "-c",
            "import json; from universal_tools.models import ServiceManifest; "
            "print(json.dumps(list(ServiceManifest.model_fields)))",
        ],
        text=True,
    )
    fields = json.loads(output)
    manifest = {
        "schema_version": 1,
        "id": "autocad",
        "display_name": "AutoCAD MCP Server",
        "description": "Local DWG/DXF/PDF and Electrical project inventory, PLC I/O, tracing, consistency and revision analysis.",
        "transport": {
            "type": "stdio",
            "command": sys.executable,
            "args": ["-m", "autocad_mcp", "--config", str(config), "serve"],
            "cwd": str(repo),
            "env_vars": [],
        },
        "enabled": True,
        "allow_writes": True,
        "timeout_seconds": 300.0,
    }
    if "allowed_write_tools" in fields:
        manifest["allowed_write_tools"] = [
            "cad_index_project",
            "cad_render_preview",
            "cad_build_electrical_project",
            "cad_export_electrical_project",
            "cad_highlight_source_object",
        ]
    if "session_mode" in fields:
        manifest["session_mode"] = "transient"
    target = repo / ".local/autocad.service.json"
    target.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    command = [
        args.broker_python,
        "-m",
        "universal_tools",
        "--state",
        args.broker_state,
        "register",
        str(target),
    ]
    if args.replace:
        command.append("--replace")
    subprocess.run(command, check=True)
    print(
        json.dumps(
            {
                "registered": "autocad",
                "exact_write_allowlist_supported": "allowed_write_tools" in fields,
                "next": "refresh_services in Universal Tools",
            }
        )
    )


if __name__ == "__main__":
    main()
