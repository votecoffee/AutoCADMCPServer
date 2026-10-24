import hashlib
import json
from types import SimpleNamespace

import pytest

from autocad_mcp import worker_launch
from scripts import stable_entry, stable_install


def fixture_home(tmp_path, monkeypatch):
    home = tmp_path / "stable app & 線"
    (home / "Python").mkdir(parents=True)
    (home / "Python/python.exe").write_bytes(b"fixture binary; never executed")
    (home / "StartMcp.py").write_bytes(b"fixture entry; never executed")
    python_manifest = {"files": stable_install.files(home / "Python")}
    stable_install.immutable(home / "python-manifest.json", stable_entry.canonical_json(python_manifest))
    library = home / "staging/library"
    (library / "site-packages").mkdir(parents=True)
    (library / "site-packages/dependency.py").write_bytes(b"# fixture")
    library_raw = stable_entry.canonical_json({"files": stable_install.files(library / "site-packages")})
    library_id = hashlib.sha256(library_raw).hexdigest()
    stable_install.immutable(library / "manifest.json", library_raw)
    target = home / "libraries" / library_id
    target.parent.mkdir()
    library.rename(target)
    config = home / "configurations/fixture.json"
    stable_install.immutable(config, b'{"execution_profile":"offline"}')
    snapshot = home / "staging/snapshot"
    snapshot.mkdir()
    (snapshot / "worker.py").write_bytes(b"fixture worker; never executed")
    manifest = {
        "schema_version": 1,
        "app_id": "autocad",
        "version": "1.0.0",
        "profile": "offline",
        "library_id": library_id,
        "bootstrap_id": stable_entry.sha256(home / "python-manifest.json"),
        "entry_sha256": stable_entry.sha256(home / "StartMcp.py"),
        "dependencies": stable_entry.PINS,
        "config": "configurations/fixture.json",
        "config_sha256": stable_entry.sha256(config),
        "environment": {},
        "registry": str(home / "registry"),
        "files": stable_install.files(snapshot),
    }
    raw = stable_entry.canonical_json(manifest)
    generation = hashlib.sha256(raw).hexdigest()
    stable_install.immutable(snapshot / "manifest.json", raw)
    final = home / "launcher/snapshots" / generation
    final.parent.mkdir(parents=True)
    snapshot.rename(final)
    stable_install.immutable(
        home / "launcher/current.json",
        stable_entry.canonical_json({"schema_version": 1, "generation": generation}),
    )
    monkeypatch.setattr(stable_entry.sys, "executable", str(home / "Python/python.exe"))
    monkeypatch.setattr(stable_entry.sys, "prefix", str(home / "Python"))
    monkeypatch.setattr(stable_entry.sys, "base_prefix", str(home / "Python"))
    return home, generation


@pytest.mark.parametrize("relative", ["Python/python.exe", "StartMcp.py", "configurations/fixture.json"])
def test_tampered_payload_refuses_before_any_execution(tmp_path, monkeypatch, relative):
    home, _ = fixture_home(tmp_path, monkeypatch)
    assert stable_entry.verify(home)["version"] == "1.0.0"
    (home / relative).write_bytes(b"tampered")
    with pytest.raises(ValueError):
        stable_entry.verify(home)


def test_missing_and_malformed_selection_refuse_without_fallback(tmp_path, monkeypatch):
    home, _ = fixture_home(tmp_path, monkeypatch)
    pointer = home / "launcher/current.json"
    pointer.write_bytes(b'{"schema_version":1,"generation":"../other"}')
    with pytest.raises(ValueError):
        stable_entry.verify(home)
    pointer.unlink()
    with pytest.raises(OSError):
        stable_entry.verify(home)


def test_pointer_cas_preserves_concurrent_selection_and_backup(tmp_path, monkeypatch):
    home, generation = fixture_home(tmp_path, monkeypatch)
    pointer = home / "launcher/current.json"
    before = pointer.read_bytes()
    before_hash = stable_entry.sha256(pointer)

    def concurrent(*args, **kwargs):
        pointer.write_bytes(b'{"schema_version":1,"generation":"concurrent"}')
        return SimpleNamespace(
            stdout=json.dumps({"generation": generation, "passed": True, "mcp_started": False})
        )

    monkeypatch.setattr(stable_install.subprocess, "run", concurrent)
    with pytest.raises(ValueError, match="changed during"):
        stable_install.publish(home, generation, expected_current=before_hash)
    assert pointer.read_bytes() != before
    assert (home / "launcher/backups" / (before_hash + ".json")).read_bytes() == before


def test_stable_worker_remains_bound_to_original_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_launch, "_deployment", None)
    generation = "a" * 64
    snapshot = tmp_path / generation
    worker_launch.bind_deployment(snapshot, generation, stable=True)
    command = worker_launch.worker_command("_extract", "request.json", "output.json")
    assert command[1:7] == ["-I", "-S", "-B", "-X", "utf8", str(snapshot / "worker.py")]
    assert command[7:] == [generation, "_extract", "request.json", "output.json"]
