"""Durable Win32 launch-order fixtures using only stub functions/handles."""

import ctypes
import os
import sys
from types import SimpleNamespace

import pytest
from universal_tools.resources import ResourceLedger

from autocad_mcp import owned_process
from autocad_mcp.owned_resources import OwnedResources


class Function:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


@pytest.mark.parametrize("exited", [False, True])
def test_identity_query_race_ignores_only_proven_exit_on_retained_handle(exited):
    class Handle:
        checks = 0

        def alive(self):
            self.checks += 1
            return self.checks == 1 or not exited

        @property
        def identity(self):
            raise PermissionError("Synthetic image query race")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    driver = owned_process.StreamProcessDriver.__new__(owned_process.StreamProcessDriver)
    driver._open = lambda pid: Handle()
    with pytest.raises(ProcessLookupError if exited else PermissionError):
        driver.capture(1234)


def test_transient_image_lookup_uses_one_retained_handle_and_a_bounded_retry(monkeypatch):
    opens, queries, sleeps = [], [], []

    class Handle:
        def alive(self):
            return True

        @property
        def identity(self):
            queries.append("query")
            if len(queries) == 1:
                raise PermissionError("Synthetic short-lived image-query denial")
            return {"pid": 1234, "created": "100", "executable": "verified.exe"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    driver = owned_process.StreamProcessDriver.__new__(owned_process.StreamProcessDriver)

    def opened(pid):
        opens.append(pid)
        return Handle()

    driver._open = opened
    monkeypatch.setattr(owned_process.time, "sleep", lambda value: sleeps.append(value))
    assert driver.capture(1234)["executable"] == "verified.exe"
    assert opens == [1234] and len(queries) == 2 and sleeps == [0.01]


def test_unverifiable_live_member_still_fails_after_retry_budget(monkeypatch):
    clock = iter([10.0, 10.1, 10.3])
    monkeypatch.setattr(owned_process.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(owned_process.time, "sleep", lambda value: None)

    class Handle:
        def alive(self):
            return True

        @property
        def identity(self):
            raise PermissionError("Still live and unverifiable")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    driver = owned_process.StreamProcessDriver.__new__(owned_process.StreamProcessDriver)
    driver._open = lambda pid: Handle()
    with pytest.raises(PermissionError, match="Still live and unverifiable"):
        driver.capture(1234)


@pytest.mark.parametrize("failure", [None, "job_attribute", "creation", "identity", "binding", "resume"])
def test_durable_identity_precedes_resume_and_startup_failures_close_job(tmp_path, monkeypatch, failure):
    events, alive = [], {"worker": True}
    pid = 7654321
    identity = {"host_id": "a" * 64, "pid": pid, "created": "2000", "executable": sys.executable}
    driver = owned_process.StreamProcessDriver.__new__(owned_process.StreamProcessDriver)
    driver.host_id = "a" * 64
    ledger = ResourceLedger(tmp_path, driver=driver)
    resources = OwnedResources(ledger=ledger)

    class Job:
        def __int__(self):
            return 555

        def Close(self):
            events.append("job_close")
            alive["worker"] = False

    job = Job()

    def query(job, kind):
        return {"BasicLimitInformation": {}} if kind == 9 else {"ActiveProcesses": int(alive["worker"])}

    def terminate(job, code):
        events.append("stop_tree")
        alive["worker"] = False

    monkeypatch.setitem(
        sys.modules,
        "win32job",
        SimpleNamespace(
            CreateJobObject=lambda *args: job,
            QueryInformationJobObject=query,
            SetInformationJobObject=lambda *args: events.append("set_limits"),
            TerminateJobObject=terminate,
            JobObjectExtendedLimitInformation=9,
            JobObjectBasicAccountingInformation=1,
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=0x2000,
            JOB_OBJECT_LIMIT_ACTIVE_PROCESS=8,
        ),
    )
    import msvcrt

    import win32api

    monkeypatch.setattr(win32api, "GetLastError", lambda: 0)
    monkeypatch.setattr(msvcrt, "get_osfhandle", lambda fd: fd + 100)
    monkeypatch.setattr(
        owned_process.os,
        "set_handle_inheritable",
        lambda handle, value: events.append(("inherit", handle, value)),
    )

    def init(buffer, count, flags, size):
        size._obj.value = 256
        return buffer is not None

    def update(buffer, flags, attribute, value, size, previous, returned):
        if attribute == 0x2000D:
            if failure == "job_attribute":
                raise OSError("Synthetic job rejection")
            assert list(value) == [555]
            events.append("job_bound")
        else:
            assert attribute == 0x20002 and list(value) == [110, 111, 112]
            events.append("only_explicit_handles")
        return True

    def create(application, command, psa, tsa, inherit, flags, env, cwd, startup, info):
        assert "job_bound" in events and "only_explicit_handles" in events
        assert flags == 0x08080404 and inherit
        assert startup._obj.startup.cb == ctypes.sizeof(owned_process.StartupInfoEx)
        assert ledger.records()[0].state == "launching"
        if failure == "creation":
            raise OSError("Synthetic creation failure")
        info._obj.process, info._obj.thread, info._obj.pid = 700, 701, pid
        events.append("created_suspended")
        return True

    def capture_handle(handle, observed_pid):
        if failure == "identity":
            raise OSError("Synthetic identity failure")
        return identity

    def capture(observed_pid):
        if observed_pid == os.getpid():
            return {**identity, "pid": observed_pid, "created": "1000"}
        if failure == "binding":
            raise OSError("Synthetic durable binding failure")
        return identity

    def resume(thread):
        record = ledger.records()[0]
        assert record.state == "active" and record.process.created == "2000"
        assert record.owner.pid == os.getpid() and record.process.pid == pid
        events.append("resume")
        if failure == "resume":
            raise OSError("Synthetic resume failure")
        return 1

    def members(job, kind, output, length, returned):
        output._obj.count = int(alive["worker"])
        output._obj.pids[0] = pid
        return True

    kernel = SimpleNamespace(
        **{
            name: Function(callback)
            for name, callback in {
                "InitializeProcThreadAttributeList": init,
                "UpdateProcThreadAttribute": update,
                "DeleteProcThreadAttributeList": lambda *args: events.append("attributes_deleted"),
                "CreateProcessW": create,
                "ResumeThread": resume,
                "QueryInformationJobObject": members,
                "CloseHandle": lambda handle: events.append(("handle_closed", handle)),
            }.items()
        }
    )
    driver.kernel = kernel
    driver.capture_handle, driver.capture = capture_handle, capture
    driver.state = lambda value: "alive" if value["pid"] == os.getpid() or alive["worker"] else "absent"

    class Handle:
        def terminate(self):
            pytest.fail("A job resource must use owned-tree cleanup")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    driver.open = lambda value: Handle()
    streams = [SimpleNamespace(fileno=lambda fd=fd: fd) for fd in (10, 11, 12)]
    if failure:
        with pytest.raises(OSError):
            resources.launch_worker([sys.executable], streams, "stub-worker")
        assert ledger.records()[0].state == "failed"
        assert "resume" not in events or failure == "resume"
    else:
        launch = resources.launch_worker([sys.executable], streams, "stub-worker")
        assert events.index("job_bound") < events.index("created_suspended") < events.index("resume")
        assert launch.close()["outcome"] == "terminated"
        assert ledger.records()[0].receipt.outcome == "terminated"
        assert not ledger.plan(ledger.records()[0].resource_id)["eligible"]
    assert events.count("job_close") == 1 and "attributes_deleted" in events
    if failure not in {"job_attribute", "creation"}:
        assert ("handle_closed", 700) in events and ("handle_closed", 701) in events
