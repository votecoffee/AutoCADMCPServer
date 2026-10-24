"""Install/select an app-owned runtime; ordinary protocol startup never installs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def install(command):
    subprocess.run(command, cwd=REPO, stdout=sys.stderr, stderr=sys.stderr, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install-only", action="store_true", help="Install/select and verify without starting MCP"
    )
    parser.add_argument("--stdio", action="store_true", help="Use MCP stdio instead of loopback HTTP")
    parser.add_argument("--framework-wheel", help="Verified local shared framework 0.20.0 wheel")
    parser.add_argument(
        "--install-plugin", action="store_true", help="Explicit standalone plugin registration"
    )
    parser.add_argument(
        "--prepare-plugin", action="store_true", help="Prepare plugin without writing host settings"
    )
    parser.add_argument("--codex-integration", choices=["auto", "standalone", "none"], default=None)
    parser.add_argument("--port", type=int, default=8796, help="Loopback HTTP port (default: 8796)")
    parser.add_argument("--root", action="append", help="First setup only: alias=absolute drawing directory")
    parser.add_argument(
        "--install-root", type=Path, help="Dedicated app-owned root outside checkouts and caches"
    )
    parser.add_argument("--config", type=Path, help="Explicit offline config; preserve selection by default")
    parser.add_argument("--management-registry", type=Path, help="Explicit durable registry")
    parser.add_argument("--app-wheel", type=Path, help="Reviewed wheel matching this source release")
    parser.add_argument(
        "--seed-site", type=Path, help="Reviewed retained runtime site-packages for offline adoption"
    )
    parser.add_argument(
        "--python-source", type=Path, default=Path(sys.base_prefix), help="Reviewed CPython 3.13.9 root"
    )
    args = parser.parse_args()
    if args.install_plugin and args.codex_integration not in {None, "standalone"}:
        parser.error("--install-plugin selects standalone; do not combine with another integration mode")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be 1..65535")
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required")
    from release_version import check
    from stable_install import (
        binding,
        bootstrap,
        default_home,
        dependencies,
        dependencies_from_seed,
        load_json,
        publish,
        regular,
        sha256,
        snapshot,
    )

    release = check(REPO)
    home = (args.install_root or default_home()).absolute()
    if home.is_relative_to(REPO) or "plugins/cache" in home.as_posix().lower():
        parser.error("--install-root must be outside the development checkout and plugin caches")
    home.mkdir(parents=True, exist_ok=True)
    regular(home, directory=True)
    pointer = home / "launcher/current.json"
    before = pointer.read_bytes() if pointer.exists() else b""
    selected = None
    if before:
        generation = load_json(pointer)["generation"]
        selected_path = home / "launcher/snapshots" / generation / "manifest.json"
        selected = load_json(selected_path)
        if sha256(selected_path) != generation:
            raise ValueError("Selected generation differs; no fallback or overwrite")
    config = args.config or (Path(home / selected["config"]) if selected else None)
    config = config or Path(os.environ.get("AUTOCAD_MCP_CONFIG") or REPO / ".local/config.json")
    sys.path.insert(0, str(REPO / "src"))
    if config.exists():
        if args.root:
            parser.error("Existing configuration preserved. Select a new explicit --config to change roots")
        config = config.absolute()
    else:
        roots = args.root
        if not roots:
            if args.stdio or not sys.stdin.isatty():
                parser.error('No configuration. Supply --root "drawings=C:\\Engineering\\Drawings"')
            roots = ["drawings=" + input("Drawing folder (full path): ").strip().strip('"')]
        values = {}
        for value in roots:
            name, directory = value.split("=", 1)
            if name in values:
                parser.error("Duplicate root name")
            values[name] = str(Path(directory).resolve(strict=True))
        config = home / "first-setup.json"
        raw = (
            json.dumps(
                {"execution_profile": "offline", "roots": values, "state_dir": str(home / "state")}, indent=2
            )
            + "\n"
        ).encode()
        with config.open("xb") as stream:
            stream.write(raw)
    config_hash = sha256(config)
    registry = args.management_registry or (Path(selected["registry"]) if selected else home / "registry")
    needs_install = (
        not selected
        or selected["version"] != release["version"]
        or selected["config_sha256"] != config_hash
        or str(registry.absolute()) != selected["registry"]
    )
    if needs_install and args.stdio and not args.install_only:
        parser.error("Protocol startup never installs/updates implicitly. Run --install-only first")
    print(f"AutoCAD MCP Server {release['display_version']}", file=sys.stderr)
    if needs_install:
        uv = shutil.which("uv")
        if not uv and (not args.app_wheel or not args.seed_site):
            parser.error("Install uv, or supply both a reviewed --app-wheel and --seed-site")
        bootstrap(home, args.python_source, REPO / "scripts/stable_entry.py")
        if selected:
            library = selected["library_id"]
            metadata = load_json(home / "libraries" / library / "manifest.json")
            if metadata["lock_sha256"] != sha256(REPO / "requirements-lock.txt"):
                raise ValueError("Dependency update needs an independently reviewed new installation")
        elif args.seed_site:
            library = dependencies_from_seed(home, args.seed_site, REPO / "requirements-lock.txt")
        else:
            from framework_dependency import stage

            wheel_directory = stage(REPO, args.framework_wheel)
            library = dependencies(home, wheel_directory, REPO / "requirements-lock.txt", uv, offline=False)
        wheel = args.app_wheel
        if wheel is None:
            output = home / "build-input" / uuid.uuid4().hex
            output.mkdir(parents=True)
            install([uv, "build", "--wheel", "--out-dir", str(output), str(REPO)])
            (wheel,) = output.glob("*.whl")
        generation = snapshot(home, wheel, config, registry, library)
        metadata = load_json(home / "launcher/snapshots" / generation / "manifest.json")
        if metadata["version"] != release["version"]:
            raise ValueError("App wheel differs from this fixed source release")
        result = publish(
            home, generation, expected_current=hashlib.sha256(before).hexdigest() if before else ""
        )
        print(json.dumps(result), file=sys.stderr)
    route = binding(home)
    install([route["command"], *route["args"], "--check"])
    integration = args.codex_integration or ("none" if args.stdio else "auto")
    if args.install_plugin:
        integration = "standalone"
    if integration != "none" or args.prepare_plugin:
        command = [
            sys.executable,
            str(REPO / "scripts/install_plugin.py"),
            "--mode",
            integration,
            "--config",
            str(config),
            "--stable-home",
            str(home),
        ]
        if args.prepare_plugin:
            command.append("--prepare-only")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(REPO / "src")
        subprocess.run(command, cwd=REPO, env=environment, check=True, stdout=sys.stderr, stderr=sys.stderr)
    if args.install_only:
        print("Installed runtime verified. Host registration is a separate stage.", file=sys.stderr)
        return 0
    command = [route["command"], *route["args"]]
    if not args.stdio:
        command.extend(["--http", str(args.port)])
        print(f"Starting http://127.0.0.1:{args.port}/mcp; Ctrl+C to stop", file=sys.stderr)
    return subprocess.call(command, cwd=route["cwd"])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as error:
        print(f"Installation failed (exit {error.returncode}). See output above.", file=sys.stderr)
        raise SystemExit(error.returncode or 1)
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (ValueError, OSError, KeyError) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        raise SystemExit(1)
