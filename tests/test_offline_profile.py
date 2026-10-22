"""Offline gates use disposable files and stubs, with no MCP/native process startup."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from autocad_mcp import autocad, electrical_server, extract
from autocad_mcp.capabilities import report
from autocad_mcp.config import Config
from autocad_mcp.owned_process import run_owned
from autocad_mcp.profile import NUMERICAL_ENVIRONMENT, configure_runtime
from autocad_mcp.service import DrawingService


def configuration(tmp_path, **overrides):
    source = tmp_path / "drawings"
    source.mkdir(exist_ok=True)
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"roots": {"fixture": str(source)}, **overrides}))
    return path, source


def test_default_profile_does_not_discover_native_utilities_and_excludes_native_formats(
    tmp_path, monkeypatch
):
    path, source = configuration(tmp_path)
    monkeypatch.setattr(Path, "glob", lambda *args: (_ for _ in ()).throw(AssertionError("No ODA scan")))
    config = Config.load(path)
    assert config.execution_profile == "offline" and config.oda_executable is None
    for name in ("native.dwg", "template.dwt", "standards.dws", "cad.dxf", "report.pdf"):
        (source / name).write_bytes(b"Inventory-only fixture")
    rows = config.files("fixture")
    assert {row["extension"] for row in rows if row["supported"]} == {".pdf", ".dxf"}


@pytest.mark.parametrize("profile", ["native", "online", "framework", None, True])
def test_nonoffline_config_cannot_enable_a_native_route(tmp_path, profile):
    path, _ = configuration(tmp_path, execution_profile=profile)
    with pytest.raises(ValueError, match="Only execution_profile='offline'"):
        Config.load(path)


def test_explicit_oda_configuration_is_rejected_before_path_lookup_or_state_creation(tmp_path):
    path, _ = configuration(tmp_path, oda_executable="C:/must-not-be-read/ODAFileConverter.exe")
    with pytest.raises(ValueError, match="oda_executable must be unset"):
        Config.load(path)
    assert not (tmp_path / "state").exists()


def test_environment_cannot_enable_native_execution(tmp_path, monkeypatch):
    path, _ = configuration(tmp_path)
    monkeypatch.setenv("AUTOCAD_MCP_EXECUTION_PROFILE", "native")
    monkeypatch.setenv("AUTOCAD_MCP_ENABLE_NATIVE", "1")
    with pytest.raises(ValueError, match="Only execution_profile='offline'"):
        Config.load(path)
    with pytest.raises(ValueError, match="standalone offline profile"):
        autocad.highlight(None, {})


def test_programmatic_configuration_cannot_bypass_the_service_gate(tmp_path):
    config = Config({"fixture": tmp_path}, tmp_path / "state", oda_executable=Path("unread-native.exe"))
    with pytest.raises(ValueError, match="oda_executable must be unset"):
        DrawingService(config)
    assert not config.state.exists()


@pytest.mark.parametrize("extension", [".dwg", ".dwt", ".dws"])
def test_converter_and_private_worker_refuse_before_launch_or_output_creation(
    tmp_path, monkeypatch, extension
):
    launches = []
    monkeypatch.setattr(extract, "run_owned", lambda *args, **kwargs: launches.append(args))
    source, destination = tmp_path / ("source" + extension), tmp_path / "response.json"
    source.write_bytes(b"Synthetic native-format stand-in")
    options = json.dumps({"oda_executable": "C:/must-not-start.exe", "max_entities": 10})
    with pytest.raises(ValueError, match="standalone offline profile"):
        extract.run_worker(str(source), str(destination), options)
    assert launches == [] and not destination.exists() and not (tmp_path / "converted").exists()


def test_highlighting_service_worker_and_tool_refuse_before_native_or_snapshot_access(tmp_path, monkeypatch):
    effects = []
    monkeypatch.setattr(autocad, "run_owned", lambda *args, **kwargs: effects.append("launch"))
    monkeypatch.setattr(autocad, "ProcessDriver", lambda: effects.append("native identity"))
    for operation in (
        lambda: autocad.highlight(None, {}),
        lambda: autocad.run_worker(tmp_path / "not-read.json", tmp_path / "not-written.json"),
    ):
        with pytest.raises(ValueError, match="standalone offline profile"):
            operation()
    handlers = {}

    def tool(**options):
        def register(fn):
            handlers[fn.__name__] = fn
            return fn

        return register

    def load(*args):
        effects.append("snapshot")
        raise AssertionError("Unavailable route must reject before lookup")

    monkeypatch.setattr(electrical_server, "ElectricalService", lambda drawings: SimpleNamespace(load=load))
    electrical_server.register(tool, None)
    with pytest.raises(ValueError, match="standalone offline profile"):
        handlers["cad_highlight_source_object"]("unknown", "unknown")
    assert effects == []


def test_status_and_capabilities_report_the_effective_profile(tmp_path):
    path, _ = configuration(tmp_path)
    status = DrawingService(Config.load(path)).status()
    assert status["execution_profile"] == report()["execution_profile"] == "offline"
    assert status["supported_extensions"] == report()["available_formats"]
    assert status["blocked_extensions"] == report()["blocked_formats"]
    assert not status["native_operations_available"] and not status["oda_available"]
    assert status["numerical_threads_per_process"] == report()["numerical_threads_per_process"] == 1


def test_numerical_pool_limits_override_ambient_values_without_an_enabling_flag(monkeypatch):
    import os

    for name in NUMERICAL_ENVIRONMENT:
        monkeypatch.setenv(name, "256")
    configure_runtime()
    assert all(os.environ[name] == "1" for name in NUMERICAL_ENVIRONMENT)


@pytest.mark.skipif(os.name != "nt", reason="Selected Windows numerical DLL regression")
def test_package_bootstrap_bounds_the_actual_numpy_pool_before_library_initialization():
    # A separate owned Python helper starts with two numerical threads requested.
    # No MCP or drawing/native engineering operation is started by this fixture.
    script = """
import ctypes,json,os,re
from pathlib import Path
for name in ('OPENBLAS_NUM_THREADS','GOTO_NUM_THREADS','OMP_NUM_THREADS','OMP_THREAD_LIMIT','MKL_NUM_THREADS','BLIS_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='2'
import autocad_mcp
import numpy as np
observed=[]
for dll in (Path(np.__file__).parent.parent/'numpy.libs').glob('*.dll'):
    for symbol in set(re.findall(rb'[A-Za-z_0-9]*openblas_get_num_threads[A-Za-z_0-9]*',dll.read_bytes())):
        try: function=getattr(ctypes.CDLL(str(dll)),symbol.decode())
        except AttributeError: continue
        function.argtypes=[];function.restype=ctypes.c_int
        observed.append(function())
values=np.ones((64,64))
assert (values@values)[0,0]==64
print(json.dumps({'actual_numerical_threads':observed}))
"""
    result = run_owned([sys.executable, "-c", script], timeout=20, check=True, capture_limit=4096)
    threads = json.loads(result.stdout)["actual_numerical_threads"]
    assert threads and set(threads) == {1}
