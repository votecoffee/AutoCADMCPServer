"""Prepare passive local assessment evidence; this never accepts or selects a broker route."""

import argparse
import json
import shutil
from pathlib import Path

from autocad_mcp.electrical import atomic_json
from autocad_mcp.integration import broker_assessment, installed_plugins

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker-python", type=Path, required=True)
    parser.add_argument("--broker-state", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    config = (args.config or repo / ".local/config.json").resolve(strict=True)
    codex = shutil.which("codex")
    if not codex:
        raise SystemExit("Codex CLI is required to assess the intended profile")
    candidate = broker_assessment(
        repo,
        config,
        installed_plugins(codex),
        args.broker_python.resolve(strict=True),
        args.broker_state.resolve(strict=True),
    )
    target = repo / ".local/broker-assessment-candidate.json"
    atomic_json(target, candidate)
    print(json.dumps({"candidate": str(target), "status": "unassessed", "migration_performed": False}))
