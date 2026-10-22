import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import autocad_mcp.integration as integration
from autocad_mcp.integration import PLUGIN_ID, select_route


@pytest.mark.parametrize("previous", [None, {"route": "standalone"}])
def test_auto_installs_or_refreshes_standalone_without_alternative_routes(previous):
    plugins = {"other-plugin@example": {"installed": True, "enabled": True}}
    assert select_route("auto", plugins, previous)["action"] == "install"
    plugins[PLUGIN_ID] = {"installed": True, "enabled": True, "version": "old"}
    plan = select_route("auto", plugins, previous)
    assert (plan["route"], plan["action"]) == ("standalone", "install")


@pytest.mark.parametrize("installed", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
def test_retired_universal_plugin_inventory_never_changes_app_installation(installed, enabled):
    plugins = {"universal-tools@universal-tools-local": {"installed": installed, "enabled": enabled}}
    plan = select_route("auto", plugins, None)
    assert (plan["route"], plan["action"]) == ("standalone", "install")


def test_disabled_and_skipped_choices_are_preserved_until_explicit_install():
    plugins = {PLUGIN_ID: {"installed": True, "enabled": False}}
    assert select_route("auto", plugins, {"route": "standalone"})["action"] == "preserve"
    assert select_route("auto", plugins, {"route": "none"})["route"] == "none"
    assert select_route("standalone", plugins, {"route": "none"})["action"] == "install"


def test_removed_route_cannot_be_selected_or_reactivated_from_saved_state():
    with pytest.raises(ValueError, match="Choose"):
        select_route("broker", {}, None)
    with pytest.raises(ValueError, match="--install-plugin"):
        select_route("auto", {}, {"route": "broker"})
    assert select_route("standalone", {}, {"route": "broker"})["route"] == "standalone"


def test_missing_or_unreadable_cli_preserves_state(tmp_path, monkeypatch):
    monkeypatch.setattr(integration.shutil, "which", lambda _: None)
    assert integration.integration_plan(tmp_path, "auto")["action"] == "defer"
    with pytest.raises(ValueError, match="CLI"):
        integration.integration_plan(tmp_path, "standalone")
    monkeypatch.setattr(integration.shutil, "which", lambda _: "codex")

    def unavailable(_):
        raise subprocess.TimeoutExpired("codex", 30)

    monkeypatch.setattr(integration, "installed_plugins", unavailable)
    assert integration.integration_plan(tmp_path, "auto")["action"] == "defer"
    record = tmp_path / ".local/codex-integration.json"
    record.parent.mkdir()
    record.write_text(json.dumps({"route": "none"}))
    assert integration.integration_plan(tmp_path, "auto")["route"] == "none"
    assert json.loads(record.read_bytes()) == {"route": "none"}


def test_removed_cli_mode_is_rejected_before_setup():
    source = Path(__file__).resolve().parents[1]
    for script, option in [("launcher.py", "--codex-integration"), ("install_plugin.py", "--mode")]:
        result = subprocess.run(
            [sys.executable, str(source / "scripts" / script), option, "broker"], capture_output=True
        )
        assert result.returncode != 0 and b"invalid choice" in result.stderr


def test_configuration_creates_only_app_configuration(tmp_path):
    source = Path(__file__).resolve().parents[1]
    scripts = tmp_path / "app/scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(source / "scripts/configure.py", scripts / "configure.py")
    drawings = tmp_path / "drawings"
    drawings.mkdir()
    result = subprocess.run(
        [sys.executable, str(scripts / "configure.py"), "--root", "fixture=" + str(drawings)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert set(config) == {"config"}
    assert {p.name for p in (tmp_path / "app/.local").iterdir()} == {"config.json"}
