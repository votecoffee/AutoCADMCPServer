"""Win32 launch-order and cleanup fixtures using only stub functions/handles."""

import ctypes
import sys
from types import SimpleNamespace

import pytest

from autocad_mcp import owned_process
from autocad_mcp.owned_resources import OwnedResources


class Function:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


@pytest.mark.parametrize("failure", [None, "job_attribute", "creation", "identity", "resume"])
def test_windows_binds_job_and_creation_identity_before_resume_and_cleans_failures(monkeypatch, failure):
    resources, events = OwnedResources(), []
    monkeypatch.setattr(owned_process, "owned_resources", resources)

    class Job:
        def __int__(self):
            return 555

        def Close(self):
            events.append("job_close")

    job = Job()
    monkeypatch.setitem(
        sys.modules,
        "win32job",
        SimpleNamespace(
            CreateJobObject=lambda *args: job,
            QueryInformationJobObject=lambda *args: {"BasicLimitInformation": {}},
            SetInformationJobObject=lambda *args: events.append("set_limits"),
            JobObjectExtendedLimitInformation=9,
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=0x2000,
            JOB_OBJECT_LIMIT_ACTIVE_PROCESS=8,
        ),
    )
    monkeypatch.setitem(
        sys.modules, "msvcrt", SimpleNamespace(get_osfhandle=lambda descriptor: descriptor + 100)
    )
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
                raise OSError("Synthetic ownership assignment rejection")
            assert list(value) == [555]
            events.append("job_bound")
        else:
            assert attribute == 0x20002 and list(value) == [110, 111, 112]
            events.append("only_explicit_handles")
        return True

    def create(application, command, process_sa, thread_sa, inherit, flags, env, cwd, startup, info):
        assert "job_bound" in events and "only_explicit_handles" in events
        assert flags == 0x08080004 and inherit
        assert startup._obj.startup.cb == ctypes.sizeof(owned_process._StartupEx)
        assert resources.snapshot()["active"][0]["state"] == "starting"
        if failure == "creation":
            raise OSError("Synthetic creation failure")
        info._obj.process, info._obj.thread, info._obj.pid = 700, 701, 1234
        events.append("created_suspended")
        return True

    def times(process, creation, exited, kernel, user):
        assert "created_suspended" in events
        if failure == "identity":
            raise OSError("Synthetic creation-time failure")
        creation._obj.dwHighDateTime, creation._obj.dwLowDateTime = 1, 2
        return True

    def resume(thread):
        record = resources.snapshot()["active"][0]
        assert record["state"] == "bound_suspended"
        assert record["pid"] == 1234 and record["creation_identity"] == 4294967298
        events.append("resume")
        return 2 if failure == "resume" else 1

    def exit_code(process, output):
        output._obj.value = 7
        return True

    kernel = SimpleNamespace(
        **{
            name: Function(callback)
            for name, callback in {
                "InitializeProcThreadAttributeList": init,
                "UpdateProcThreadAttribute": update,
                "DeleteProcThreadAttributeList": lambda *args: events.append("attributes_deleted"),
                "CreateProcessW": create,
                "GetProcessTimes": times,
                "ResumeThread": resume,
                "WaitForSingleObject": lambda *args: 0,
                "GetExitCodeProcess": exit_code,
                "CloseHandle": lambda handle: events.append(("handle_closed", handle)),
            }.items()
        }
    )
    monkeypatch.setattr(owned_process.ctypes, "WinDLL", lambda *args, **kwargs: kernel, raising=False)
    streams = [SimpleNamespace(fileno=lambda index=index: index) for index in (10, 11, 12)]
    if failure:
        with pytest.raises((OSError, RuntimeError)):
            owned_process._windows(["trusted-worker.exe"], 10, streams, "test-worker")
    else:
        assert owned_process._windows(["trusted-worker.exe"], 10, streams, "test-worker") == 7
        assert events.index("job_bound") < events.index("created_suspended") < events.index("resume")
    assert events.count("job_close") == 1
    assert "attributes_deleted" in events
    assert resources.snapshot()["active_count"] == 0
    if failure in {"job_attribute", "creation", "identity"}:
        assert "resume" not in events
    if failure not in {"job_attribute", "creation"}:
        assert ("handle_closed", 700) in events and ("handle_closed", 701) in events
