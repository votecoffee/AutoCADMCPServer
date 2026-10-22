"""Bounded worker diagnostics and kernel ownership of Windows worker descendants.

Windows 10+ job-list attributes bind ownership at creation, before any child code
can run. Failure to establish ownership rejects launch; there is no plain-Popen
fallback. Only app-created workers belong to the job, never an attached CAD app.
"""

import ctypes
import os
import signal
import subprocess
import tempfile
import threading
from contextlib import ExitStack
from ctypes import wintypes as w

from .owned_resources import owned_resources

DIAGNOSTIC_BYTES = 65_536


def _tail(stream, encoding, errors):
    stream.seek(max(0, stream.seek(0, os.SEEK_END) - DIAGNOSTIC_BYTES))
    data = stream.read()
    return data.decode(encoding, errors) if encoding else data


class _Startup(ctypes.Structure):
    _fields_ = [
        ("cb", w.DWORD),
        ("reserved", w.LPWSTR),
        ("desktop", w.LPWSTR),
        ("title", w.LPWSTR),
        ("x", w.DWORD),
        ("y", w.DWORD),
        ("width", w.DWORD),
        ("height", w.DWORD),
        ("chars_x", w.DWORD),
        ("chars_y", w.DWORD),
        ("fill", w.DWORD),
        ("flags", w.DWORD),
        ("show", w.WORD),
        ("reserved_size", w.WORD),
        ("reserved_data", ctypes.POINTER(w.BYTE)),
        ("stdin", w.HANDLE),
        ("stdout", w.HANDLE),
        ("stderr", w.HANDLE),
    ]


class _StartupEx(ctypes.Structure):
    _fields_ = [("startup", _Startup), ("attributes", ctypes.c_void_p)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [("process", w.HANDLE), ("thread", w.HANDLE), ("pid", w.DWORD), ("tid", w.DWORD)]


def _windows(args, timeout, streams, kind):
    import msvcrt

    import win32job

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    init = kernel.InitializeProcThreadAttributeList
    init.argtypes = [ctypes.c_void_p, w.DWORD, w.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    init.restype = w.BOOL
    update = kernel.UpdateProcThreadAttribute
    update.argtypes = [
        ctypes.c_void_p,
        w.DWORD,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    update.restype = w.BOOL
    delete = kernel.DeleteProcThreadAttributeList
    delete.argtypes = [ctypes.c_void_p]
    create = kernel.CreateProcessW
    create.argtypes = [
        w.LPCWSTR,
        w.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        w.BOOL,
        w.DWORD,
        ctypes.c_void_p,
        w.LPCWSTR,
        ctypes.POINTER(_StartupEx),
        ctypes.POINTER(_ProcessInfo),
    ]
    create.restype = w.BOOL
    wait = kernel.WaitForSingleObject
    wait.argtypes = [w.HANDLE, w.DWORD]
    wait.restype = w.DWORD
    code = kernel.GetExitCodeProcess
    code.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    code.restype = w.BOOL
    close = kernel.CloseHandle
    close.argtypes = [w.HANDLE]
    close.restype = w.BOOL
    times = kernel.GetProcessTimes
    times.argtypes = [w.HANDLE, *([ctypes.POINTER(w.FILETIME)] * 4)]
    times.restype = w.BOOL
    resume = kernel.ResumeThread
    resume.argtypes, resume.restype = [w.HANDLE], w.DWORD

    def checked(success):
        if not success:
            raise ctypes.WinError(ctypes.get_last_error())

    job = win32job.CreateJobObject(None, None)
    job_guard = threading.Lock()
    job_closed = False

    def stop_job():
        nonlocal job_closed
        with job_guard:
            if not job_closed:
                job.Close()
                job_closed = True

    attributes_ready = False
    resource_id = None
    info = _ProcessInfo()
    handles = []
    try:
        limits = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        limits["BasicLimitInformation"]["LimitFlags"] = (
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | win32job.JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        )
        limits["BasicLimitInformation"]["ActiveProcessLimit"] = 8
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, limits)
        resource_id = owned_resources.register(stop_job, kind)
        size = ctypes.c_size_t()
        init(None, 2, 0, ctypes.byref(size))
        if not size.value:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(size.value)
        checked(init(buffer, 2, 0, ctypes.byref(size)))
        attributes_ready = True
        handles = [msvcrt.get_osfhandle(stream.fileno()) for stream in streams]
        for handle in handles:
            os.set_handle_inheritable(handle, True)
        inherited = (w.HANDLE * len(handles))(*handles)
        jobs = (w.HANDLE * 1)(int(job))
        # PROC_THREAD_ATTRIBUTE_HANDLE_LIST and PROC_THREAD_ATTRIBUTE_JOB_LIST.
        checked(update(buffer, 0, 0x20002, inherited, ctypes.sizeof(inherited), None, None))
        checked(update(buffer, 0, 0x2000D, jobs, ctypes.sizeof(jobs), None, None))
        startup = _StartupEx()
        startup.startup.cb = ctypes.sizeof(startup)
        startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
        startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = handles
        startup.attributes = ctypes.cast(buffer, ctypes.c_void_p)
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
        checked(
            create(
                args[0],
                command,
                None,
                None,
                True,
                0x08080004,  # NO_WINDOW | EXTENDED_STARTUPINFO_PRESENT | CREATE_SUSPENDED
                None,
                None,
                ctypes.byref(startup),
                ctypes.byref(info),
            )
        )
        creation, exited, cpu_kernel, cpu_user = (w.FILETIME() for _ in range(4))
        checked(
            times(
                info.process,
                ctypes.byref(creation),
                ctypes.byref(exited),
                ctypes.byref(cpu_kernel),
                ctypes.byref(cpu_user),
            )
        )
        owned_resources.started(
            resource_id, info.pid, (creation.dwHighDateTime << 32) | creation.dwLowDateTime, suspended=True
        )
        previous_count = resume(info.thread)
        if previous_count != 1:
            raise RuntimeError("Owned worker did not resume from its expected suspended state")
        owned_resources.resumed(resource_id)
        for handle in handles:
            os.set_handle_inheritable(handle, False)
        result = wait(info.process, min(int(timeout * 1000), 0xFFFFFFFE))
        if result == 258:  # WAIT_TIMEOUT
            raise subprocess.TimeoutExpired(args, timeout)
        if result != 0:
            raise ctypes.WinError(ctypes.get_last_error())
        exit_code = w.DWORD()
        checked(code(info.process, ctypes.byref(exit_code)))
        return exit_code.value
    finally:
        # Last noninherited job handle closes even on owner death; descendants
        # cannot retain stdout pipes or a converter after this scope ends.
        try:
            stop_job()
        except BaseException:
            if resource_id is not None:
                owned_resources.unconfirmed(resource_id)
            raise
        finally:
            with ExitStack() as cleanup:
                if resource_id is not None and job_closed:
                    cleanup.callback(owned_resources.finished, resource_id)
                if attributes_ready:
                    cleanup.callback(delete, buffer)
                for handle in handles:
                    cleanup.callback(os.set_handle_inheritable, handle, False)
                if info.thread:
                    cleanup.callback(close, info.thread)
                if info.process:
                    cleanup.callback(close, info.process)
                    wait(info.process, 5000)


def run_owned(args, *, timeout, check=False, encoding=None, errors="strict", resource_kind="worker"):
    """Run trusted app argv with disconnected stdin and 64 KiB diagnostic tails.

    Windows owns the full child job, including on abrupt parent exit. The POSIX
    fallback cleans its process group on return/timeout; abrupt-parent cleanup
    there is outside this Windows app's acceptance profile.
    """
    if not args or timeout <= 0:
        raise ValueError("An explicit worker command and positive deadline are required")
    args = [os.fspath(item) for item in args]
    with open(os.devnull, "rb") as incoming, tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            if os.name == "nt":
                returncode = _windows(args, timeout, (incoming, out, err), resource_kind)
            else:
                process = subprocess.Popen(
                    args, stdin=incoming, stdout=out, stderr=err, start_new_session=True
                )
                try:
                    returncode = process.wait(timeout=timeout)
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
        except subprocess.TimeoutExpired as error:
            error.output, error.stderr = _tail(out, encoding, errors), _tail(err, encoding, errors)
            raise
        result = subprocess.CompletedProcess(
            args, returncode, _tail(out, encoding, errors), _tail(err, encoding, errors)
        )
        if check:
            result.check_returncode()
        return result
