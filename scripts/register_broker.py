"""Register with an existing broker without restarting, upgrading or accepting migration."""

import argparse
import json
import subprocess
from pathlib import Path

from autocad_mcp.electrical import atomic_json
from autocad_mcp.integration import broker_manifest, broker_metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker-python", type=Path, required=True)
    parser.add_argument("--broker-state", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--prepare-only", action="store_true", help="Prepare without registering")
    parser.add_argument(
        "--include-highlighting", action="store_true", help="Also authorize the guarded native UI tool"
    )
    parser.add_argument(
        "--replace", action="store_true", help="Explicitly replace this app's existing autocad registration"
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    config = args.config or repo / ".local/config.json"
    metadata = broker_metadata(args.broker_python)
    manifest = broker_manifest(repo, config, highlighting=args.include_highlighting)
    if not set(manifest) <= set(metadata["fields"]):
        raise SystemExit("Broker lacks the scoped registration contract; existing setup preserved")
    target = repo / ".local/autocad.service.json"
    atomic_json(target, manifest)
    broker_metadata(args.broker_python, target)
    if not args.prepare_only:
        command = [
            str(args.broker_python.resolve(strict=True)),
            "-m",
            "universal_tools",
            "--state",
            str(args.broker_state.resolve(strict=True)),
            "register",
            str(target),
        ]
        if args.replace:
            command.append("--replace")
        subprocess.run(command, check=True)
    print(
        json.dumps(
            {
                "prepared" if args.prepare_only else "registered": "autocad",
                "broker_version": metadata["version"],
                "session_mode": "transient",
                "allowed_write_tools": manifest["allowed_write_tools"],
                "migration_accepted": False,
                "next": "Assess isolated workflows and host behavior before selecting the broker route",
            }
        )
    )


if __name__ == "__main__":
    main()
