"""Metadata process ownership uses stubs; no live Codex/plugin/manager is invoked."""

import json
import os
import sys
from types import SimpleNamespace

import pytest

from autocad_mcp import management


def test_inventory_uses_owned_fixed_command_and_cached_results(tmp_path, monkeypatch):
    executable = tmp_path / "codex.exe"
    executable.write_bytes(b"Not executed")
    calls = []

    def probe(argv, **options):
        calls.append((argv, options))
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "installed": [
                        {
                            "pluginId": management.PLUGIN_ID,
                            "name": "AutoCAD",
                            "version": "0.6.0",
                            "installed": True,
                            "enabled": False,
                        }
                    ]
                }
            ).encode()
        )

    monkeypatch.setattr(management, "run_owned", probe)
    inventory = management.OwnedCodexInventory(command=str(executable))
    first = inventory.refresh()
    assert first[1] is None and not first[0][0]["enabled"]
    assert inventory.refresh() == first and len(calls) == 1
    assert calls[0][0] == [str(executable), "plugin", "list", "--json"]
    assert calls[0][1]["resource_kind"] == "codex-inventory"
    assert calls[0][1]["capture_limit"] == 2 * 1024 * 1024


@pytest.mark.skipif(os.name != "nt", reason="Windows official npm shim resolution")
def test_npm_inventory_resolves_node_without_executing_shell_wrapper(tmp_path, monkeypatch):
    shim = tmp_path / "codex.cmd"
    shim.write_text("Not executed")
    node = tmp_path / "node.exe"
    node.write_bytes(b"Not executed")
    script = tmp_path / "node_modules/@openai/codex/bin/codex.js"
    script.parent.mkdir(parents=True)
    script.write_text("Not executed")
    inventory = management.OwnedCodexInventory(command=str(shim))
    assert inventory.argv() == [str(node), str(script), "plugin", "list", "--json"]
    script.unlink()
    monkeypatch.setattr(management, "run_owned", lambda *args, **kwargs: pytest.fail("Unowned fallback"))
    assert inventory.refresh()[1] is not None


def test_experimental_host_refuses_start_before_any_server_or_transport(tmp_path, monkeypatch):
    from autocad_mcp import framework_host

    monkeypatch.setattr(framework_host, "create_host", lambda *args, **kwargs: pytest.fail("Backend launch"))
    with pytest.raises(ValueError, match="SDK stdio"):
        framework_host.serve(tmp_path, tmp_path / "publication.json", tmp_path / "config.json")
    with pytest.raises(ValueError, match="SDK stdio"):
        framework_host.proxy(tmp_path)


def test_experimental_installer_and_backend_refuse_before_configuration_or_cli(tmp_path, monkeypatch, capsys):
    from autocad_mcp import __main__
    from scripts import install_plugin

    monkeypatch.setattr(sys, "argv", ["install_plugin.py", "--frontend", "framework"])
    with pytest.raises(SystemExit) as installed:
        install_plugin.main()
    assert installed.value.code == 2 and "SDK stdio" in capsys.readouterr().err
    monkeypatch.setattr(
        sys, "argv", ["autocad-mcp", "--config", str(tmp_path / "absent.json"), "serve", "--workflow"]
    )
    with pytest.raises(SystemExit) as backend:
        __main__.main()
    assert backend.value.code == 2 and "SDK stdio" in capsys.readouterr().err
