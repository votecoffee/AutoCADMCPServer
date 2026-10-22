"""Private worker-file streams around the shared durable Windows ownership API.

This is not an MCP stdio launcher. Only bounded private capture pipes and disconnected
stdin are inherited; the existing SDK transport remains separate.
"""

import ctypes
import json
import os
import re
import signal
import subprocess
import time
from ctypes import wintypes as w
from pathlib import Path

from universal_tools.windows_resources import (
    ContainedProcess,
    ProcessDriver,
    ProcessInfo,
    StartupInfoEx,
    checked,
)

from .owned_resources import owned_resources
from .worker_capture import Captures

DIAGNOSTIC_BYTES = 65_536
TREE_ENV = "AUTOCAD_MCP_OWNED_TREE"


class StreamProcessDriver(ProcessDriver):
    """Equivalent atomic job creation, adding only private capture-handle streams."""

    def __init__(self):
        super().__init__()
        if self.kernel:
            self.kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
            self.kernel.GetExitCodeProcess.restype = w.BOOL

    def capture(self, pid):
        # Short-lived launchers can exit after the first wait but before image
        # lookup. Ignore only an exit proven on this same retained OS handle.
        with self._open(pid) as handle:
            if not handle.alive():
                raise ProcessLookupError("Owned member already exited")
            try:
                return handle.identity
            except OSError:
                if not handle.alive():
                    raise ProcessLookupError("Owned member exited during identity capture") from None
                raise

    def create_suspended(self, argv, *, streams=None, env=None, max_processes=8, job_name=None):
        if streams is None:
            return super().create_suspended(argv, env=env, max_processes=max_processes)
        self._require_windows()
        import msvcrt

        import win32api
        import win32job

        if not isinstance(argv, (tuple, list)) or not 1 <= len(argv) <= 256:
            raise ValueError("Use bounded trusted worker argv")
        if any(not isinstance(value, str) or "\0" in value for value in argv):
            raise ValueError("Invalid worker arguments")
        if not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file():
            raise ValueError("Use an existing absolute worker executable")
        if type(max_processes) is not int or not 1 <= max_processes <= 8 or len(streams) != 3:
            raise ValueError("Invalid private worker bounds")
        command = subprocess.list2cmdline(argv)
        if len(command.encode("utf-16-le")) > 65532:
            raise ValueError("Worker command exceeds Windows limit")
        environment = None
        if env is not None:
            if not isinstance(env, dict) or any(
                not isinstance(key, str)
                or not key
                or "=" in key
                or "\0" in key
                or not isinstance(value, str)
                or "\0" in value
                for key, value in env.items()
            ):
                raise ValueError("Invalid worker environment")
            block = "\0".join(
                f"{key}={value}" for key, value in sorted(env.items(), key=lambda row: row[0].upper())
            )
            if len(block.encode("utf-16-le")) > 2 * 1024 * 1024:
                raise ValueError("Worker environment exceeds budget")
            environment = ctypes.create_unicode_buffer(block + "\0\0")
        job = win32job.CreateJobObject(None, job_name or "")
        if job_name and win32api.GetLastError() == 183:
            job.Close()
            raise ValueError("Named worker containment already exists; ownership not adopted")
        ready, info, handles = False, None, []
        kernel = self.kernel
        try:
            limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
            limits["BasicLimitInformation"]["LimitFlags"] = (
                win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            )
            limits["BasicLimitInformation"]["ActiveProcessLimit"] = max_processes
            win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
            size = ctypes.c_size_t()
            kernel.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
            if not size.value:
                raise ctypes.WinError(ctypes.get_last_error())
            attributes = ctypes.create_string_buffer(size.value)
            checked(kernel.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(size)))
            ready = True
            handles = [msvcrt.get_osfhandle(stream.fileno()) for stream in streams]
            for handle in handles:
                os.set_handle_inheritable(handle, True)
            inherited = (w.HANDLE * 3)(*handles)
            jobs = (w.HANDLE * 1)(int(job))
            checked(
                kernel.UpdateProcThreadAttribute(
                    attributes, 0, 0x20002, inherited, ctypes.sizeof(inherited), None, None
                )
            )
            checked(
                kernel.UpdateProcThreadAttribute(
                    attributes, 0, 0x2000D, jobs, ctypes.sizeof(jobs), None, None
                )
            )
            startup = StartupInfoEx()
            startup.startup.cb = ctypes.sizeof(startup)
            startup.startup.dwFlags = 0x100
            startup.startup.hStdInput, startup.startup.hStdOutput, startup.startup.hStdError = handles
            startup.attributes = ctypes.cast(attributes, ctypes.c_void_p)
            info = ProcessInfo()
            checked(
                kernel.CreateProcessW(
                    argv[0],
                    ctypes.create_unicode_buffer(command),
                    None,
                    None,
                    True,
                    0x08080404,
                    environment,
                    None,
                    ctypes.byref(startup),
                    ctypes.byref(info),
                )
            )
            return ContainedProcess(self, job, info)
        except BaseException:
            job.Close()
            if info is not None:
                for handle in (info.thread, info.process):
                    if handle:
                        kernel.CloseHandle(handle)
            raise
        finally:
            for handle in handles:
                os.set_handle_inheritable(handle, False)
            if ready:
                kernel.DeleteProcThreadAttributeList(attributes)


def inherited_tree(driver):
    """Validate a temporary helper's membership in its exact durable parent tree.

    Helpers do not become replacement resource owners. The parent record plus the
    actual named kernel job must both match before any nested converter starts.
    """
    raw = os.environ.get(TREE_ENV)
    if not raw:
        return None
    if len(raw) > 8192:
        raise ValueError("Invalid inherited resource context")
    context = json.loads(raw)
    token = context.get("job_token", "")
    if not re.fullmatch("[0-9a-f]{32}", token):
        raise ValueError("Invalid inherited resource identity")
    from universal_tools.resources import ResourceLedger

    records = ResourceLedger(context["registry"], driver=driver).records()
    matches = [
        record
        for record in records
        if record.owner_id == context["owner_id"]
        and record.owner.model_dump(mode="json") == context["owner"]
        and record.label == context["label"]
        and record.state == "active"
        and record.ownership == "private"
        and record.containment == "windows_job"
    ]
    if len(matches) != 1 or driver.state(context["owner"]) != "alive":
        raise ValueError("Inherited supervisor resource is unavailable; no orphan adoption")
    kernel = driver.kernel
    kernel.OpenJobObjectW.argtypes, kernel.OpenJobObjectW.restype = [w.DWORD, w.BOOL, w.LPCWSTR], w.HANDLE
    kernel.IsProcessInJob.argtypes = [w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL)]
    kernel.IsProcessInJob.restype = w.BOOL
    job = checked(kernel.OpenJobObjectW(4, False, "Local\\AutoCADMCP-" + token))
    try:
        member = w.BOOL()
        checked(kernel.IsProcessInJob(w.HANDLE(-1), job, ctypes.byref(member)))
        if not member.value:
            raise ValueError("Temporary helper is outside its recorded supervisor's containment")
    finally:
        kernel.CloseHandle(job)
    return matches[0]


def run_owned(
    args,
    *,
    timeout,
    check=False,
    encoding=None,
    errors="strict",
    resource_kind="worker",
    on_poll=None,
    capture_limit=DIAGNOSTIC_BYTES,
):
    """Run trusted worker argv with durable ownership, bounded diagnostic tails and deadlines."""
    if not args or timeout <= 0:
        raise ValueError("An explicit worker command and positive deadline are required")
    if type(capture_limit) is not int or not 1 <= capture_limit <= 2 * 1024 * 1024:
        raise ValueError("Invalid private worker capture budget")
    args = [os.fspath(item) for item in args]
    with Captures(capture_limit) as capture:
        try:
            if os.name == "nt":
                driver = StreamProcessDriver()
                parent_tree = inherited_tree(driver)
                if parent_tree is None:
                    launch = owned_resources.launch_worker(args, capture.streams, resource_kind)
                    group = launch.group
                    driver = group.driver
                else:
                    # The durable parent tree owns this nested converter and all
                    # its descendants; no temporary registration helper becomes owner.
                    launch = None
                    group = driver.create_suspended(args, streams=capture.streams, max_processes=8)
                    try:
                        group.resume()
                    except BaseException:
                        group.close()
                        raise
                capture.close_parent_writers()
                deadline, refresh = time.monotonic() + timeout, 0.0
                try:
                    while True:
                        if on_poll:
                            on_poll()
                        state = driver.kernel.WaitForSingleObject(group.info.process, 100)
                        if state == 0:
                            break
                        if state != 258:
                            raise OSError("Owned worker wait failed")
                        if time.monotonic() >= deadline:
                            raise subprocess.TimeoutExpired(args, timeout)
                        if launch and time.monotonic() >= refresh:
                            launch.refresh()
                            refresh = time.monotonic() + 1
                    if on_poll:
                        on_poll()
                    code = w.DWORD()
                    checked(driver.kernel.GetExitCodeProcess(group.info.process, ctypes.byref(code)))
                    returncode = code.value
                finally:
                    if launch:
                        launch.close()
                    else:
                        try:
                            group.stop()
                        finally:
                            group.close()
            else:
                process = subprocess.Popen(
                    args,
                    stdin=capture.streams[0],
                    stdout=capture.streams[1],
                    stderr=capture.streams[2],
                    start_new_session=True,
                )
                capture.close_parent_writers()
                try:
                    returncode = process.wait(timeout=timeout)
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
        except subprocess.TimeoutExpired as error:
            capture.finish()
            error.output, error.stderr = (buffer.value(encoding, errors) for buffer in capture.buffers)
            raise
        capture.finish()
        result = subprocess.CompletedProcess(
            args,
            returncode,
            *(buffer.value(encoding, errors) for buffer in capture.buffers),
        )
        result.stdout_truncated, result.stderr_truncated = (buffer.truncated for buffer in capture.buffers)
        if check:
            result.check_returncode()
        return result
