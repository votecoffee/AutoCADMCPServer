"""Resolve an observed executable through its file handle, including MSIX aliases."""

import ctypes
import os
from ctypes import wintypes as w
from pathlib import Path


def canonical_image_path(value):
    if os.name != "nt":
        return str(Path(value).resolve(strict=True))
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.GetFinalPathNameByHandleW.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]
    kernel.GetFinalPathNameByHandleW.restype = w.DWORD
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
    # Attribute-only observation, shared with readers/writers/deletion; never a process action.
    handle = kernel.CreateFileW(str(value), 0x80, 7, None, 3, 0, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not 0 < length < len(buffer):
            raise OSError("Executable physical path is unavailable")
        path = buffer.value
        if path.startswith("\\\\?\\UNC\\"):
            path = "\\\\" + path[8:]
        elif path.startswith("\\\\?\\"):
            path = path[4:]
        return os.path.normcase(os.path.normpath(path))
    finally:
        kernel.CloseHandle(handle)


def same_generation(observed, recorded):
    if any(observed.get(key) != recorded.get(key) for key in ("host_id", "pid", "created")):
        return False
    return canonical_image_path(observed["executable"]) == canonical_image_path(recorded["executable"])
