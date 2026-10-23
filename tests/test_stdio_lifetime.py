"""Harmless real SDK fd-claim/lifetime fixtures; never starts an MCP server."""

import ctypes
import json
import os
import sys
import time
from ctypes import wintypes as w
from pathlib import Path
from types import SimpleNamespace

import pytest
from universal_tools.resources import ResourceLedger

from autocad_mcp import lifetime
from autocad_mcp.owned_process import StreamProcessDriver
from autocad_mcp.worker_capture import Captures

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows pipe-handle lifetime contract")

BOOT = """
import os,sys,site,json,time,threading
from pathlib import Path
site.addsitedir(os.environ['AUTOCAD_TEST_SITE'])
from autocad_mcp.owned_process import StreamProcessDriver
from autocad_mcp.lifetime import parent_lifetime
from mcp.server.stdio import _claim_fd,_open_stdin_diversion
driver=StreamProcessDriver()
def save(path,value):
    path=Path(path);temporary=path.with_suffix('.pending');temporary.write_text(json.dumps(value))
    for attempt in range(40):
        try:temporary.replace(path);return
        except PermissionError:time.sleep(.005)
    raise RuntimeError('Private heartbeat remained locked')
"""

DIVERT = (
    BOOT
    + """
marker=Path(sys.argv[1]); started=time.monotonic()
with parent_lifetime(stdio=True):
    wire,release=_claim_fd(0,sys.stdin,'rb',_open_stdin_diversion)
    while True:
        save(marker,{'identity':driver.capture(os.getpid()),'elapsed':time.monotonic()-started,'wire_fd':wire.fileno(),'fence_source':parent_lifetime.__code__.co_filename})
        time.sleep(.05)
"""
)

BLOCKED_CHILD = (
    BOOT
    + """
marker=Path(sys.argv[1])
with parent_lifetime(stdio=True):
    wire,release=_claim_fd(0,sys.stdin,'rb',_open_stdin_diversion)
    started=threading.Event()
    def read():
        started.set();wire.read(1)
    reader=threading.Thread(target=read,daemon=True);reader.start();started.wait()
    save(marker,{'identity':driver.capture(os.getpid()),'parent':driver.capture(os.getppid()),'blocking_reader_started':True})
    while True:time.sleep(.1)
"""
)

PARENT = (
    BOOT
    + """
import subprocess
child=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]],stdin=sys.stdin,stdout=sys.stdout,stderr=sys.stderr)
while True:time.sleep(.1)
"""
)


def launch_fixture(tmp_path, script, *args):
    driver = StreamProcessDriver()
    owner = ResourceLedger(tmp_path / "registry", driver=driver).owner("autocad-stdio-fixture")
    read_fd, write_fd = os.pipe()
    reader, writer = os.fdopen(read_fd, "rb", buffering=0), os.fdopen(write_fd, "wb", buffering=0)
    captures = Captures(4096).__enter__()
    env = {**os.environ, "AUTOCAD_TEST_SITE": str(Path(sys.prefix) / "Lib/site-packages")}
    try:
        launch = owner.launch(
            [sys._base_executable, "-c", script, *map(str, args)],
            "Harmless SDK fd-claim fence",
            allow_termination=True,
            streams=(reader, *captures.writers),
            env=env,
            max_processes=8,
        )
        captures.close_parent_writers()
        reader.close()
        return driver, owner, launch, writer, captures
    except BaseException:
        reader.close()
        writer.close()
        captures.finish()
        owner.close()
        raise


def wait_marker(path, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_bytes())
        time.sleep(0.02)
    raise TimeoutError("Harmless child did not publish its exact identity")


def code(driver, handle):
    value = w.DWORD()
    assert driver.kernel.GetExitCodeProcess(int(handle), ctypes.byref(value))
    return value.value


def retain_fixture_result(tmp_path, owner, captures):
    (tmp_path / "fixture-diagnostics.json").write_text(
        json.dumps(
            {
                "stderr": captures.buffers[1].value("utf-8", "replace"),
                "records": [record.model_dump(mode="json") for record in owner.ledger.records()],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_sdk_fd_diversion_preserves_live_wire_then_true_eof_exits(tmp_path):
    marker = tmp_path / "child.json"
    driver, owner, launch, writer, captures = launch_fixture(tmp_path, DIVERT, marker)
    observed = None
    try:
        state = wait_marker(marker)
        observed = driver.open(state["identity"])
        deadline = time.monotonic() + 6
        while state["elapsed"] < 3.7:
            assert observed.alive(), "fd0 diversion must not masquerade as EOF"
            assert time.monotonic() < deadline
            time.sleep(0.05)
            state = wait_marker(marker)
        assert not writer.closed and observed.alive()
        before_eof = dict(state)
        eof_at = time.monotonic()
        writer.close()
        assert observed.wait(5000)
        exit_code = code(driver, observed.handle)
        assert exit_code == 70
        (tmp_path / "fixture-outcome.json").write_text(
            json.dumps(
                {
                    "before_real_eof": before_eof,
                    "true_writer_close": True,
                    "exit_code": exit_code,
                    "exit_after_eof_seconds": time.monotonic() - eof_at,
                    "self_exit_before_outer_cleanup": True,
                    "mcp_started": False,
                },
                indent=2,
            )
            + "\n"
        )
        receipt = launch.close()
        launch = None
        assert receipt["outcome"] in {"terminated", "already_exited"}
    finally:
        if launch is not None:
            launch.close()
        if not writer.closed:
            writer.close()
        if observed is not None:
            observed.close()
        captures.finish()
        owner.close()
        retain_fixture_result(tmp_path, owner, captures)


def test_parent_death_exits_with_sdk_blocking_reader_and_external_writer_held(tmp_path):
    marker = tmp_path / "child.json"
    driver, owner, launch, writer, captures = launch_fixture(tmp_path, PARENT, BLOCKED_CHILD, marker)
    child, parent = None, None
    try:
        state = wait_marker(marker)
        assert state["blocking_reader_started"]
        child = driver.open(state["identity"])
        parent = driver.open(state["parent"])
        assert state["parent"] == launch.group.identity
        time.sleep(0.3)
        parent_killed_at = time.monotonic()
        parent.terminate()
        assert parent.wait(2000) and not writer.closed
        # The outer job is deliberately still open. Only the app's independent
        # parent watcher can make this natural code70 exit before outer cleanup.
        assert child.wait(6000)
        exit_code = code(driver, child.handle)
        assert exit_code == 70
        assert not writer.closed
        (tmp_path / "fixture-outcome.json").write_text(
            json.dumps(
                {
                    **state,
                    "exit_code": exit_code,
                    "external_writer_still_held": not writer.closed,
                    "self_exit_before_outer_cleanup": True,
                    "parent_death_to_exit_seconds": time.monotonic() - parent_killed_at,
                    "mcp_started": False,
                },
                indent=2,
            )
            + "\n"
        )
        receipt = launch.close()
        launch = None
        assert receipt["outcome"] in {"terminated", "already_exited"}
    finally:
        if launch is not None:
            launch.close()
        writer.close()
        if child is not None:
            child.close()
        if parent is not None:
            parent.close()
        captures.finish()
        owner.close()
        retain_fixture_result(tmp_path, owner, captures)


class Function:
    def __init__(self, fn):
        self.fn = fn

    def __call__(self, *args):
        return self.fn(*args)


@pytest.mark.parametrize("failure", [None, "duplicate", "parent_thread", "pipe_thread", "body"])
def test_monitor_duplicate_is_noninherited_and_owned_once_even_on_partial_start(monkeypatch, failure):
    events = []

    class Handle:
        def __init__(self, name):
            self.name = name

        def __int__(self):
            return 200

        def Close(self):
            events.append(("close", self.name))

    parent, pipe = Handle("parent"), Handle("pipe")

    def duplicate(*args):
        events.append(("duplicate", args[3:]))
        if failure == "duplicate":
            raise OSError("Synthetic duplication failure")
        return pipe

    class Thread:
        def __init__(self, *, target, name, daemon):
            self.name = name
            assert daemon

        def start(self):
            events.append(("start", self.name))
            if (failure == "parent_thread" and self.name == "autocad-owner-watch") or (
                failure == "pipe_thread" and self.name == "autocad-stdin-watch"
            ):
                raise RuntimeError("Synthetic thread admission failure")

        def join(self, timeout):
            events.append(("join", self.name))
            assert timeout == 1

    kernel = SimpleNamespace(
        WaitForSingleObject=Function(lambda *args: 258),
        PeekNamedPipe=Function(lambda *args: True),
        GetFileType=Function(lambda *args: 3),
    )
    monkeypatch.setattr(lifetime.ctypes, "WinDLL", lambda *args, **kwargs: kernel)
    monkeypatch.setattr(lifetime.threading, "Thread", Thread)
    monkeypatch.setattr(lifetime.sys, "stdin", SimpleNamespace(fileno=lambda: 0))
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(get_osfhandle=lambda fd: 100))
    monkeypatch.setitem(
        sys.modules,
        "win32api",
        SimpleNamespace(
            OpenProcess=lambda *args: parent, GetCurrentProcess=lambda: 1, DuplicateHandle=duplicate
        ),
    )
    monkeypatch.setitem(
        sys.modules, "win32process", SimpleNamespace(GetProcessTimes=lambda handle: {"CreationTime": 1})
    )

    def exercise():
        with lifetime.parent_lifetime(stdio=True):
            if failure == "body":
                raise ValueError("Synthetic scope failure")

    if failure:
        with pytest.raises((OSError, RuntimeError, ValueError)):
            exercise()
    else:
        exercise()
    assert ("duplicate", (0, False, 2)) in events
    assert events.count(("close", "parent")) == 1
    assert events.count(("close", "pipe")) == (0 if failure == "duplicate" else 1)
    joined = [event for event in events if event[0] == "join"]
    assert len(joined) == (
        0 if failure in {"duplicate", "parent_thread"} else 1 if failure == "pipe_thread" else 2
    )
