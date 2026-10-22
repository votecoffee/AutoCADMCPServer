"""App-owned shared-framework publication and serving. No universal daemon is required."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import platform
import sqlite3
import sys
from contextlib import asynccontextmanager, closing
from pathlib import Path

from . import __version__
from .config import Config, inside
from .coordination import Coordinator
from .integration import HIGHLIGHT, OFFLINE_WRITES

FRAMEWORK_VERSION = "0.18.0"
HOST_INSTRUCTIONS = (
    "AutoCAD MCP Server app-owned framework host. Use search_tools, then describe_service and "
    "describe_tool for drawing-engine/cad_get_workflow. Read that tool's current app workflow "
    "through call_read_tool before selecting drawing operations. Use exact root/project IDs and "
    "current catalog revisions. Writes require separate host and app request IDs. Preserve source "
    "hashes, app authorization and uncertainty. No automatic cross-route retries or approval-mode overrides. "
    "This is AutoCAD's app-owned standalone host."
)


def require_framework():
    if importlib.metadata.version("mcp") != "2.3.0":
        raise ValueError("MCP SDK 2.3.0 is required; do not downgrade the application SDK")
    if importlib.metadata.version("universal-codex-tools") != FRAMEWORK_VERSION:
        raise ValueError("Install the exact tested shared app framework package")


def check_host_state(config: Config, state: Path):
    if any(inside(state, root) or inside(root, state) for root in [*config.roots.values(), config.state]):
        raise ValueError("Framework state must be separate from drawing roots and app business state")
    if any((state / "services").glob("*.json")):
        raise ValueError("Use dedicated app framework state without existing service registrations")


def check_receipts(config: Config):
    jobs = config.state / "batch-jobs.sqlite3"
    if jobs.exists():
        with closing(sqlite3.connect(jobs.as_uri() + "?mode=ro", uri=True)) as db:
            if db.execute(
                "SELECT count(*) FROM jobs WHERE state IN ('queued','running','cancel_requested','unknown')"
            ).fetchone()[0]:
                raise ValueError("Reconcile active/unknown index jobs before backend publication")
    path = config.state / "requests.sqlite3"
    if not path.exists():
        return
    # Read only; publication cannot clear, acknowledge or retry an app operation.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        unresolved = db.execute("SELECT count(*) FROM requests WHERE state!='succeeded'").fetchone()[0]
    if unresolved:
        raise ValueError(
            "Reconcile non-successful app receipts before backend publication; no automatic override"
        )


def prepare(
    config_path: Path, state: Path, *, port=8798, highlighting=False, discovery_profile="transient-legacy"
) -> dict:
    require_framework()
    from universal_tools.cli import initialize
    from universal_tools.framework import ApplicationDefinition
    from universal_tools.models import atomic_json

    config_path, state = config_path.resolve(strict=True), state.resolve()
    config = Config.load(config_path)
    check_host_state(config, state)
    check_receipts(config)
    if discovery_profile not in {"transient-legacy", "retained-modern"}:
        raise ValueError("Select an explicit supported discovery profile")
    modern = discovery_profile == "retained-modern"
    previous = state / "autocad-application.json"
    if previous.exists() and json.loads(previous.read_bytes())["backends"][0]["service"]["session_mode"] != (
        "shared" if modern else "transient"
    ):
        raise ValueError("A different retained/ownership profile requires dedicated host state")
    package = Path(__file__).parent
    contents = {"autocad_mcp/" + p.name: p.read_bytes() for p in sorted(package.glob("*.py"))}
    contents["worker.py"] = (package / "framework_entry.py").read_bytes()
    from .workflow_guidance import render, source_text

    contents.update(
        {
            "guidance/" + name: raw
            for name, raw in render(source_text(contents["autocad_mcp/guidance.py"])).items()
        }
    )
    dependencies = {
        name: importlib.metadata.version(name)
        for name in (
            "mcp",
            "universal-codex-tools",
            "anyio",
            "opentelemetry-api",
            "ezdxf",
            "PyMuPDF",
            "Pillow",
        )
    }
    manifest = {
        "schema_version": 1,
        "app_version": __version__,
        "python_version": platform.python_version(),
        "dependencies": dependencies,
        "config": str(config_path),
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()},
    }
    raw = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    deployment = state / "backend-releases" / digest
    deployment.mkdir(parents=True, exist_ok=True)
    for name, data in {**contents, "deployment.json": raw}.items():
        target = deployment / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != data:
            raise ValueError("Immutable backend deployment was modified")
        if not target.exists():
            target.write_bytes(data)
    if any(
        (package / Path(name).name).read_bytes() != data
        for name, data in contents.items()
        if name.startswith("autocad_mcp/")
    ):
        raise ValueError("App source changed during publication; retry after development is quiescent")
    entry = deployment / "worker.py"
    publication = ApplicationDefinition.model_validate(
        {
            "schema_version": 1,
            "id": "autocad",
            "display_name": "AutoCAD MCP Server",
            "instructions": HOST_INSTRUCTIONS,
            "backends": [
                {
                    "revision": "cad-" + digest[:48],
                    "artifact": {
                        "path": str(entry),
                        "sha256": hashlib.sha256(contents["worker.py"]).hexdigest(),
                    },
                    "service": {
                        "id": "drawing-engine",
                        "display_name": "AutoCAD drawing engine",
                        "description": "Source-preserving drawing analysis and read-only versioned workflow guidance.",
                        "transport": {
                            "type": "stdio",
                            "command": sys.executable,
                            "args": ["-I", str(entry), digest],
                            "cwd": str(deployment),
                        },
                        "enabled": True,
                        "allow_writes": True,
                        "allowed_write_tools": list(OFFLINE_WRITES) + ([HIGHLIGHT] if highlighting else []),
                        "session_mode": "shared" if modern else "transient",
                        "protocol_mode": "2026-07-28" if modern else "legacy",
                        "discovery_cache_ttl_seconds": 2 if modern else 0,
                        "watch_catalog": modern,
                        "max_argument_depth": 64,
                        "max_argument_nodes": 100_000,
                        "timeout_seconds": 300,
                        "resource_id": "autocad-state-"
                        + hashlib.sha256(str(config.state).casefold().encode()).hexdigest()[:24],
                    },
                }
            ],
        }
    )
    initialize(state, port)
    path = state / "autocad-application.json"
    atomic_json(path, publication.model_dump(mode="json"))
    return {
        "publication": str(path),
        "host_state": str(state),
        "backend_revision": publication.backends[0].revision,
        "deployment": str(deployment),
        "framework_version": FRAMEWORK_VERSION,
        "backend_tools": 38,
        "live_migration_performed": False,
    }


def create_host(state: Path, publication: Path, config_path: Path, **kwargs):
    require_framework()
    from universal_tools.framework import ApplicationHost
    from universal_tools.models import BrokerError

    from .framework_entry import verify_deployment

    state, publication, config_path = (
        state.resolve(),
        publication.resolve(strict=True),
        config_path.resolve(strict=True),
    )
    original = Config.load(config_path)
    check_host_state(original, state)

    # App-owned reload gate supplements the framework journal with inner app receipts.
    # A normal MCP result can still describe an unknown native UI outcome.
    class DrawingHost(ApplicationHost):
        async def refresh(self):
            async with self.guidance_refresh_lock:
                return await self.refresh_with_guidance()

        async def refresh_with_guidance(self):
            try:
                arguments = json.loads(publication.read_bytes())["backends"][0]["service"]["transport"][
                    "args"
                ]
                deployment = verify_deployment(Path(arguments[-2]).parent, arguments[-1])
                if Path(deployment["config"]).resolve() != config_path:
                    raise ValueError("Publication changed the selected app configuration")
                app_config = Config.load(config_path)
                if app_config.state != original.state:
                    raise ValueError("Use a new host for a different app business-state directory")
                check_host_state(app_config, state)
                check_receipts(app_config)
                from .workflow_guidance import Guidance

                guide_folder = Path(arguments[-2]).parent / "guidance"
                candidate = Guidance(package=guide_folder)
            except (
                ValueError,
                OSError,
                KeyError,
                IndexError,
                sqlite3.Error,
                importlib.metadata.PackageNotFoundError,
            ) as error:
                raise BrokerError(
                    "App deployment/receipts require local reconciliation before refresh"
                ) from error
            result = await super().refresh()
            # A deferred or rejected backend must keep its prior guidance publication.
            if (
                self._selected["drawing-engine"].revision
                == json.loads(publication.read_bytes())["backends"][0]["revision"]
            ):
                import tempfile

                with tempfile.TemporaryDirectory(prefix="autocad-host-guidance-") as folder:
                    Guidance.write(Path(folder), candidate.files())
                    await self.workflow_guidance.catalog.publish(
                        [folder], expected_revision=self.workflow_guidance.catalog.revision
                    )
            return result

    from .management import Activity

    host = DrawingHost(state, publication, **kwargs)
    from .workflow_guidance import Guidance

    host.workflow_guidance = Guidance()
    from .artifacts import Artifacts, GuidanceResources
    from .service import DrawingService

    host.artifacts = Artifacts(DrawingService(original))
    host.resource_catalog = GuidanceResources(host.workflow_guidance.catalog, host.artifacts)
    host.guidance_refresh_lock = asyncio.Lock()
    host.management_activity = Activity()
    invoke = host.backend.invoke

    async def observed(name, arguments, *, relay=None):
        with host.management_activity.operation():
            result = await invoke(name, arguments, relay=relay)
            if (
                name == "call_read_tool"
                and arguments.get("tool_id") == "drawing-engine/cad_get_artifact"
                and not result.is_error
            ):
                payload = arguments["arguments"]
                await asyncio.to_thread(
                    host.artifacts.describe,
                    payload["request_id"],
                    payload["sha256"],
                    payload.get("offset", 0),
                    payload.get("length", 65536),
                )
                await host.artifacts.changed()
            return result

    host.backend.invoke = observed
    return host


def serve(state: Path, publication: Path, config_path: Path, *, registry=None):
    from .lifetime import server_lifetime

    config = Config.load(config_path)
    with server_lifetime(config):
        with Coordinator(config.state).lock("framework-host:" + str(state.resolve()), timeout=0):
            _serve(state, publication, config_path, registry=registry)


def _serve(state: Path, publication: Path, config_path: Path, *, registry=None):
    import secrets

    import uvicorn
    from starlette.applications import Starlette
    from universal_tools.daemon import ProtectedApp
    from universal_tools.models import load_settings

    from .management import Reporting

    state = state.resolve(strict=True)
    settings = load_settings(state)
    host = create_host(
        state, publication, config_path, max_request_body_bytes=settings.max_request_body_bytes
    )
    server = host.create_server(port=settings.port, skills=host.resource_catalog)
    base = server.streamable_http_app(**server.http_options)

    @asynccontextmanager
    async def lifespan(_):
        async with host, server.session_manager.run():
            with Reporting(host.management_activity.status, registry=registry):
                yield

    app = Starlette(routes=base.routes, lifespan=lifespan)
    runtime = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level="warning",
        access_log=False,
        timeout_graceful_shutdown=15,
    )
    process = uvicorn.Server(runtime)
    runtime.app = ProtectedApp(app, settings, process, secrets.token_hex(16))
    process.run()


def proxy(state: Path):
    from .lifetime import parent_lifetime

    state = state.resolve(strict=True)
    with Coordinator(state).pool("servers:proxy", 2, timeout=0):
        with parent_lifetime(stdio=True):
            _proxy(state)


def _proxy(state: Path):
    require_framework()
    from universal_tools.models import load_settings
    from universal_tools.surface import RemoteBackend, create_surface

    # App startup is a separate app-owned operation. Never start a universal daemon here.
    create_surface(
        RemoteBackend(load_settings(state.resolve(strict=True))),
        name="AutoCAD MCP Server",
        instructions=HOST_INSTRUCTIONS,
    ).run(transport="stdio")
