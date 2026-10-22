import json
import shutil
from pathlib import Path

from autocad_mcp import __display_version__, __version__
from autocad_mcp.profile import NUMERICAL_ENVIRONMENT
from scripts.install_plugin import FILES, prepare


def test_plugin_binding_is_local_independent_and_relocatable(tmp_path):
    source = Path(__file__).resolve().parents[1]
    repo = tmp_path / "app & files"
    template = repo / "plugins/autocad"
    for name in FILES:
        target = template / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / "plugins/autocad" / name, target)
    drawings = tmp_path / "drawings"
    drawings.mkdir()
    config = repo / ".local/config.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"roots": {"test": str(drawings)}}), encoding="utf-8")
    import sys

    python = repo / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    python.parent.mkdir(parents=True)
    python.write_bytes(b"test placeholder; never executed")
    result = prepare(repo)
    assert result["standalone"] is True
    package = Path(result["package"])
    manifest = json.loads((package / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "autocad"
    assert manifest["version"] == __version__
    assert json.loads((package / ".codex-plugin/plugin.json").read_bytes())["version"] == __version__
    assert result["version"] == __version__ and result["display_version"] == __display_version__
    assert package.name.startswith("autocad-" + __version__ + "-")
    servers = json.loads((package / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert (
        servers["autocad"]["env"]["AUTOCAD_MCP_PLUGIN_VERSION"]
        == json.loads((template / "plugin.json").read_bytes())["version"]
    )
    assert set(servers) == {"autocad"}
    assert servers["autocad"]["env"]["AUTOCAD_MCP_EXECUTION_PROFILE"] == "offline"
    assert all(servers["autocad"]["env"][name] == "1" for name in NUMERICAL_ENVIRONMENT)
    assert servers["autocad"]["env"]["AUTOCAD_MCP_PLUGIN_DISPLAY_VERSION"] == __display_version__
    assert servers["autocad"]["command"] == str(python)
    assert servers["autocad"]["args"] == ["-m", "autocad_mcp", "--config", str(config), "serve"]
    assert (
        json.loads((template / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["autocad"]["type"]
        == "streamable-http"
    )
    assert prepare(repo)["package"] == str(package)
    alternate = repo / ".local/alternate.json"
    alternate.write_bytes(config.read_bytes())
    alternate_package = Path(prepare(repo, alternate)["package"])
    assert alternate_package != package
    alternate_binding = json.loads((alternate_package / "mcp.json").read_text())
    assert str(alternate) in alternate_binding["mcpServers"]["autocad"]["args"]
    from autocad_mcp.framework_host import prepare as publish

    state = repo / ".local/framework-host"
    publish(config, state)
    framework_package = Path(prepare(repo, config, frontend="framework", host_state=state)["package"])
    binding = json.loads((framework_package / "mcp.json").read_bytes())["mcpServers"]["autocad"]
    assert "framework-proxy" in binding["args"] and str(state) in binding["args"]
    assert "universal_tools" not in binding["args"]
