"""Fixed ODA command on private snapshots, under the existing durable process owner.

Containment governs process lifetime, not filesystem/network access. An operator must
trust the installed converter and its dependencies. No converter is downloaded here.
"""

from __future__ import annotations

import contextlib
import hashlib
import itertools
import os
import shutil
import tempfile
from pathlib import Path

from .owned_process import run_owned
from .profile import ODA_PROFILE, PROFILE, require_native, validate_profile

NATIVE_FORMATS = frozenset({".dwg", ".dwt", ".dws"})


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def converter_path(executable):
    path = Path(executable)
    if not path.is_absolute() or path.suffix.lower() != ".exe":
        raise ValueError("Use an existing absolute ODA .exe path")
    # Refuse reparse indirection, including ancestors; never discover or adopt a binary.
    if any(
        part.is_symlink() or getattr(part, "is_junction", lambda: False)() for part in (path, *path.parents)
    ):
        raise ValueError("ODA executable path cannot contain links or junctions")
    if not path.is_file():
        raise ValueError("Configured ODA executable is missing")
    return path


@contextlib.contextmanager
def pinned_converter(executable, expected_sha256):
    """Deny executable write/delete while hashing, launching and reading the result."""
    if os.name != "nt":
        raise ValueError("Contained ODA execution currently requires Windows")
    import msvcrt

    import win32api
    import win32con
    import win32file

    path = converter_path(executable)
    handle = win32file.CreateFile(
        str(path),
        win32con.GENERIC_READ,
        win32con.FILE_SHARE_READ,
        None,
        win32con.OPEN_EXISTING,
        win32con.FILE_ATTRIBUTE_NORMAL,
        None,
    )
    # Transfer handle ownership to Python so every exception closes it exactly once.
    raw_handle = handle.Detach()
    try:
        fd = msvcrt.open_osfhandle(raw_handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        win32api.CloseHandle(raw_handle)
        raise
    with os.fdopen(fd, "rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected_sha256:
            raise ValueError("ODA executable SHA-256 differs from the configured pin")
        yield path


@contextlib.contextmanager
def converted_dxf(source: Path, options: dict):
    """Yield one validated DXF until its caller has read it, then discard staging."""
    if source.suffix.lower() == ".dxf":
        yield source, {"engine": "ezdxf", "conversion": None}
        return
    profile = options.get("execution_profile", PROFILE)
    if profile != ODA_PROFILE:
        require_native("ODA DWG/DWT/DWS conversion")
    executable, pin = options.get("oda_executable"), options.get("oda_sha256")
    validate_profile(profile, executable, pin)
    if source.suffix.lower() not in NATIVE_FORMATS:
        raise ValueError("ODA input must be DWG, DWT or DWS")
    budget = options.get("max_file_bytes", 268_435_456)
    if type(budget) is not int or not 1 <= budget <= 268_435_456:
        raise ValueError("Invalid conversion byte budget")
    if source.stat().st_size > budget:
        raise ValueError("ODA input exceeds conversion byte budget")
    before = digest(source)
    with pinned_converter(executable, pin) as binary:
        # The adapter itself isolates input, even when called outside DrawingService.
        with tempfile.TemporaryDirectory(prefix="autocad-oda-") as folder:
            staging = Path(folder)
            inputs, outputs = staging / "input", staging / "output"
            inputs.mkdir()
            outputs.mkdir()
            # DWT/DWS share the DWG container; use an exact .dwg filter for ODA.
            snapshot = inputs / "source.dwg"
            shutil.copyfile(source, snapshot)
            if digest(snapshot) != before or digest(source) != before:
                raise ValueError("ODA source changed during snapshot")
            result = run_owned(
                [str(binary), str(inputs), str(outputs), "ACAD2018", "DXF", "0", "0", snapshot.name],
                timeout=60,
                check=False,
                resource_kind="oda-converter",
            )
            if result.returncode:
                raise ValueError(f"ODA conversion failed: exit={result.returncode}")
            if (
                outputs.is_symlink()
                or getattr(outputs, "is_junction", lambda: False)()
                or outputs.resolve() != staging / "output"
            ):
                raise ValueError("ODA output directory was replaced; result discarded")
            candidates = list(itertools.islice(outputs.iterdir(), 2))
            if len(candidates) != 1:
                raise ValueError(f"ODA must produce exactly one DXF; outputs={len(candidates)}")
            dxf = candidates[0]
            if (
                dxf.is_symlink()
                or getattr(dxf, "is_junction", lambda: False)()
                or not dxf.is_file()
                or dxf.suffix.lower() != ".dxf"
                or dxf.resolve().parent != outputs.resolve()
                or dxf.stat().st_nlink != 1
                or not 0 < dxf.stat().st_size <= budget
            ):
                raise ValueError("ODA output is not one bounded regular DXF")
            if digest(source) != before or digest(snapshot) != before:
                raise ValueError("ODA source or conversion snapshot changed; result discarded")
            converted_hash = digest(dxf)
            yield (
                dxf,
                {
                    "engine": "ODA File Converter + ezdxf",
                    "conversion": "isolated copy to ACAD2018 DXF",
                    "oda_sha256": pin,
                    "input_sha256": before,
                    "converted_dxf_sha256": converted_hash,
                    "converted_dxf_size_bytes": dxf.stat().st_size,
                    "audit": False,
                    "recursive": False,
                    "native_autocad_validation": False,
                    "reference_policy": "No companion files staged; converter is trusted, not sandboxed",
                },
            )
            if digest(source) != before or digest(dxf) != converted_hash:
                raise ValueError("ODA input or readback changed; result discarded")
