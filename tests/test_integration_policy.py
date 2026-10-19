import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

import autocad_mcp.integration as integration
from autocad_mcp import __version__
from autocad_mcp.guidance import WORKFLOW
from autocad_mcp.integration import PLUGIN_ID, UNIVERSAL_ID, select_route


@pytest.mark.parametrize(
    "universal",
    [None, {"installed": False}, {"installed": True, "enabled": False}, {"installed": True, "enabled": True}],
)
def test_presence_without_accepted_registration_does_not_skip_standalone(universal):
    plugins = {UNIVERSAL_ID: universal} if universal else {}
    plan = select_route("auto", plugins, None, None)
    assert (plan["route"], plan["action"]) == ("standalone", "install")


@pytest.mark.parametrize("enabled", [True, False])
def test_auto_preserves_existing_plugin_including_disabled_choice(enabled):
    plugins = {PLUGIN_ID: {"installed": True, "enabled": enabled}}
    assert select_route("auto", plugins, None, {"route": "broker"})["action"] == "preserve"
    assert select_route("auto", plugins, None, {"route": "broker"})["route"] == "standalone"


def test_fresh_accepted_broker_skips_direct_plugin_but_explicit_standalone_installs():
    broker = {"route": "broker", "fingerprints": {"example": "pinned"}}
    assert select_route("auto", {}, None, broker)["route"] == "broker"
    assert select_route("auto", {}, None, broker)["action"] == "preserve"
    assert select_route("standalone", {}, None, broker)["action"] == "install"
    with pytest.raises(ValueError, match="accepted"):
        select_route("broker", {}, None, None)


@pytest.mark.parametrize("saved", ["standalone", "broker", "none"])
def test_auto_never_switches_saved_route_when_a_broker_disappears(saved):
    previous = {"schema_version": 1, "route": saved}
    plan = select_route("auto", {}, previous, None)
    assert (plan["route"], plan["action"]) == (saved, "preserve")


def test_missing_or_unreadable_cli_preserves_state(tmp_path, monkeypatch):
    monkeypatch.setattr(integration.shutil, "which", lambda _: None)
    plan = integration.integration_plan(tmp_path, tmp_path / "config.json", "auto")
    assert plan["action"] == "defer" and plan["route"] is None
    monkeypatch.setattr(integration.shutil, "which", lambda _: "codex")

    def unavailable(_):
        raise subprocess.TimeoutExpired("codex", 30)

    monkeypatch.setattr(integration, "installed_plugins", unavailable)
    assert integration.integration_plan(tmp_path, tmp_path / "config.json", "auto")["action"] == "defer"
    with pytest.raises(ValueError, match="inventory"):
        integration.integration_plan(tmp_path, tmp_path / "config.json", "broker")
    record = tmp_path / ".local/codex-integration.json"
    record.parent.mkdir()
    record.write_text(json.dumps({"route": "broker"}))
    assert integration.integration_plan(tmp_path, tmp_path / "config.json", "auto")["route"] == "broker"


@pytest.fixture
def assessment(tmp_path, monkeypatch):
    repo = tmp_path / "app & drawings"
    repo.mkdir()
    drawings = tmp_path / "drawings"
    drawings.mkdir()
    config = repo / ".local/config.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"roots": {"test": str(drawings)}}))
    python = integration.app_python(repo)
    python.parent.mkdir(parents=True)
    python.write_bytes(b"placeholder never executed")
    state = tmp_path / "broker-state"
    registration = state / "services/autocad.json"
    registration.parent.mkdir(parents=True)
    manifest = integration.broker_manifest(repo, config)
    registration.write_text(json.dumps(manifest))
    metadata = {"version": "fixture", "code_sha256": "fixture-code", "manifest": manifest}
    monkeypatch.setattr(integration, "broker_metadata", lambda *args: metadata)
    proof = {
        "schema_version": 1,
        "status": "accepted",
        "broker_python": str(python),
        "broker_state": str(state),
        "checks": {
            name: True
            for name in ("metadata", "adapter_workflows", "host_guidance", "recovery", "coexistence")
        },
        "fingerprints": {
            "app_version": __version__,
            "app_code_sha256": integration.code_hash(Path(integration.__file__).parent),
            "config_sha256": integration.file_hash(config),
            "workflow_sha256": hashlib.sha256(WORKFLOW.encode()).hexdigest(),
            "broker_plugin_id": UNIVERSAL_ID,
            "broker_plugin_version": "fixture-plugin",
            "broker_version": metadata["version"],
            "broker_code_sha256": metadata["code_sha256"],
            "registration_sha256": integration.file_hash(registration),
            "codex_profile": str(Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").resolve()),
        },
    }
    plugins = {UNIVERSAL_ID: {"installed": True, "enabled": True, "version": "fixture-plugin"}}
    return repo, config, registration, proof, plugins, metadata


def save_assessment(repo, proof):
    (repo / ".local/broker-acceptance.json").write_text(json.dumps(proof))


def test_broker_acceptance_is_explicit_pinned_and_scoped(assessment):
    repo, config, registration, proof, plugins, metadata = assessment
    assert integration.HIGHLIGHT not in metadata["manifest"]["allowed_write_tools"]
    save_assessment(repo, proof)
    assert integration.accepted_broker(repo, config, plugins)["route"] == "broker"
    proof["checks"]["host_guidance"] = False
    save_assessment(repo, proof)
    with pytest.raises(ValueError, match="gates"):
        integration.accepted_broker(repo, config, plugins)
    proof["checks"]["host_guidance"] = True
    save_assessment(repo, proof)
    registration.write_text(registration.read_text() + "\n")
    with pytest.raises(ValueError, match="installation"):
        integration.accepted_broker(repo, config, plugins)


@pytest.mark.parametrize(
    "changed", ["plugin_disabled", "broker_version", "broad_writes", "wrong_app", "config"]
)
def test_changed_broker_prerequisites_invalidate_acceptance(assessment, changed):
    repo, config, registration, proof, plugins, metadata = assessment
    save_assessment(repo, proof)
    if changed == "plugin_disabled":
        plugins[UNIVERSAL_ID]["enabled"] = False
    elif changed == "broker_version":
        metadata["version"] = "changed"
    elif changed == "broad_writes":
        metadata["manifest"]["allowed_write_tools"] = None
    elif changed == "wrong_app":
        metadata["manifest"]["transport"]["command"] = "other-app"
    else:
        config.write_text(config.read_text() + "\n")
    with pytest.raises(ValueError):
        integration.accepted_broker(repo, config, plugins)


def test_native_highlight_is_separately_gated(assessment):
    repo, config, registration, proof, plugins, metadata = assessment
    metadata["manifest"]["allowed_write_tools"].append(integration.HIGHLIGHT)
    registration.write_text(json.dumps(metadata["manifest"]))
    proof["fingerprints"]["registration_sha256"] = integration.file_hash(registration)
    save_assessment(repo, proof)
    with pytest.raises(ValueError, match="gates"):
        integration.accepted_broker(repo, config, plugins)
    proof["checks"]["native_highlighting"] = True
    save_assessment(repo, proof)
    assert integration.accepted_broker(repo, config, plugins)["route"] == "broker"
