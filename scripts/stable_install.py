"""Publish reviewed standalone runtimes; never writes shared Codex settings or prunes live assets."""

from __future__ import annotations

import argparse
import base64
import contextlib
import csv
import ctypes
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path

try:
    from scripts.stable_entry import (
        PINS,
        canonical_json,
        inventory,
        load_json,
        regular,
        sha256,
        verify_inventory,
    )
except ModuleNotFoundError:
    from stable_entry import PINS, canonical_json, inventory, load_json, regular, sha256, verify_inventory


def default_home():
    if os.name != "nt":
        raise ValueError("The stable deployment profile requires Windows")
    from ctypes import wintypes as w

    # FOLDERID_Profile avoids Local AppData's MSIX package-file virtualization.
    folder_id = ctypes.create_string_buffer(uuid.UUID("5e6c858f-0e22-4760-9afe-ea3317b67173").bytes_le)
    value = w.LPWSTR()
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, w.DWORD, w.HANDLE, ctypes.POINTER(w.LPWSTR)]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole = ctypes.WinDLL("ole32")
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    result = shell.SHGetKnownFolderPath(folder_id, 0x10000, None, ctypes.byref(value))
    if result != 0:
        raise OSError("Unredirected user profile is unavailable")
    try:
        return Path(value.value) / "Applications" / "AutoCADMCPServer"
    finally:
        ole.CoTaskMemFree(value)


def files(root):
    return {
        name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for name, path in sorted(inventory(root).items())
    }


def immutable(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        regular(path)
        if path.read_bytes() != data:
            raise ValueError("An immutable installed file differs; retain it for inspection")
    else:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())


def contained(home, path):
    home, path = Path(home).absolute(), Path(path).absolute()
    if path == home or not path.is_relative_to(home):
        raise ValueError("Publication path escaped the dedicated installation")
    return path


def bootstrap(home, python_source, entry):
    home, source = Path(home).absolute(), regular(python_source, directory=True)
    target = contained(home, home / "Python")
    manifest_path = home / "python-manifest.json"
    if manifest_path.exists():
        record = load_json(manifest_path)
        verify_inventory(target, record["files"])
        if (home / "StartMcp.py").read_bytes() != Path(entry).read_bytes():
            raise ValueError("Stable bootstrap update needs a separate reviewed launcher migration")
        return sha256(manifest_path)
    if target.exists():
        raise ValueError("An incomplete bootstrap is retained; inspect it before publication")
    version = subprocess.check_output(
        [
            str(source / "python.exe"),
            "-I",
            "-S",
            "-B",
            "-c",
            "import sys;print('.'.join(map(str,sys.version_info[:3])))",
        ],
        text=True,
        timeout=10,
    ).strip()
    if version != "3.13.9":
        raise ValueError("Stable Windows adoption requires reviewed CPython 3.13.9")
    target.mkdir(parents=True, exist_ok=False)
    names = (
        "python.exe",
        "pythonw.exe",
        "python3.dll",
        "python313.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "LICENSE.txt",
    )
    for name in names:
        path = regular(source / name)
        shutil.copyfile(path, target / name)
    for folder in ("Lib", "DLLs"):
        origin = regular(source / folder, directory=True)
        for directory, folders, names in os.walk(origin, followlinks=False):
            folders[:] = [name for name in folders if name not in {"site-packages", "__pycache__"}]
            for name in names:
                if name.endswith(".pyc"):
                    continue
                path = regular(Path(directory) / name)
                destination = contained(home, target / folder / path.relative_to(origin))
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
    manifest = {"schema_version": 1, "python_version": "3.13.9", "files": files(target)}
    immutable(manifest_path, canonical_json(manifest))
    immutable(home / "StartMcp.py", Path(entry).read_bytes())
    return sha256(manifest_path)


def dependencies(home, wheelhouse, lock, uv, *, offline=True):
    home = Path(home).absolute()
    stage = contained(home, home / "staging" / uuid.uuid4().hex)
    site = stage / "site-packages"
    site.mkdir(parents=True)
    environment = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "UV_PYTHON", "UV_PROJECT_ENVIRONMENT"):
        environment.pop(name, None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [
        str(uv),
        "--no-cache",
        "--no-config",
        "pip",
        "install",
        "--python",
        str(home / "Python/python.exe"),
        "--target",
        str(site),
        "--link-mode",
        "copy",
        "--require-hashes",
        "--find-links",
        str(wheelhouse),
        "-r",
        str(lock),
    ]
    if offline:
        command.append("--no-index")
    subprocess.run(command, env=environment, stdout=sys.stderr, stderr=sys.stderr, check=True)
    versions = {
        dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions(path=[str(site)])
    }
    if any(versions.get(name) != value for name, value in PINS.items()):
        raise ValueError("Dependency staging did not produce the reviewed SDK/framework pins")
    wheel_hashes = {path.name: sha256(path) for path in sorted(Path(wheelhouse).glob("*.whl"))}
    record = {
        "schema_version": 1,
        "versions": versions,
        "lock_sha256": sha256(lock),
        "wheel_hashes": wheel_hashes,
        "files": files(site),
    }
    raw = canonical_json(record)
    identity = hashlib.sha256(raw).hexdigest()
    immutable(stage / "manifest.json", raw)
    destination = contained(home, home / "libraries" / identity)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError(
            "Identical dependency closure already exists; select it explicitly and retain staged evidence"
        )
    os.replace(stage, destination)
    return identity


def dependencies_from_seed(home, seed_site, lock):
    """Copy only verified runtime RECORD payloads from a reviewed installation.

    The seed's installer must use the wheel lock; retained adoption also keeps its
    original acceptance inventory. Editable hooks, development extras and bytecode
    are never copied, and copying breaks hard links to mutable package caches.
    """
    home, seed_site = Path(home).absolute(), regular(seed_site, directory=True)
    pinned = {
        re.sub(r"[-_.]+", "-", name).lower(): version
        for name, version in re.findall(r"(?m)^([A-Za-z0-9_.-]+)==([^\s;\\]+)", Path(lock).read_text())
    }
    installed = {
        re.sub(r"[-_.]+", "-", dist.metadata["Name"]).lower(): dist
        for dist in importlib.metadata.distributions(path=[str(seed_site)])
    }
    if not pinned or any(
        name not in installed or installed[name].version != version for name, version in pinned.items()
    ):
        raise ValueError("Reviewed runtime seed does not match every locked version")
    stage = contained(home, home / "staging" / uuid.uuid4().hex)
    target = stage / "site-packages"
    target.mkdir(parents=True)
    records = {}
    for name, version in pinned.items():
        dist = installed[name]
        record = Path(dist._path) / "RECORD"
        records[name] = {"version": version, "record_sha256": sha256(record)}
        with record.open(encoding="utf-8", newline="") as stream:
            for relative, checksum, length in csv.reader(stream):
                source = (seed_site / relative).absolute()
                if ".." in Path(relative).parts or not source.is_relative_to(seed_site):
                    if re.fullmatch(r"(?:\.\./){2,3}Scripts/[^/]+", relative.replace("\\", "/")):
                        continue
                    if name == "fonttools" and relative == "../../share/man/man1/ttx.1":
                        continue
                    raise ValueError("Seed RECORD escaped its package directory")
                if source.suffix == ".pyc" or "__pycache__" in source.parts:
                    continue
                source = regular(source)
                if checksum:
                    algorithm, value = checksum.split("=", 1)
                    actual = base64.urlsafe_b64encode(bytes.fromhex(sha256(source))).decode().rstrip("=")
                    if algorithm != "sha256" or value != actual or source.stat().st_size != int(length):
                        raise ValueError("Runtime seed payload differs from its reviewed RECORD")
                elif source.name not in {"RECORD", "INSTALLER", "REQUESTED", "direct_url.json"}:
                    raise ValueError("Unexpected unhashed runtime seed payload")
                if source.suffix == ".pth" and source.name != "pywin32.pth":
                    raise ValueError("Unexpected executable path hook in runtime dependencies")
                destination = contained(home, target / relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if sha256(destination) != sha256(source):
                        raise ValueError("Conflicting dependency payload")
                else:
                    shutil.copyfile(source, destination)
    metadata = {
        "schema_version": 1,
        "versions": pinned,
        "lock_sha256": sha256(lock),
        "seed_records": records,
        "files": files(target),
    }
    raw = canonical_json(metadata)
    identity = hashlib.sha256(raw).hexdigest()
    immutable(stage / "manifest.json", raw)
    destination = contained(home, home / "libraries" / identity)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if (destination / "manifest.json").read_bytes() != raw:
            raise ValueError("Retained dependency identity conflict")
    else:
        os.replace(stage, destination)
    return identity


def snapshot(home, wheel, config, registry, library_id, *, environment=None):
    home, wheel = Path(home).absolute(), regular(wheel)
    from autocad_mcp.profile import NUMERICAL_ENVIRONMENT

    raw_config = regular(config).read_bytes()
    value = json.loads(raw_config)
    if (
        value.get("execution_profile", "offline") != "offline"
        or value.get("oda_executable")
        or value.get("oda_sha256")
    ):
        raise ValueError(
            "Stable adoption retains the accepted offline profile; native activation is separate"
        )
    config_id = hashlib.sha256(raw_config).hexdigest()
    config_relative = "configurations/" + config_id + ".json"
    immutable(home / config_relative, raw_config)
    stage = contained(home, home / "staging" / uuid.uuid4().hex)
    (stage / "app").mkdir(parents=True)
    with zipfile.ZipFile(wheel) as package:
        if package.testzip():
            raise ValueError("App wheel CRC differs")
        for name in package.namelist():
            part = Path(name)
            if part.is_absolute() or ".." in part.parts or ":" in name or "\\" in name:
                raise ValueError("App wheel member escaped staging")
            if name.endswith("/"):
                continue
            if not (name.startswith("autocad_mcp/") or ".dist-info/" in name):
                raise ValueError("Unexpected app wheel payload")
            path = contained(home, stage / "app" / name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(package.read(name))
    app = list(importlib.metadata.distributions(path=[str(stage / "app")]))
    if len(app) != 1 or app[0].metadata["Name"] != "autocad-mcp-server":
        raise ValueError("Expected exactly this application's wheel")
    shutil.copyfile(home / "StartMcp.py", stage / "worker.py")
    env = {
        **NUMERICAL_ENVIRONMENT,
        "AUTOCAD_MCP_EXECUTION_PROFILE": "offline",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "PYTHONPATH": "",
        "PYTHONHOME": "",
        "PATH": str(home / "Python")
        + os.pathsep
        + str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"),
    }
    if environment:
        for name in environment:
            if name not in {"AUTOCAD_MCP_PLUGIN_VERSION", "AUTOCAD_MCP_PLUGIN_DISPLAY_VERSION"}:
                raise ValueError("Only explicit observed plugin identities may augment launch environment")
        env.update(environment)
    manifest = {
        "schema_version": 1,
        "app_id": "autocad",
        "version": app[0].version,
        "profile": "offline",
        "app_wheel_sha256": sha256(wheel),
        "library_id": library_id,
        "bootstrap_id": sha256(home / "python-manifest.json"),
        "entry_sha256": sha256(home / "StartMcp.py"),
        "dependencies": PINS,
        "config": config_relative,
        "config_sha256": config_id,
        "registry": str(Path(registry).absolute()),
        "environment": env,
        "files": files(stage),
    }
    raw = canonical_json(manifest)
    identity = hashlib.sha256(raw).hexdigest()
    immutable(stage / "manifest.json", raw)
    destination = contained(home, home / "launcher/snapshots" / identity)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ValueError("Snapshot already exists; retain the duplicate staging evidence")
    os.replace(stage, destination)
    return identity


@contextlib.contextmanager
def publication_lock(home):
    path = contained(home, Path(home) / "launcher/publication.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def publish(home, generation, *, expected_current):
    """CAS the pointer after a real isolated preflight; live peers keep their snapshots."""
    home = regular(home, directory=True)
    with publication_lock(home):
        current = home / "launcher/current.json"
        if current.exists():
            load_json(current, 65536)
        before = current.read_bytes() if current.exists() else b""
        if (hashlib.sha256(before).hexdigest() if before else "") != expected_current:
            raise ValueError(
                "Launcher selection changed; inspect current bytes rather than restoring a stale pointer"
            )
        # Pin a candidate-only check path; it does not publish or start an MCP service.
        candidate = home / "launcher/snapshots" / generation
        manifest = load_json(candidate / "manifest.json")
        if sha256(candidate / "manifest.json") != generation or manifest["profile"] != "offline":
            raise ValueError("Candidate generation differs")
        if before:
            immutable(home / "launcher/backups" / (expected_current + ".json"), before)
        # Full payload preflight uses the same app-owned interpreter and entry bytes.
        result = subprocess.run(
            [
                str(home / "Python/python.exe"),
                "-I",
                "-S",
                "-B",
                "-X",
                "utf8",
                str(home / "StartMcp.py"),
                "--check-generation",
                generation,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        attested = json.loads(result.stdout)
        if (
            attested.get("generation") != generation
            or attested.get("passed") is not True
            or attested.get("mcp_started") is not False
        ):
            raise ValueError("Candidate preflight did not attest this generation")
        if (current.read_bytes() if current.exists() else b"") != before:
            raise ValueError("Launcher selection changed during verification")
        raw = canonical_json({"schema_version": 1, "generation": generation})
        temporary = current.with_name("current." + uuid.uuid4().hex + ".pending")
        immutable(temporary, raw)
        os.replace(temporary, current)
        if current.read_bytes() != raw:
            raise ValueError("Selected pointer readback differs; retain all old assets")
    return {
        "home": str(home),
        "generation": generation,
        "selection_sha256": sha256(current),
        "binding": binding(home),
    }


def binding(home):
    home = regular(home, directory=True)
    return {
        "command": str(home / "Python/python.exe"),
        "args": ["-I", "-S", "-B", "-u", "-X", "utf8", str(home / "StartMcp.py")],
        "cwd": str(home),
        "env": {"AUTOCAD_MCP_EXECUTION_PROFILE": "offline"},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path)
    parser.add_argument("--python-source", type=Path, default=Path(sys.base_prefix))
    parser.add_argument("--wheelhouse", type=Path)
    parser.add_argument(
        "--seed-site", type=Path, help="Reviewed retained runtime instead of installing dependencies"
    )
    parser.add_argument("--app-wheel", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument(
        "--library-id", help="Explicit retained verified dependency closure instead of reinstalling"
    )
    parser.add_argument(
        "--expected-current", required=True, help="SHA-256 of current.json, or empty for a new installation"
    )
    parser.add_argument("--stage-only", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    home = (args.home or default_home()).absolute()
    home.mkdir(parents=True, exist_ok=True)
    bootstrap(home, args.python_source, repo / "scripts/stable_entry.py")
    if args.library_id:
        library = args.library_id
    elif args.seed_site:
        library = dependencies_from_seed(home, args.seed_site, repo / "requirements-lock.txt")
    elif args.wheelhouse:
        library = dependencies(
            home, args.wheelhouse, repo / "requirements-lock.txt", shutil.which("uv") or "uv"
        )
    else:
        parser.error("Supply --seed-site, --wheelhouse or an explicit retained --library-id")
    generation = snapshot(home, args.app_wheel, args.config, args.registry, library)
    result = {"home": str(home), "generation": generation, "library_id": library, "selected": False}
    if not args.stage_only:
        result.update(publish(home, generation, expected_current=args.expected_current), selected=True)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
