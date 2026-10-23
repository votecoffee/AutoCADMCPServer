"""Disposable ODA-shaped fixtures. No ODA, AutoCAD or customer drawing is executed."""

import base64
import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import ezdxf
import pytest

from autocad_mcp import extract, oda, owned_process, service
from autocad_mcp.capabilities import report
from autocad_mcp.config import Config
from autocad_mcp.owned_resources import OwnedResources


@pytest.fixture
def conversion(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTOCAD_MCP_EXECUTION_PROFILE", raising=False)
    drawings = tmp_path / "drawings"
    drawings.mkdir()
    source = drawings / "fixture.dwg"
    source.write_bytes(b"not a real DWG: source preservation fixture")
    original = source.read_bytes()
    binary = tmp_path / "ODAFileConverter.exe"
    binary.write_bytes(b"not an executable: never launched")
    options = {
        "execution_profile": "oda-read",
        "oda_executable": str(binary),
        "oda_sha256": oda.digest(binary),
        "max_entities": 50,
        "max_pages": 2,
    }
    fixture = tmp_path / "fixture.dxf"
    doc = ezdxf.new("R2018")
    doc.modelspace().add_text("SENSOR-101")
    doc.saveas(fixture)

    @contextlib.contextmanager
    def pinned(executable, pin):
        assert Path(executable) == binary and oda.digest(binary) == pin
        yield binary

    monkeypatch.setattr(oda, "pinned_converter", pinned)
    monkeypatch.setattr(service, "pinned_converter", pinned)

    def runner(argv, **kwargs):
        inputs, outputs = Path(argv[1]), Path(argv[2])
        assert argv[3:] == ["ACAD2018", "DXF", "0", "0", "source.dwg"]
        assert list(inputs.iterdir()) == [inputs / "source.dwg"]
        assert (inputs / "source.dwg").read_bytes() == original
        assert kwargs == {"timeout": 60, "check": False, "resource_kind": "oda-converter"}
        (outputs / "source.dxf").write_bytes(fixture.read_bytes())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(oda, "run_owned", runner)
    return source, binary, fixture, options


@pytest.mark.parametrize("extension", [".dwg", ".dwt", ".dws"])
def test_fixed_conversion_readback_and_source_preservation(conversion, extension):
    source, binary, fixture, options = conversion
    original = source.read_bytes()
    source = source.rename(source.with_suffix(extension))
    with oda.converted_dxf(source, options) as (dxf, backend):
        staging = dxf.parent.parent
        assert source.parent not in staging.parents
        assert dxf.read_bytes() == fixture.read_bytes()
        assert backend["input_sha256"] == oda.digest(source)
        assert backend["converted_dxf_sha256"] == oda.digest(fixture)
        assert backend["oda_sha256"] == oda.digest(binary)
        assert not backend["native_autocad_validation"] and not backend["audit"]
    assert not staging.exists() and source.read_bytes() == original
    assert list(source.parent.iterdir()) == [source]


def test_explicit_config_capabilities_and_options(conversion, tmp_path):
    source, _, _, options = conversion
    filename = tmp_path / "config.json"
    filename.write_text(json.dumps({"roots": {"fixture": str(source.parent)}, **options}))
    config = Config.load(filename)
    drawings = service.DrawingService(config)
    status = drawings.status()
    assert config.files("fixture")[0]["supported"]
    assert config.conversion_options()["oda_sha256"] == options["oda_sha256"]
    assert report(config=config)["execution_profile"] == "oda-read"
    assert status["supported_extensions"] == report(config=config)["available_formats"]
    assert status["native_operations_available"] and not status["autocad_automation_available"]
    assert not status["blocked_extensions"]


@pytest.mark.parametrize(
    "changes",
    [
        {"oda_sha256": None},
        {"oda_sha256": "a" * 63},
        {"oda_sha256": "G" * 64},
        {"oda_executable": "relative.exe"},
        {"oda_executable": "C:/missing.exe"},
    ],
)
def test_invalid_native_policy_fails_before_state_creation(conversion, tmp_path, changes):
    source, _, _, options = conversion
    filename = tmp_path / "config.json"
    filename.write_text(json.dumps({"roots": {"fixture": str(source.parent)}, **options, **changes}))
    with pytest.raises(ValueError):
        Config.load(filename)
    assert not (tmp_path / "state").exists()


def test_offline_environment_cannot_be_bypassed_by_oda_config(conversion, monkeypatch):
    source, _, _, options = conversion
    monkeypatch.setenv("AUTOCAD_MCP_EXECUTION_PROFILE", "offline")
    with pytest.raises(ValueError, match="Execution profile differs"):
        with oda.converted_dxf(source, options):
            pytest.fail("No launch permitted")


@pytest.mark.parametrize(
    "mode", ["failed", "missing", "duplicate", "oversize", "directory", "hardlink", "input_changed"]
)
def test_failed_or_ambiguous_conversion_is_discarded(conversion, monkeypatch, mode):
    source, _, fixture, options = conversion
    staged = []

    def runner(argv, **kwargs):
        inputs, outputs = Path(argv[1]), Path(argv[2])
        staged.append(outputs.parent)
        destination = outputs / "source.dxf"
        if mode == "directory":
            destination.mkdir()
        elif mode == "hardlink":
            os.link(fixture, destination)
        elif mode != "missing":
            destination.write_bytes(fixture.read_bytes())
        if mode == "duplicate":
            (outputs / "second.DXF").write_bytes(fixture.read_bytes())
        if mode == "input_changed":
            (inputs / "source.dwg").write_bytes(b"converter changed the snapshot")
        return SimpleNamespace(returncode=7 if mode == "failed" else 0)

    monkeypatch.setattr(oda, "run_owned", runner)
    if mode == "oversize":
        options["max_file_bytes"] = source.stat().st_size + 1
    with pytest.raises(ValueError):
        with oda.converted_dxf(source, options):
            pytest.fail("Unacceptable result published")
    assert staged and not staged[0].exists()


def test_changed_readback_is_discarded(conversion):
    source, _, _, options = conversion
    with pytest.raises(ValueError, match="readback changed"):
        with oda.converted_dxf(source, options) as (dxf, _):
            staging = dxf.parent.parent
            dxf.write_bytes(b"replaced while being read")
    assert not staging.exists()


def test_corrupt_output_never_publishes_worker_response(conversion, monkeypatch, tmp_path):
    source, _, fixture, options = conversion
    fixture.write_bytes(b"corrupt DXF")
    destination = tmp_path / "response.json"
    with pytest.raises((ezdxf.DXFError, OSError)):
        extract.run_worker(str(source), str(destination), json.dumps(options))
    assert not destination.exists()


def test_service_worker_policy_cache_and_original_change_rejection(conversion, monkeypatch, tmp_path):
    source, binary, _, options = conversion
    config = Config(
        {"fixture": source.parent},
        tmp_path / "state",
        oda_executable=binary,
        oda_sha256=options["oda_sha256"],
        execution_profile="oda-read",
    )
    drawings = service.DrawingService(config)
    calls = []

    def worker(argv, **kwargs):
        inputs, destination, policy = argv[-3:]
        assert json.loads(policy)["execution_profile"] == "oda-read"
        assert json.loads(policy)["oda_sha256"] == options["oda_sha256"]
        calls.append(inputs)
        extract.run_worker(inputs, destination, policy)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(service, "run_owned", worker)
    before = oda.digest(source)
    record = drawings.load("fixture", source.name)
    assert record["backend"]["input_sha256"] == record["source"]["sha256"] == before
    assert record["text"][0]["text"] == "SENSOR-101"
    assert drawings.load("fixture", source.name) == record and len(calls) == 1

    def changed(argv, **kwargs):
        result = worker(argv, **kwargs)
        source.write_bytes(b"changed original")
        return result

    monkeypatch.setattr(service, "run_owned", changed)
    for cache in (config.state / "cache").iterdir():
        cache.unlink()
    with pytest.raises(ValueError, match="Source changed during extraction"):
        drawings.load("fixture", source.name)
    assert not list((config.state / "cache").iterdir())


@pytest.mark.anyio
async def test_in_memory_mcp_reports_profile_and_extracts_without_exposing_policy(
    conversion, monkeypatch, tmp_path
):
    from mcp import Client

    from autocad_mcp.server import create_server

    source, binary, _, options = conversion
    config = Config(
        {"fixture": source.parent},
        tmp_path / "state",
        oda_executable=binary,
        oda_sha256=options["oda_sha256"],
        execution_profile="oda-read",
    )

    def worker(argv, **kwargs):
        extract.run_worker(*argv[-3:])
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(service, "run_owned", worker)
    server = create_server(service.DrawingService(config))
    async with Client(server, mode="2026-07-28", cache=None) as client:
        capabilities = (await client.call_tool("cad_capabilities", {})).structured_content
        assert capabilities["execution_profile"] == "oda-read"
        assert not capabilities["autocad_automation_available"]
        listing = await client.list_tools()
        inspect = next(tool for tool in listing.tools if tool.name == "cad_inspect")
        assert set(inspect.input_schema["properties"]) == {"root_id", "relative_path"}
        result = await client.call_tool("cad_inspect", {"root_id": "fixture", "relative_path": source.name})
        assert not result.is_error
        assert result.structured_content["backend"]["oda_sha256"] == options["oda_sha256"]
        assert (
            await client.call_tool(
                "cad_highlight_source_object",
                {
                    "project_id": "not-read",
                    "device_id": "not-read",
                },
            )
        ).is_error


@pytest.mark.skipif(os.name != "nt", reason="Windows executable sharing and containment")
def test_binary_pin_blocks_replacement_until_readback_and_refuses_wrong_hash(tmp_path):
    binary = tmp_path / "not-executable.exe"
    binary.write_bytes(b"pin fixture")
    with oda.pinned_converter(binary, oda.digest(binary)):
        with pytest.raises(PermissionError):
            binary.write_bytes(b"changed")
        with pytest.raises(PermissionError):
            binary.unlink()
    binary.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256"):
        with oda.pinned_converter(binary, "0" * 64):
            pytest.fail("Wrong binary accepted")
    config = Config(
        {"fixture": tmp_path},
        tmp_path / "not-created",
        execution_profile="oda-read",
        oda_executable=binary,
        oda_sha256="0" * 64,
    )
    with pytest.raises(ValueError, match="SHA-256"):
        service.DrawingService(config)
    assert not config.state.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows durable process identity fixture")
def test_harmless_converter_standin_has_terminal_owned_receipt(conversion, tmp_path, monkeypatch):
    source, _, fixture, options = conversion
    resources = OwnedResources(tmp_path / "registry")
    monkeypatch.setattr(owned_process, "owned_resources", resources)
    payload = base64.b64encode(fixture.read_bytes()).decode()

    def runner(argv, **kwargs):
        code = (
            "import base64,sys;from pathlib import Path;"
            f"Path(sys.argv[2],'source.dxf').write_bytes(base64.b64decode('{payload}'))"
        )
        return owned_process.run_owned([sys.executable, "-c", code, *argv[1:]], **kwargs)

    monkeypatch.setattr(oda, "run_owned", runner)
    try:
        result = extract.extract_cad(source, options)
        assert result["text"][0]["text"] == "SENSOR-101"
        records = resources.ledger.records()
        assert len(records) == 1 and records[0].owner.pid == os.getpid()
        assert records[0].state == "terminated" and records[0].receipt.outcome == "terminated"
        assert resources.snapshot()["active_count"] == 0
    finally:
        resources.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows private Python timeout fixture")
def test_converter_timeout_discards_staging_and_records_cleanup(conversion, tmp_path, monkeypatch):
    source, _, _, options = conversion
    resources = OwnedResources(tmp_path / "registry")
    monkeypatch.setattr(owned_process, "owned_resources", resources)
    staged = []

    def runner(argv, **kwargs):
        staged.append(Path(argv[2]).parent)
        return owned_process.run_owned(
            [sys.executable, "-c", "import time;time.sleep(60)"],
            timeout=1,
            resource_kind=kwargs["resource_kind"],
        )

    monkeypatch.setattr(oda, "run_owned", runner)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            extract.extract_cad(source, options)
        assert staged and not staged[0].exists()
        records = resources.ledger.records()
        assert len(records) == 1 and records[0].state == "terminated"
        assert resources.snapshot()["active_count"] == 0
    finally:
        resources.close()
