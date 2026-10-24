"""Prepare an independent app-owned Codex plugin with private local runtime bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
import uuid
from pathlib import Path

FILES = (
    "plugin.json",
    "mcp.json",
    ".mcp.json",
    ".codex-plugin/plugin.json",
    "assets/icon.png",
    "skills/drawing-analysis/SKILL.md",
)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".pending")
    with temporary.open("xb") as stream:
        stream.write((json.dumps(value, indent=2) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def registration_guard(stable_home, settings=None):
    """Retain legacy pins and defer CLI pruning until the host route is migrated."""
    settings = settings or Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
    raw = settings.read_bytes() if settings.exists() else b""
    value = tomllib.loads(raw.decode("utf-8-sig"))
    route = value.get("mcp_servers", {}).get("autocad")
    if not route:
        return {"ready": True, "existing_route": None}
    try:
        from scripts.stable_install import binding, files, regular
    except ModuleNotFoundError:
        from stable_install import binding, files, regular

    desired = binding(stable_home)
    ready = all(route.get(key) == desired[key] for key in ("command", "args", "cwd"))
    result = {"ready": ready, "existing_route": route, "settings_sha256": hashlib.sha256(raw).hexdigest()}
    if ready:
        return result
    retained = Path(stable_home) / "registration-pins" / uuid.uuid4().hex
    retained.mkdir(parents=True)
    (retained / "config-before.toml").write_bytes(raw)
    cache = Path(route.get("cwd", ""))
    cache_root = settings.parent / "plugins/cache/autocad-local/autocad"
    if cache.is_absolute() and cache.is_relative_to(cache_root) and cache.is_dir():
        regular(cache, directory=True)
        payloads = files(cache)
        for relative in payloads:
            target = retained / "cache" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cache / relative, target)
        result["retained_cache_inventory"] = payloads
    result.update(
        reason="Existing route must be migrated by the serialized host-settings publisher before plugin registration can prune caches",
        retained_pins=str(retained),
    )
    (retained / "pins.json").write_bytes((json.dumps(result, indent=2) + "\n").encode())
    return result


def prepare(
    repo: Path,
    config: Path | None = None,
    *,
    frontend="legacy",
    host_state: Path | None = None,
    stable_home: Path | None = None,
):
    repo = repo.resolve()
    template = repo / "plugins" / "autocad"
    config = (config or repo / ".local" / "config.json").resolve(strict=True)
    python = repo / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if stable_home is None and not python.is_file():
        raise ValueError("Run InstallAndRun.cmd --install-only first")
    from autocad_mcp import __display_version__, __version__
    from autocad_mcp.profile import NUMERICAL_ENVIRONMENT

    if stable_home is None:
        from autocad_mcp.config import Config

        profile = Config.load(config).execution_profile
    else:
        profile = "offline"
    for name in ("plugin.json", ".codex-plugin/plugin.json"):
        if json.loads((template / name).read_bytes())["version"] != __version__:
            raise ValueError("Plugin manifest must match the app package version")
    server = {
        "type": "stdio",
        "command": str(python),
        "args": ["-m", "autocad_mcp", "--config", str(config), "serve"],
        "cwd": str(repo),
        "env": {
            **NUMERICAL_ENVIRONMENT,
            "AUTOCAD_MCP_EXECUTION_PROFILE": profile,
            "AUTOCAD_MCP_PLUGIN_VERSION": __version__,
            "AUTOCAD_MCP_PLUGIN_DISPLAY_VERSION": __display_version__,
        },
    }
    if stable_home is not None:
        try:
            from scripts.stable_install import binding, load_json, sha256
        except ModuleNotFoundError:
            from stable_install import binding, load_json, sha256

        if frontend != "legacy" or host_state is not None:
            raise ValueError("Stable adoption selects the direct standalone offline service")
        stable_home = stable_home.absolute()
        pointer = load_json(stable_home / "launcher/current.json", 65536)
        selected_path = stable_home / "launcher/snapshots" / pointer["generation"] / "manifest.json"
        selected = load_json(selected_path)
        if sha256(selected_path) != pointer["generation"] or selected["version"] != __version__:
            raise ValueError("Plugin package must match the reviewed selected app version")
        if selected["config_sha256"] != hashlib.sha256(config.read_bytes()).hexdigest():
            raise ValueError("Publish the selected configuration before preparing its stable plugin")
        server = {"type": "stdio", **binding(stable_home)}
        server["env"].update(
            {
                "AUTOCAD_MCP_PLUGIN_VERSION": __version__,
                "AUTOCAD_MCP_PLUGIN_DISPLAY_VERSION": __display_version__,
            }
        )
    if frontend == "framework":
        if host_state is None or not (host_state / "autocad-application.json").is_file():
            raise ValueError("Prepare a dedicated app framework host before preparing its frontend")
        from autocad_mcp.framework_entry import verify_deployment

        publication = json.loads((host_state / "autocad-application.json").read_bytes())
        arguments = publication["backends"][0]["service"]["transport"]["args"]
        deployment = verify_deployment(Path(arguments[-2]).parent, arguments[-1])
        if publication["id"] != "autocad" or Path(deployment["config"]).resolve() != config:
            raise ValueError("Framework frontend must use this app and selected configuration")
        server["args"] = [
            "-m",
            "autocad_mcp",
            "--config",
            str(config),
            "framework-proxy",
            "--host-state",
            str(host_state.resolve()),
        ]
    elif frontend != "legacy" or host_state is not None:
        raise ValueError("Select legacy or framework explicitly; host state applies only to framework")
    portable = {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        "mcpServers": {"autocad": server},
    }
    legacy = {"mcpServers": {"autocad": server}}
    contents = {name: (template / name).read_bytes() for name in FILES}
    contents["mcp.json"] = (json.dumps(portable, indent=2) + "\n").encode()
    contents[".mcp.json"] = (json.dumps(legacy, indent=2) + "\n").encode()
    digest = hashlib.sha256(
        b"".join(name.encode() + b"\0" + contents[name] for name in sorted(contents))
    ).hexdigest()[:16]
    root = (
        stable_home / "codex-marketplace"
        if stable_home is not None
        else repo / ".local" / "codex-marketplace"
    )
    package = root / "packages" / ("autocad-" + __version__ + "-" + digest)
    for name, data in contents.items():
        path = package / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.read_bytes() != data:
            raise ValueError("Immutable plugin package identity conflict")
        if not path.exists():
            path.write_bytes(data)
    marketplace = {
        "name": "autocad-local",
        "interface": {"displayName": "AutoCAD MCP Server Local"},
        "plugins": [
            {
                "name": "autocad",
                "source": {"source": "local", "path": "./" + package.relative_to(root).as_posix()},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }
        ],
    }
    target = root / ".agents" / "plugins" / "marketplace.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(target, marketplace)
    return {
        "marketplace": str(root),
        "package": str(package),
        "plugin": "autocad@autocad-local",
        "transport": "stdio",
        "standalone": True,
        "frontend": frontend,
        "version": __version__,
        "display_version": __display_version__,
        "publishable": stable_home is not None,
        "deployment_scope": "app_owned_stable" if stable_home is not None else "development_unpublished",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prepare-only", action="store_true", help="Prepare local bindings without registering in Codex"
    )
    parser.add_argument(
        "--mode",
        choices=["auto", "standalone", "none"],
        default="standalone",
        help="Auto refreshes standalone while preserving skipped/disabled installation choices",
    )
    parser.add_argument("--config", type=Path, help="Use this app configuration in the generated binding")
    parser.add_argument("--frontend", choices=["legacy", "framework"], default="legacy")
    parser.add_argument("--host-state", type=Path, help="Dedicated app-owned framework host state")
    parser.add_argument(
        "--stable-home", type=Path, help="Reviewed app-owned stable launcher; required for registration"
    )
    args = parser.parse_args()
    if args.frontend == "framework" and not args.prepare_only and args.mode != "none":
        parser.error(
            "Framework plugin deployment is blocked pending app-owned SDK stdio resource ownership; --prepare-only remains available"
        )
    repo = Path(__file__).resolve().parents[1]
    config = (args.config or repo / ".local/config.json").resolve(strict=True)
    from autocad_mcp.integration import integration_plan

    if args.prepare_only:
        print(
            json.dumps(
                prepare(
                    repo,
                    config,
                    frontend=args.frontend,
                    host_state=args.host_state,
                    stable_home=args.stable_home,
                )
            )
        )
        return
    plan = integration_plan(repo, args.mode)
    result = dict(plan)
    if plan["action"] == "install":
        if args.stable_home is None:
            parser.error("Registration requires --stable-home; checkout/cache launchers cannot be published")
        result.update(
            prepare(
                repo, config, frontend=args.frontend, host_state=args.host_state, stable_home=args.stable_home
            )
        )
        result["route_guard"] = registration_guard(args.stable_home)
        if not result["route_guard"]["ready"]:
            result.update(registration_requested=False, action="defer")
            print(json.dumps(result))
            return
        codex = shutil.which("codex")
        if not codex:
            raise ValueError("Codex CLI was not found; local plugin prepared but not registered")
        subprocess.run(
            [codex, "plugin", "marketplace", "add", result["marketplace"]], check=True, stdout=sys.stderr
        )
        subprocess.run([codex, "plugin", "add", result["plugin"], "--json"], check=True, stdout=sys.stderr)
        result["registration_requested"] = True
    if plan["action"] != "defer":
        atomic_json(repo / ".local/codex-integration.json", {"schema_version": 1, **plan})
    print(json.dumps(result))


if __name__ == "__main__":
    main()
