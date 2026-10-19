import subprocess
import sys
from pathlib import Path

import pytest

from scripts.framework_dependency import stage, verify


def test_modified_framework_wheel_is_rejected_before_installation(tmp_path):
    wheel = tmp_path / "framework.whl"
    wheel.write_bytes(b"modified dependency must never execute")
    with pytest.raises(ValueError, match="SHA-256"):
        verify(wheel)
    with pytest.raises(ValueError, match="SHA-256"):
        stage(tmp_path, str(wheel))
    assert not (tmp_path / ".local/wheels").exists()


def test_setup_requires_explicit_local_framework_artifact(tmp_path):
    with pytest.raises(ValueError, match="--framework-wheel"):
        stage(tmp_path)
    source = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(source / "scripts/launcher.py"), "--port", "0"], capture_output=True
    )
    assert result.returncode != 0 and b"--port must be" in result.stderr


def test_framework_refuses_an_sdk_downgrade(monkeypatch):
    from autocad_mcp import framework_host

    original = framework_host.importlib.metadata.version
    monkeypatch.setattr(
        framework_host.importlib.metadata,
        "version",
        lambda name: "1.30.0" if name == "mcp" else original(name),
    )
    with pytest.raises(ValueError, match="do not downgrade"):
        framework_host.require_framework()
