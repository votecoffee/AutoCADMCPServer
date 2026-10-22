"""Synthetic ownership checks. No native drawing or existing process is targeted."""

import json
import os
import subprocess
import sys
import time
import uuid

import pytest

from autocad_mcp.coordination import Coordinator, ResourceBusy
from autocad_mcp.owned_process import DIAGNOSTIC_BYTES, run_owned

IDENTITY_WRITER = (
    "from universal_tools.windows_resources import ProcessDriver\n"
    "def identity_file(name):\n"
    " p=Path(name); t=p.with_suffix('.tmp'); t.write_text(json.dumps(ProcessDriver().capture(os.getpid()))); t.replace(p)\n"
)


def wait_file(path, owner):
    deadline = time.monotonic() + 15
    while not path.exists():
        assert owner.poll() is None and time.monotonic() < deadline
        time.sleep(0.02)
    return json.loads(path.read_bytes())


def assert_exited(identity):
    from universal_tools.windows_resources import ProcessDriver

    driver, deadline = ProcessDriver(), time.monotonic() + 5
    while driver.state(identity) not in {"absent", "different"}:
        assert time.monotonic() < deadline, "Captured synthetic process did not exit"
        time.sleep(0.02)


def stop_captured(identity):
    from universal_tools.windows_resources import ProcessDriver

    driver = ProcessDriver()
    if driver.state(identity) in {"absent", "different"}:
        return
    try:
        with driver.open(identity) as process:
            process.terminate()
            assert process.wait(5000)
    except ProcessLookupError:
        pass


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
    assert result.stdout_truncated and not result.stderr_truncated


@pytest.mark.skipif(os.name != "nt", reason="Windows named-job membership and durable parent ownership")
def test_nested_helper_retains_the_actual_supervisor_as_sole_owner(tmp_path, monkeypatch):
    from autocad_mcp import owned_process
    from autocad_mcp.owned_resources import OwnedResources

    resources = OwnedResources(tmp_path / "registry")
    monkeypatch.setattr(owned_process, "owned_resources", resources)
    inner = (
        "from autocad_mcp.owned_process import inherited_tree,StreamProcessDriver; "
        "print(inherited_tree(StreamProcessDriver()).owner.pid)"
    )
    helper = tmp_path / "nested.py"
    helper.write_text(
        "import sys\nfrom autocad_mcp.owned_process import run_owned\n"
        "result=run_owned([sys.executable,'-c',sys.argv[1]],timeout=10,encoding='utf-8')\n"
        "assert result.returncode==0,result.stderr\nprint(result.stdout.strip())\n"
    )
    result = run_owned([sys.executable, str(helper), inner], timeout=15, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(os.getpid())
    records = resources.ledger.records()
    assert len(records) == 1 and records[0].owner.pid == os.getpid()
    assert records[0].state == "terminated" and records[0].receipt.outcome == "terminated"
    assert resources.snapshot()["active_count"] == 0


@pytest.mark.skipif(
    os.name != "nt", reason="Harmless Python attachment stands in for protected user software"
)
def test_protected_attachment_survives_owner_close_and_uncertain_detach(tmp_path):
    from autocad_mcp.owned_resources import OwnedResources

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    resources = OwnedResources(tmp_path / "registry")
    try:
        record = resources.attach(process.pid)
        assert record.ownership == "attached" and record.cleanup_mode == "report"
        resources.close()
        assert process.poll() is None
        assert not resources.ledger.plan(record.resource_id)["eligible"]
        detached = resources.detach(record.resource_id, uncertain=True)
        assert detached.state == "released" and detached.recovery_barrier
        assert process.poll() is None
        assert not resources.ledger.plan(record.resource_id)["eligible"]
    finally:
        # Popen retains this fixture's original process handle, independent of PID reuse.
        process.terminate()
        process.wait(timeout=10)


@pytest.mark.skipif(os.name != "nt", reason="Windows kernel ownership acceptance")
def test_timeout_terminates_owned_grandchild(tmp_path):
    child = tmp_path / "child.py"
    marker = tmp_path / "child.json"
    child.write_text(
        "import os,json,sys,time\nfrom pathlib import Path\n"
        + IDENTITY_WRITER
        + "identity_file(sys.argv[1])\ntime.sleep(60)\n"
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
        "import os,json,sys,time\nfrom pathlib import Path\n"
        + IDENTITY_WRITER
        + "identity_file(sys.argv[1])\ntime.sleep(60)\n"
    )
    owner = tmp_path / "owner.py"
    owner.write_text(
        "import os,json,sys\nfrom pathlib import Path\n"
        "from autocad_mcp.owned_process import run_owned\n" + IDENTITY_WRITER + "identity_file(sys.argv[1])\n"
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
        stop_captured(actual_owner)
        process.wait(timeout=10)
        assert_exited(actual_child)
        from universal_tools.resources import ResourceLedger

        ledger = ResourceLedger(os.environ["AUTOCAD_MCP_MANAGEMENT_REGISTRY"])
        record = next(row for row in ledger.records() if row.owner.model_dump(mode="json") == actual_owner)
        plan = ledger.plan(record.resource_id)
        assert plan["eligible"] and plan["owner_state"] == "absent"
        receipt = ledger.cleanup(record.resource_id, record.revision, uuid.uuid4().hex)
        assert receipt["outcome"] == "already_exited"
        assert ledger.get(record.resource_id).receipt.outcome == "already_exited"
    finally:
        if actual_owner is not None and process.poll() is None:
            stop_captured(actual_owner)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


@pytest.mark.skipif(os.name != "nt", reason="Harmless Windows suspended-start owner-death fixtures")
@pytest.mark.parametrize("stage", ["before_bind", "before_resume"])
def test_owner_death_before_binding_or_resume_never_executes_child(tmp_path, stage):
    from universal_tools.resources import ResourceLedger

    info, marker = tmp_path / "ready.json", tmp_path / "must-not-run.txt"
    registry = tmp_path / "registry"
    helper = tmp_path / "suspended_owner.py"
    helper.write_text(
        "import json,sys,time,os\nfrom pathlib import Path\n"
        "from autocad_mcp import owned_process\n"
        "from autocad_mcp.owned_resources import OwnedResources\n"
        "r=OwnedResources(sys.argv[1]); owned_process.owned_resources=r\n"
        "owner=r._owner(); original=owner.ledger.driver.create_suspended\n"
        "def pause(group):\n"
        " p=Path(sys.argv[2]); t=p.with_suffix('.tmp'); t.write_text(json.dumps({'owner':owner.identity.model_dump(mode='json'),'child':group.identity})); t.replace(p); time.sleep(60)\n"
        "def create(*args,**kwargs):\n"
        " group=original(*args,**kwargs)\n"
        " if sys.argv[3]=='before_bind': pause(group)\n"
        " else:\n"
        "  resume=group.resume\n"
        "  def paused_resume():\n   pause(group)\n   resume()\n"
        "  group.resume=paused_resume\n"
        " return group\n"
        "owner.ledger.driver.create_suspended=create\n"
        "owned_process.run_owned([sys.executable,'-c',\"from pathlib import Path; import sys; Path(sys.argv[1]).write_text('must-not-execute')\",sys.argv[4]],timeout=60)\n"
    )
    process = subprocess.Popen(
        [sys.executable, str(helper), str(registry), str(info), stage, str(marker)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    observed = None
    try:
        observed = wait_file(info, process)
        stop_captured(observed["owner"])
        process.wait(timeout=10)
        assert_exited(observed["child"])
        assert not marker.exists()
        ledger = ResourceLedger(registry)
        record = ledger.records()[0]
        assert record.owner.model_dump(mode="json") == observed["owner"]
        assert record.state == ("launching" if stage == "before_bind" else "active")
        if stage == "before_bind":
            assert record.process is None and not ledger.plan(record.resource_id)["eligible"]
        else:
            assert record.process.model_dump(mode="json") == observed["child"]
    finally:
        if observed is not None and process.poll() is None:
            stop_captured(observed["owner"])
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
        + IDENTITY_WRITER
        + "identity_file(sys.argv[1])\ntime.sleep(60)\n"
    )
    owner = tmp_path / "owner.py"
    owner.write_text(
        "import os,json,sys\nfrom pathlib import Path\n"
        "from autocad_mcp.owned_process import run_owned\n"
        "from autocad_mcp.lifetime import parent_lifetime\n"
        + IDENTITY_WRITER
        + "with parent_lifetime(stdio=True):\n"
        " identity_file(sys.argv[1])\n"
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
            stop_captured(actual_owner)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
