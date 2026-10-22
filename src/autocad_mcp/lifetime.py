"""Fail-fast instance leases and owner/stdio-pipe lifetime fences for CLI servers."""

import contextlib
import ctypes
import os
import sys
import threading
from ctypes import wintypes as w

from .coordination import Coordinator


@contextlib.contextmanager
def parent_lifetime(*, stdio=False):
    """Exit this server if its captured parent or stdio writer disappears.

    Normal transport shutdown gets three seconds. This is a termination fence,
    not a restart supervisor or proof that interrupted native work rolled back.
    No PID inventory, process-name cleanup, or external native process is used.
    """
    stop = threading.Event()
    parent_pid = os.getppid()
    parent = None
    pipe = None
    if os.name == "nt":
        import msvcrt

        import win32api
        import win32process

        parent = win32api.OpenProcess(0x101000, False, parent_pid)
        try:
            if (
                win32process.GetProcessTimes(parent)["CreationTime"]
                > win32process.GetProcessTimes(win32api.GetCurrentProcess())["CreationTime"]
            ):
                raise RuntimeError("Server parent identity expired before startup")
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            wait = kernel.WaitForSingleObject
            wait.argtypes, wait.restype = [w.HANDLE, w.DWORD], w.DWORD
            peek = kernel.PeekNamedPipe
            peek.argtypes = [
                w.HANDLE,
                ctypes.c_void_p,
                w.DWORD,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            peek.restype = w.BOOL
            file_type = kernel.GetFileType
            file_type.argtypes, file_type.restype = [w.HANDLE], w.DWORD
            if stdio:
                candidate = msvcrt.get_osfhandle(sys.stdin.fileno())
                if file_type(candidate) == 3:  # FILE_TYPE_PIPE; never consume protocol bytes.
                    pipe = candidate
        except BaseException:
            parent.Close()
            raise

    def watch():
        while not stop.wait(0.25):
            lost = wait(int(parent), 0) != 258 if parent is not None else os.getppid() != parent_pid
            if pipe is not None and not peek(pipe, None, 0, None, None, None):
                lost = lost or ctypes.get_last_error() in {6, 109, 232, 233}
            if lost:
                if not stop.wait(3):
                    # Kernel job handles close on exit; durable in-flight intent
                    # remains uncertain for later inspection, never auto-replayed.
                    os._exit(70)
                return

    thread = threading.Thread(target=watch, name="autocad-owner-watch", daemon=True)
    try:
        thread.start()
        yield
    finally:
        stop.set()
        thread.join(timeout=1)
        if parent is not None:
            parent.Close()


@contextlib.contextmanager
def server_lifetime(config, *, backend=False, stdio=False):
    coordinator = Coordinator(config.state)
    role = "backend" if backend else "owner"
    with coordinator.pool("servers:" + role, config.max_server_instances, timeout=0):
        with parent_lifetime(stdio=stdio):
            yield
