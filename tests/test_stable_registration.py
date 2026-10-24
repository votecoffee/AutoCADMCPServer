import hashlib
import json

from scripts.install_plugin import registration_guard
from scripts.stable_binding import propose
from scripts.stable_install import binding
from tests.test_stable_policy import fixture_home


def test_legacy_route_defers_without_touching_settings_or_cache(tmp_path, monkeypatch):
    from scripts import stable_binding

    monkeypatch.setattr(stable_binding, "__file__", str(tmp_path / "source/scripts/stable_binding.py"))
    home, _ = fixture_home(tmp_path, monkeypatch)
    codex = tmp_path / "codex"
    cache = codex / "plugins/cache/autocad-local/autocad/old"
    cache.mkdir(parents=True)
    (cache / "launcher.py").write_bytes(b"# original cache")
    raw = (
        '\ufeff# preserve comments\r\n[mcp_servers.autocad]\r\ncommand="old.exe"\r\ncwd='
        + json.dumps(str(cache))
        + "\r\nargs=[]\r\n"
    ).encode()
    settings = codex / "config.toml"
    settings.write_bytes(raw)
    result = registration_guard(home, settings)
    assert not result["ready"]
    assert settings.read_bytes() == raw and (cache / "launcher.py").read_bytes() == b"# original cache"
    from pathlib import Path

    retained = Path(result["retained_pins"])
    assert (retained / "config-before.toml").read_bytes() == raw
    assert (retained / "cache/launcher.py").read_bytes() == b"# original cache"
    proposal = propose(home, settings, tmp_path / "review only")
    assert proposal["expected_config_sha256"] == hashlib.sha256(raw).hexdigest()
    assert proposal["proposed_route"]["command"] == binding(home)["command"]
    assert settings.read_bytes() == raw


def test_already_stable_route_allows_registration_without_backup_writes(tmp_path, monkeypatch):
    home, _ = fixture_home(tmp_path, monkeypatch)
    route = binding(home)
    settings = tmp_path / "config.toml"
    raw = (
        "[mcp_servers.autocad]\ncommand="
        + json.dumps(route["command"])
        + "\nargs="
        + json.dumps(route["args"])
        + "\ncwd="
        + json.dumps(route["cwd"])
        + "\n"
    ).encode()
    settings.write_bytes(raw)
    assert registration_guard(home, settings)["ready"]
    assert settings.read_bytes() == raw and not (home / "registration-pins").exists()
