"""Synthetic ownership checks. No native drawing or existing process is targeted."""

import json
import os
import signal
import subprocess
import sys
import time

import pytest

from autocad_mcp.coordination import Coordinator, ResourceBusy
from autocad_mcp.owned_process import DIAGNOSTIC_BYTES, run_owned


def wait_file(path, owner):
    deadline = time.monotonic() + 15
    while not path.exists():
        assert owner.poll() is None and time.monotonic() < deadline
        time.sleep(0.02)
    return json.loads(path.read_bytes())


def assert_exited(pid):
    import win32api
    import win32event

    try:
        process = win32api.OpenProcess(0x100000, False, pid)
    except Exception as error:
        assert error.winerror == 87  # The captured synthetic process no longer exists.
        return
    try:
        assert win32event.WaitForSingleObject(process, 5000) == 0
    finally:
        process.Close()


def test_server_slot_admission_is_immediate_and_released_on_exit(tmp_path):
    first, second = Coordinator(tmp_path), Coordinator(tmp_path)
    with first.pool("servers:owner", 1, timeout=0):
        started = time.monotonic()
        with pytest.raises(ResourceBusy):
            with second.pool("servers:owner", 1, timeout=0):
                pytest.fail("An additional owner was admitted")
        assert time.monotonic() - started < 1
    with second.pool("servers:owner", 1, timeout=0):
        pass


def test_worker_capture_is_bounded_and_failures_stay_failures():
    result = run_owned(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('x'*200000); sys.stderr.write('error'); sys.exit(7)",
        ],
        timeout=10,
        encoding="utf-8",
    )
    assert result.returncode == 7 and result.stdout == "x" * DIAGNOSTIC_BYTES
    assert result.stderr == "error"


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel ownership acceptance")
def test_timeout_terminates_owned_grandchild(tmp_path):
    child = tmp_path / "child.py"
    marker = tmp_path / "child.json"
    child.write_text(
        "import os,json,sys,time\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps(os.getpid()))\ntime.sleep(60)\n"
    )
    parent = tmp_path / "parent.py"
    parent.write_text(
        "import subprocess,sys,time\nsubprocess.Popen([sys.executable,sys.argv[1],sys.argv[2]])\ntime.sleep(60)\n"
    )
    with pytest.raises(subprocess.TimeoutExpired):
        run_owned([sys.executable, str(parent), str(child), str(marker)], timeout=5)
    assert marker.exists(), "Synthetic descendant must start before timeout"
    assert_exited(json.loads(marker.read_bytes()))


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel ownership acceptance")
def test_abrupt_owner_exit_closes_worker_job(tmp_path):
    marker, info = tmp_path / "child.json", tmp_path / "owner.json"
    child = tmp_path / "child.py"
    child.write_text(
        "import os,json,sys,time\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps(os.getpid()))\ntime.sleep(60)\n"
    )
    owner = tmp_path / "owner.py"
    owner.write_text(
        "import os,json,sys\nfrom pathlib import Path\n"
        "from autocad_mcp.owned_process import run_owned\n"
        "Path(sys.argv[1]).write_text(json.dumps(os.getpid()))\n"
        "run_owned([sys.executable,sys.argv[2],sys.argv[3]],timeout=60)\n"
    )
    process = subprocess.Popen(
        [sys.executable, str(owner), str(info), str(child), str(marker)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    actual_owner = None
    try:
        actual_owner = wait_file(info, process)
        actual_child = wait_file(marker, process)
        os.kill(actual_owner, signal.SIGTERM)
        process.wait(timeout=10)
        assert_exited(actual_child)
    finally:
        if actual_owner is not None and process.poll() is None:
            os.kill(actual_owner, signal.SIGTERM)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def test_stdio_eof_stops_cli_owner_without_handshake(drawing_service):
    service, source = drawing_service
    process = subprocess.Popen(
        [sys.executable, "-m", "autocad_mcp", "--config", str(source.parent / "config.json"), "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={
            **os.environ,
            "AUTOCAD_MCP_MANAGEMENT_REGISTRY": str(service.config.state / "private-test-registry"),
        },
    )
    try:
        process.stdin.close()
        assert process.wait(timeout=15) in {0, 70}
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


@pytest.mark.skipif(os.name != "nt", reason="Windows non-consuming pipe and kernel job fence")
def test_stdio_eof_fence_terminates_inflight_owned_child(tmp_path):
    info, marker = tmp_path / "owner.json", tmp_path / "child.json"
    child = tmp_path / "child.py"
    child.write_text(
        "import os,json,sys,time\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).write_text(json.dumps(os.getpid()))\ntime.sleep(60)\n"
    )
    owner = tmp_path / "owner.py"
    owner.write_text(
        "import os,json,sys\nfrom pathlib import Path\n"
        "from autocad_mcp.owned_process import run_owned\n"
        "from autocad_mcp.lifetime import parent_lifetime\n"
        "with parent_lifetime(stdio=True):\n"
        " Path(sys.argv[1]).write_text(json.dumps(os.getpid()))\n"
        " run_owned([sys.executable,sys.argv[2],sys.argv[3]],timeout=60)\n"
    )
    process = subprocess.Popen(
        [sys.executable, str(owner), str(info), str(child), str(marker)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    actual_owner = None
    try:
        actual_owner = wait_file(info, process)
        actual_child = wait_file(marker, process)
        process.stdin.close()
        assert process.wait(timeout=10) == 70
        assert_exited(actual_owner)
        assert_exited(actual_child)
    finally:
        if not process.stdin.closed:
            process.stdin.close()
        if actual_owner is not None and process.poll() is None:
            os.kill(actual_owner, signal.SIGTERM)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
