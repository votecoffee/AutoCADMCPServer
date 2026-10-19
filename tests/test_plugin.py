import json
import shutil
from pathlib import Path

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
    assert result["broker_required"] is False
    package = Path(result["package"])
    manifest = json.loads((package / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "autocad"
    servers = json.loads((package / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert set(servers) == {"autocad"}
    assert servers["autocad"]["command"] == str(python)
    assert servers["autocad"]["args"] == ["-m", "autocad_mcp", "--config", str(config), "serve"]
    assert (
        json.loads((template / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["autocad"]["type"]
        == "streamable-http"
    )
    assert prepare(repo)["package"] == str(package)
