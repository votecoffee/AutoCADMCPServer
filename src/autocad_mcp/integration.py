"""Local installer policy. Integration selection never dispatches drawing operations."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .config import Config
from .guidance import WORKFLOW

PLUGIN_ID = "autocad@autocad-local"
UNIVERSAL_ID = "universal-tools@universal-tools-local"
OFFLINE_WRITES = (
    "cad_index_project",
    "cad_render_preview",
    "cad_build_electrical_project",
    "cad_export_electrical_project",
)
HIGHLIGHT = "cad_highlight_source_object"


def code_hash(folder: Path) -> str:
    return hashlib.sha256(
        b"".join(
            p.relative_to(folder).as_posix().encode() + b"\0" + p.read_bytes()
            for p in sorted(folder.rglob("*.py"))
        )
    ).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def app_python(repo: Path) -> Path:
    return repo / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def broker_manifest(repo: Path, config: Path, *, highlighting=False) -> dict:
    repo, config = repo.resolve(), config.resolve(strict=True)
    settings = Config.load(config)
    python = app_python(repo)
    if not python.is_file():
        raise ValueError("Run application setup first")
    return {
        "schema_version": 1,
        "id": "autocad",
        "display_name": "AutoCAD MCP Server",
        "description": "Local drawing extraction and Electrical inventory, I/O, tracing and revision analysis.",
        "transport": {
            "type": "stdio",
            "command": str(python),
            "args": ["-m", "autocad_mcp", "--config", str(config), "serve"],
            "cwd": str(repo),
            "env_vars": [],
        },
        "enabled": True,
        "allow_writes": True,
        "allowed_write_tools": list(OFFLINE_WRITES) + ([HIGHLIGHT] if highlighting else []),
        "read_only_tools": [],
        "timeout_seconds": 300.0,
        "session_mode": "transient",
        "resource_id": "autocad-state-"
        + hashlib.sha256(str(settings.state.resolve()).casefold().encode()).hexdigest()[:24],
    }


# Metadata only: no settings/token read, service initialization, tool calls or broker startup.
BROKER_PROBE = """
import hashlib, json, pathlib, sys
import universal_tools
from universal_tools.models import load_manifest, ServiceManifest
folder = pathlib.Path(universal_tools.__file__).parent
code = b''.join(p.relative_to(folder).as_posix().encode() + b'\\0' + p.read_bytes()
                for p in sorted(folder.rglob('*.py')))
result = {'version': universal_tools.__version__, 'code_sha256': hashlib.sha256(code).hexdigest(),
          'fields': list(ServiceManifest.model_fields)}
if len(sys.argv) > 1:
    result['manifest'] = load_manifest(pathlib.Path(sys.argv[1])).model_dump(mode='json')
print(json.dumps(result))
"""


def broker_metadata(python: Path, registration: Path | None = None) -> dict:
    arguments = [str(python.resolve(strict=True)), "-c", BROKER_PROBE]
    if registration:
        arguments.append(str(registration.resolve(strict=True)))
    result = subprocess.run(
        arguments, check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30
    )
    return json.loads(result.stdout)


def installed_plugins(codex: str) -> dict:
    result = subprocess.run(
        [codex, "plugin", "list", "--json"],
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )
    inventory = json.loads(result.stdout)
    if not isinstance(inventory, dict) or not isinstance(inventory.get("installed"), list):
        raise ValueError("Codex did not return a supported plugin inventory")
    plugins = {}
    for item in inventory["installed"]:
        if not isinstance(item, dict) or not isinstance(item.get("pluginId"), str):
            raise ValueError("Codex returned a malformed plugin entry")
        plugins[item["pluginId"]] = item
    return plugins


def broker_assessment(repo: Path, config: Path, plugins: dict, python: Path, state: Path) -> dict:
    """Create a passive, unaccepted assessment candidate; never dispatch app operations."""
    plugin = plugins.get(UNIVERSAL_ID, {})
    if plugin.get("installed") is not True or plugin.get("enabled") is not True:
        raise ValueError("Universal Tools is absent or disabled in the selected Codex profile")
    if not python.is_absolute() or not state.is_absolute():
        raise ValueError("Accepted broker paths must be absolute")
    registration = state / "services/autocad.json"
    metadata = broker_metadata(python, registration)
    manifest = metadata["manifest"]
    highlighting = HIGHLIGHT in (manifest.get("allowed_write_tools") or [])
    expected = broker_manifest(repo, config, highlighting=highlighting)
    if any(manifest.get(k) != v for k, v in expected.items()):
        raise ValueError("Broker registration does not match this app, config and scoped policy")
    checks = {"metadata", "adapter_workflows", "host_guidance", "recovery", "coexistence"}
    if highlighting:
        checks.add("native_highlighting")
    fingerprints = {
        "app_version": __version__,
        "app_code_sha256": code_hash(Path(__file__).parent),
        "config_sha256": file_hash(config),
        "workflow_sha256": hashlib.sha256(WORKFLOW.encode()).hexdigest(),
        "broker_plugin_id": UNIVERSAL_ID,
        "broker_plugin_version": plugin.get("version"),
        "broker_version": metadata["version"],
        "broker_code_sha256": metadata["code_sha256"],
        "registration_sha256": file_hash(registration),
        "codex_profile": str(Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").resolve()),
    }
    return {
        "schema_version": 1,
        "status": "unassessed",
        "broker_python": str(python),
        "broker_state": str(state),
        "checks": {name: False for name in sorted(checks)},
        "fingerprints": fingerprints,
    }


def accepted_broker(repo: Path, config: Path, plugins: dict) -> dict:
    """Require operator acceptance pinned to the app, profile, runtime, guidance and registration."""
    proof = json.loads((repo / ".local/broker-acceptance.json").read_text(encoding="utf-8"))
    if proof.get("schema_version") != 1 or proof.get("status") != "accepted":
        raise ValueError("Broker route has no accepted local assessment")
    candidate = broker_assessment(
        repo, config, plugins, Path(proof["broker_python"]), Path(proof["broker_state"])
    )
    if any(proof.get("checks", {}).get(name) is not True for name in candidate["checks"]):
        raise ValueError("Broker acceptance gates are incomplete")
    if proof.get("fingerprints") != candidate["fingerprints"]:
        raise ValueError("Broker acceptance does not match the current installation")
    return {
        "route": "broker",
        "broker_state": candidate["broker_state"],
        "fingerprints": candidate["fingerprints"],
    }


def select_route(mode: str, plugins: dict, previous: dict | None, broker: dict | None) -> dict:
    """No runtime failover. Reinstallation and automatic setup preserve existing choices."""
    if mode == "none":
        return {"route": "none", "action": "preserve", "reason": "Codex integration explicitly skipped"}
    if mode == "standalone":
        return {"route": "standalone", "action": "install", "reason": "Explicit standalone selection"}
    if mode == "broker":
        if broker is None:
            raise ValueError("Broker selection requires a current accepted local assessment")
        return {**broker, "action": "preserve", "reason": "Explicit accepted broker selection"}
    if mode != "auto":
        raise ValueError("Unknown integration mode")
    if previous is not None:
        if previous.get("route") not in {"none", "standalone", "broker"}:
            raise ValueError("Unknown saved integration route; existing choices preserved")
        return {**previous, "action": "preserve", "reason": "Preserved saved integration choice"}
    # A disabled app plugin is still an explicit choice, not permission to enable/replace it.
    if plugins.get(PLUGIN_ID, {}).get("installed") is True:
        return {"route": "standalone", "action": "preserve", "reason": "Preserved existing app plugin"}
    if broker is not None:
        return {**broker, "action": "preserve", "reason": "Accepted Universal Tools route available"}
    return {"route": "standalone", "action": "install", "reason": "No accepted broker route available"}


def integration_plan(repo: Path, config: Path, mode: str) -> dict:
    record = repo / ".local/codex-integration.json"
    previous = json.loads(record.read_text(encoding="utf-8")) if record.exists() else None
    codex = shutil.which("codex")
    # Preserve choices even when profile discovery is temporarily unavailable.
    if mode == "none" or mode == "auto" and previous is not None:
        return select_route(mode, {}, previous, None)
    if not codex:
        if mode == "auto":
            return {
                "route": None,
                "action": "defer",
                "reason": "Codex CLI unavailable; application is usable",
            }
        raise ValueError("Codex CLI was not found")
    try:
        plugins = installed_plugins(codex)
    except (OSError, ValueError, subprocess.SubprocessError):
        if mode == "broker":
            raise ValueError("Plugin inventory unavailable; broker selection was not changed") from None
        if mode != "standalone":
            # Unreadable state is not evidence that Universal Tools or an app plugin is absent.
            return {
                "route": None,
                "action": "defer",
                "reason": "Plugin inventory unavailable; choices preserved",
            }
        raise
    broker, reason = None, None
    if mode != "standalone":
        try:
            broker = accepted_broker(repo, config, plugins)
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            reason = type(error).__name__  # Never print imported configuration or process output.
    plan = select_route(mode, plugins, previous, broker)
    if reason:
        plan["broker_assessment"] = "unavailable or stale"
    return plan
