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
                    # SDK 2.3 claims fd 0 and diverts the CRT descriptor to NUL.
                    # Retain our own non-inherited wire handle before that claim;
                    # a borrowed CRT handle would become invalid or be recycled.
                    current = win32api.GetCurrentProcess()
                    pipe = win32api.DuplicateHandle(current, candidate, current, 0, False, 2)
        except BaseException:
            if pipe is not None:
                pipe.Close()
            parent.Close()
            raise

    def lost_owner():
        if not stop.wait(3):
            # Only this server exits; kernel jobs close and interrupted intent
            # stays uncertain. A native/user-owned process is never targeted.
            os._exit(70)

    def watch_parent():
        while not stop.wait(0.25):
            lost = wait(int(parent), 0) != 258 if parent is not None else os.getppid() != parent_pid
            if lost:
                lost_owner()
                return

    def watch_pipe():
        # A synchronous pipe query can wait behind a reader. It must never block
        # the independent parent-loss watcher, including an inherited writer.
        while not stop.wait(0.25):
            if not peek(int(pipe), None, 0, None, None, None) and ctypes.get_last_error() in {
                6,
                109,
                232,
                233,
            }:
                lost_owner()
                return

    threads = [threading.Thread(target=watch_parent, name="autocad-owner-watch", daemon=True)]
    if pipe is not None:
        threads.append(threading.Thread(target=watch_pipe, name="autocad-stdin-watch", daemon=True))
    started = []
    try:
        for thread in threads:
            thread.start()
            started.append(thread)
        yield
    finally:
        stop.set()
        for thread in started:
            thread.join(timeout=1)
        if pipe is not None:
            pipe.Close()
        if parent is not None:
            parent.Close()


@contextlib.contextmanager
def server_lifetime(config, *, backend=False, stdio=False):
    coordinator = Coordinator(config.state)
    role = "backend" if backend else "owner"
    with coordinator.pool("servers:" + role, config.max_server_instances, timeout=0):
        with parent_lifetime(stdio=stdio):
            yield
