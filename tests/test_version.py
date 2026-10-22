"""Release identity and package normalization; no MCP or native application startup."""

import json
import re
import shutil
import sys
from pathlib import Path

import pytest
from packaging.version import Version
from universal_tools.manager_inventory import newer_numeric_version

from autocad_mcp import __display_version__, __version__
from autocad_mcp.capabilities import report
from autocad_mcp.version import canonical_timestamp_version, display_timestamp_version
from autocad_mcp.workflow_guidance import render
from scripts.release_version import PLUGIN_MANIFESTS, check, stamp


@pytest.mark.parametrize(
    ("display", "canonical"),
    [
        ("26.0101.000000", "26.101.0"),
        ("26.0101.000001", "26.101.1"),
        ("26.0101.010203", "26.101.10203"),
        ("26.0909.090909", "26.909.90909"),
        ("26.1231.235959", "26.1231.235959"),
        ("24.0229.235959", "24.229.235959"),
        ("00.0101.000000", "0.101.0"),
    ],
)
def test_leading_zero_identities_round_trip_and_compare_semantically(display, canonical):
    assert canonical_timestamp_version(display) == canonical
    assert canonical_timestamp_version(canonical) == canonical
    assert display_timestamp_version(canonical) == display
    assert str(Version(display)) == canonical == str(Version(canonical))
    assert Version(display) == Version(canonical)
    numeric = r"(?:0|[1-9][0-9]*)"
    assert re.fullmatch(rf"{numeric}\.{numeric}\.{numeric}", canonical)  # strict numeric SemVer
    assert not newer_numeric_version(display, canonical)
    assert not newer_numeric_version(canonical, display)


@pytest.mark.parametrize(
    "value",
    [
        "26.0230.120000",
        "25.0229.120000",
        "26.1301.120000",
        "26.0101.240000",
        "26.0101.126000",
        "26.0101.120060",
        "026.0101.120000",
        "26.00101.120000",
        "26.0101.0000000",
        "26.0101.000001\n",
        "26.0101.000001+local",
        "26.0101.-1",
    ],
)
def test_invalid_stamps_are_rejected(value):
    with pytest.raises(ValueError):
        canonical_timestamp_version(value)


def test_timestamp_ordering_handles_midnight_month_and_year_boundaries():
    for old, new in [
        ("25.1231.235959", "26.0101.000000"),
        ("26.0101.235959", "26.0102.000000"),
        ("26.0131.235959", "26.0201.000000"),
        ("26.0101.000009", "26.0101.000010"),
        ("0.6.0", __version__),
    ]:
        assert Version(new) > Version(old)
        assert newer_numeric_version(new, old)
        assert not newer_numeric_version(old, new)


def release_copy(tmp_path):
    source = Path(__file__).resolve().parents[1]
    for name in ["src/autocad_mcp/version.py", "pyproject.toml", *PLUGIN_MANIFESTS]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    return tmp_path


def test_explicit_stamp_updates_both_plugin_loaders_and_preserves_dependencies(tmp_path):
    repo = release_copy(tmp_path)
    project = (repo / "pyproject.toml").read_text()
    identity = stamp(repo, "26.0101.010203")
    assert identity == {
        "version": "26.101.10203",
        "display_version": "26.0101.010203",
        "version_timezone": "America/New_York",
    }
    assert check(repo) == identity
    for name in PLUGIN_MANIFESTS:
        assert json.loads((repo / name).read_bytes())["version"] == "26.101.10203"
    assert (
        project.split("dependencies =", 1)[1]
        == (repo / "pyproject.toml").read_text().split("dependencies =", 1)[1]
    )
    assert stamp(repo, "26.0101.010203") == identity
    with pytest.raises(ValueError, match="padded"):
        stamp(repo, "26.101.10203")


def test_legacy_manifest_divergence_is_rejected(tmp_path):
    repo = release_copy(tmp_path)
    path = repo / PLUGIN_MANIFESTS[-1]
    metadata = json.loads(path.read_bytes())
    metadata["version"] = "0.4.4"
    path.write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match="identity mismatch"):
        check(repo)


def test_public_source_capability_and_guidance_identities_agree():
    identity = check(Path(__file__).resolve().parents[1])
    assert identity["version"] == __version__ == canonical_timestamp_version(__display_version__)
    assert identity["display_version"] == __display_version__
    assert report()["version"] == __version__
    assert report()["display_version"] == __display_version__
    workflow = json.loads(render()["workflow.json"])
    assert workflow["app_version"] == __version__
    assert workflow["app_display_version"] == __display_version__


def test_cli_version_exits_before_loading_config_or_starting_services(monkeypatch, capsys):
    from autocad_mcp.__main__ import main

    monkeypatch.setattr(sys, "argv", ["autocad-mcp", "--version"])
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == (
        f"AutoCAD MCP Server {__display_version__} (package {__version__})"
    )
