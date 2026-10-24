"""App-owned, in-process stdio entry. Copied unchanged to StartMcp.py and worker.py."""

from __future__ import annotations

import ctypes
import hashlib
import importlib.metadata
import json
import os
import re
import site
import stat
import sys
from contextlib import contextmanager
from pathlib import Path

SCHEMA = 1
PINS = {"universal-codex-tools": "0.20.0", "mcp": "2.3.0", "mcp-types": "2.3.0"}
NUMERICAL = (
    "OPENBLAS_NUM_THREADS",
    "GOTO_NUM_THREADS",
    "OMP_NUM_THREADS",
    "OMP_THREAD_LIMIT",
    "MKL_NUM_THREADS",
    "BLIS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
HEX = re.compile(r"[0-9a-f]{64}\Z")


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical_json(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def regular(path, *, directory=False):
    """Check the original path components before resolve can hide a junction."""
    path = Path(path).absolute()
    for current in [*reversed(path.parents), path]:
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked/reparse deployment paths are unsupported")
    info = path.stat()
    if directory and not stat.S_ISDIR(info.st_mode):
        raise ValueError("Deployment directory is unavailable")
    if not directory and not stat.S_ISREG(info.st_mode):
        raise ValueError("Deployment file is unavailable")
    return path


def member(root, relative):
    if not isinstance(relative, str) or not relative or ":" in relative or "\\" in relative:
        raise ValueError("Invalid deployment member")
    part = Path(relative)
    if part.is_absolute() or any(value in {"..", "."} for value in part.parts):
        raise ValueError("Deployment member escaped its root")
    target = Path(root).absolute() / part
    if not target.is_relative_to(Path(root).absolute()):
        raise ValueError("Deployment member escaped its root")
    return regular(target)


def load_json(path, maximum=4_000_000):
    path = regular(path)
    info = path.stat()
    if not 1 <= info.st_size <= maximum or info.st_nlink != 1:
        raise ValueError("Invalid bounded deployment record")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Deployment record must be an object")
    return value


def inventory(root):
    root = regular(root, directory=True)
    result, todo = {}, [root]
    while todo:
        for entry in os.scandir(todo.pop()):
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Deployment inventory contains a linked/reparse member")
            path = Path(entry.path)
            if stat.S_ISDIR(info.st_mode):
                todo.append(path)
            elif stat.S_ISREG(info.st_mode):
                result[path.relative_to(root).as_posix()] = path
            else:
                raise ValueError("Unsupported deployment member")
    return result


def verify_inventory(root, expected, check=lambda: None):
    actual = inventory(root)
    if not isinstance(expected, dict) or not 1 <= len(expected) <= 15000 or actual.keys() != expected.keys():
        raise ValueError("Immutable deployment inventory differs")
    for relative, value in expected.items():
        check()
        if not isinstance(value, dict) or not HEX.fullmatch(value.get("sha256", "")):
            raise ValueError("Invalid immutable member identity")
        path = actual[relative]
        info = path.stat()
        if info.st_nlink != 1 or info.st_size != value["bytes"] or sha256(path) != value["sha256"]:
            raise ValueError("Immutable deployment bytes differ")


@contextmanager
def startup_guard(enabled=True, *, stdio=True):
    """Retain the original parent/wire during verification, before SDK fd diversion."""
    if os.name != "nt" or not enabled:
        yield lambda: None
        return
    from ctypes import wintypes as w

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
    kernel.WaitForSingleObject.argtypes, kernel.WaitForSingleObject.restype = [w.HANDLE, w.DWORD], w.DWORD
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.GetProcessTimes.argtypes = [w.HANDLE, *([ctypes.POINTER(w.FILETIME)] * 4)]
    kernel.GetProcessTimes.restype = w.BOOL
    kernel.GetStdHandle.argtypes, kernel.GetStdHandle.restype = [w.DWORD], w.HANDLE
    kernel.GetFileType.argtypes, kernel.GetFileType.restype = [w.HANDLE], w.DWORD
    kernel.DuplicateHandle.argtypes = [
        w.HANDLE,
        w.HANDLE,
        w.HANDLE,
        ctypes.POINTER(w.HANDLE),
        w.DWORD,
        w.BOOL,
        w.DWORD,
    ]
    kernel.DuplicateHandle.restype = w.BOOL
    kernel.PeekNamedPipe.argtypes = [
        w.HANDLE,
        ctypes.c_void_p,
        w.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    kernel.PeekNamedPipe.restype = w.BOOL
    parent = kernel.OpenProcess(0x101000, False, os.getppid())
    if not parent:
        raise OSError("Startup parent is unavailable")
    pipe = w.HANDLE()
    try:

        def created(handle):
            values = [w.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in values)):
                raise ctypes.WinError(ctypes.get_last_error())
            return (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime

        if created(parent) > created(kernel.GetCurrentProcess()):
            raise ValueError("Startup parent generation changed")
        source = kernel.GetStdHandle(-10 & 0xFFFFFFFF)
        if stdio and kernel.GetFileType(source) == 3:
            current = kernel.GetCurrentProcess()
            if not kernel.DuplicateHandle(current, source, current, ctypes.byref(pipe), 0, False, 2):
                raise ctypes.WinError(ctypes.get_last_error())

        def check():
            if kernel.WaitForSingleObject(parent, 0) != 258:
                raise SystemExit(70)
            if pipe and not kernel.PeekNamedPipe(pipe, None, 0, None, None, None):
                if ctypes.get_last_error() in {6, 109, 232, 233}:
                    raise SystemExit(70)
                raise ctypes.WinError(ctypes.get_last_error())

        check()
        yield check
    finally:
        if pipe:
            kernel.CloseHandle(pipe)
        kernel.CloseHandle(parent)


def selection(root):
    record = load_json(Path(root) / "launcher/current.json", 65536)
    if set(record) != {"schema_version", "generation"} or record["schema_version"] != SCHEMA:
        raise ValueError("Unsupported launcher selection")
    if not isinstance(record["generation"], str) or not HEX.fullmatch(record["generation"]):
        raise ValueError("Malformed launcher generation")
    return record


def verify(root, generation=None, *, check=lambda: None):
    root = regular(root, directory=True)
    generation = generation or selection(root)["generation"]
    if not isinstance(generation, str) or not HEX.fullmatch(generation):
        raise ValueError("Malformed launcher generation")
    snapshot = regular(root / "launcher/snapshots" / generation, directory=True)
    path = regular(snapshot / "manifest.json")
    if sha256(path) != generation:
        raise ValueError("Launch snapshot identity differs")
    record = load_json(path)
    if (
        record.get("schema_version") != SCHEMA
        or record.get("app_id") != "autocad"
        or record.get("profile") != "offline"
    ):
        raise ValueError("Only a reviewed standalone offline deployment is selected")
    if record.get("dependencies") != PINS:
        raise ValueError("Reviewed SDK/framework pins differ")
    if not HEX.fullmatch(record.get("library_id", "")) or not HEX.fullmatch(record.get("bootstrap_id", "")):
        raise ValueError("Invalid retained runtime identity")
    bootstrap_manifest = member(root, "python-manifest.json")
    if sha256(bootstrap_manifest) != record["bootstrap_id"]:
        raise ValueError("Bootstrap interpreter manifest differs")
    verify_inventory(root / "Python", load_json(bootstrap_manifest)["files"], check)
    if sha256(regular(root / "StartMcp.py")) != record["entry_sha256"]:
        raise ValueError("Stable entrypoint differs")
    files = {name: path for name, path in inventory(snapshot).items() if name != "manifest.json"}
    if files.keys() != record["files"].keys():
        raise ValueError("Launch snapshot inventory differs")
    for name, row in record["files"].items():
        check()
        path = member(snapshot, name)
        info = path.stat()
        if info.st_nlink != 1 or info.st_size != row["bytes"] or sha256(path) != row["sha256"]:
            raise ValueError("Launch snapshot bytes differ")
    libraries = regular(root / "libraries" / record["library_id"], directory=True)
    library_manifest = regular(libraries / "manifest.json")
    if sha256(library_manifest) != record["library_id"]:
        raise ValueError("Dependency closure identity differs")
    verify_inventory(libraries / "site-packages", load_json(library_manifest)["files"], check)
    config = member(root, record["config"])
    if sha256(config) != record["config_sha256"]:
        raise ValueError("Selected configuration differs")
    if Path(sys.executable).resolve() != (root / "Python/python.exe").resolve():
        raise ValueError("Use this installation's actual app-owned interpreter")
    if any(Path(value).resolve() != (root / "Python").resolve() for value in (sys.prefix, sys.base_prefix)):
        raise ValueError("Interpreter prefix escaped this installation")
    check()
    return {
        **record,
        "generation": generation,
        "home": str(root),
        "snapshot": str(snapshot),
        "site": str(libraries / "site-packages"),
        "config_path": str(config),
    }


def run(argv=None, script=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    script = Path(script or __file__).absolute()
    worker = script.name == "worker.py"
    root = script.parents[3] if worker else script.parent
    check_only = not worker and argv == ["--check"]
    check_generation = not worker and len(argv) == 2 and argv[0] == "--check-generation"
    check_only = check_only or check_generation
    http_port = None
    if not worker and len(argv) == 2 and argv[0] == "--http":
        http_port = int(argv[1])
        if not 1 <= http_port <= 65535:
            raise ValueError("HTTP port must be 1..65535")
    if worker:
        if not 2 <= len(argv) <= 258 or argv[1] not in {"_extract", "_render", "_tables", "_highlight"}:
            raise ValueError("Invalid immutable worker invocation")
        generation = argv[0]
        if script.parent.name != generation:
            raise ValueError("Worker generation differs")
    else:
        if argv and not check_only and http_port is None:
            raise ValueError("Stable server entry accepts no runtime/profile overrides")
        generation = argv[1] if check_generation else None
    sys.dont_write_bytecode = True
    with startup_guard(not worker and not check_only, stdio=http_port is None) as check:
        observed = verify(root, generation, check=check)
        for name in ("PYTHONPATH", "PYTHONHOME", "NODE_OPTIONS", "NODE_PATH", "AUTOCAD_MCP_OWNED_TREE"):
            if name == "AUTOCAD_MCP_OWNED_TREE" and worker:
                continue
            os.environ.pop(name, None)
        os.environ.update(observed["environment"])
        os.environ.update({name: "1" for name in NUMERICAL})
        os.chdir(root)
        sys.path.insert(0, observed["site"])
        site.addsitedir(observed["site"])
        sys.path.insert(0, str(Path(observed["snapshot"]) / "app"))
        expected = {**PINS, "autocad-mcp-server": observed["version"]}
        if any(importlib.metadata.version(name) != version for name, version in expected.items()):
            raise ValueError("Loaded dependency identities differ")
        from autocad_mcp.config import Config

        Config.load(observed["config_path"])
        if check_only:
            print(
                json.dumps(
                    {
                        "passed": True,
                        "generation": observed["generation"],
                        "version": observed["version"],
                        "profile": observed["profile"],
                        "mcp_started": False,
                        "native_started": False,
                    }
                )
            )
            return 0
        check()
    from autocad_mcp import __version__
    from autocad_mcp.__main__ import main
    from autocad_mcp.deployment_status import bind_deployment_status
    from autocad_mcp.worker_launch import bind_deployment

    if __version__ != observed["version"]:
        raise ValueError("App resolved outside its selected generation")
    bind_deployment(Path(observed["snapshot"]), observed["generation"], stable=True)
    bind_deployment_status(observed)
    if worker:
        sys.argv = [str(script), *argv[1:]]
    else:
        sys.argv = [
            str(script),
            "--config",
            observed["config_path"],
            "serve",
            "--management-registry",
            observed["registry"],
        ]
        if http_port is not None:
            sys.argv.extend(["--transport", "streamable-http", "--port", str(http_port)])
    main()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except (OSError, ValueError, KeyError, TypeError, importlib.metadata.PackageNotFoundError) as error:
        print(
            f"AutoCAD stable launcher refused startup: {type(error).__name__}: {str(error)[:400]}",
            file=sys.stderr,
        )
        raise SystemExit(1)
