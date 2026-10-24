from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import nullcontext


def main():
    if len(sys.argv) > 1 and sys.argv[1] in {"_extract", "_render", "_tables", "_highlight"}:
        if sys.argv[1] == "_extract":
            from .extract import run_worker
        elif sys.argv[1] == "_render":
            from .render import run_worker
        elif sys.argv[1] == "_tables":
            from .render import run_tables as run_worker
        else:
            from .autocad import run_worker
        run_worker(*sys.argv[2:])
        return
    from . import __display_version__, __version__

    parser = argparse.ArgumentParser(description="AutoCAD MCP Server - local DWG/DXF/PDF extraction")
    parser.add_argument(
        "--version",
        action="version",
        version=f"AutoCAD MCP Server {__display_version__} (package {__version__})",
    )
    parser.add_argument("--config", default=os.environ.get("AUTOCAD_MCP_CONFIG", ".local/config.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument("--port", type=int, default=8796)
    serve.add_argument(
        "--management-registry", help="Explicit private tray registry for isolated deployments"
    )
    serve.add_argument(
        "--workflow",
        action="store_true",
        help="Reserved app-host backend; deployment is blocked pending SDK stdio ownership",
    )
    prepare = sub.add_parser(
        "framework-prepare", help="Publish a private, immutable backend for the app-owned framework host"
    )
    prepare.add_argument("--host-state", required=True)
    prepare.add_argument("--port", type=int, default=8798)
    prepare.add_argument("--include-highlighting", action="store_true")
    prepare.add_argument(
        "--discovery-profile", choices=["transient-legacy", "retained-modern"], default="transient-legacy"
    )
    host = sub.add_parser("framework-serve", help="Run the authenticated app-owned host; no universal daemon")
    host.add_argument("--host-state", required=True)
    host.add_argument("--publication")
    host.add_argument("--management-registry", help="Explicit private tray registry for isolated deployments")
    proxy = sub.add_parser(
        "framework-proxy", help="Connect the standalone app frontend to its already-running host"
    )
    proxy.add_argument("--host-state", required=True)
    sub.add_parser("status")
    inventory = sub.add_parser("inventory")
    inventory.add_argument("root_id")
    inventory.add_argument("--all", action="store_true")
    inventory.add_argument("--offset", type=int, default=0)
    inventory.add_argument("--limit", type=int, default=100)
    for name in ("inspect", "text", "render"):
        command = sub.add_parser(name)
        command.add_argument("root_id")
        command.add_argument("relative_path")
    index = sub.add_parser("index")
    index.add_argument("root_id")
    index.add_argument("--offset", type=int, default=0)
    index.add_argument("--limit", type=int, default=2)
    search = sub.add_parser("search")
    search.add_argument("root_id")
    search.add_argument("query")
    build = sub.add_parser("electrical-build")
    build.add_argument("root_id")
    build.add_argument("--wdp")
    build.add_argument("--options", help="JSON file with build options, including reports and drawing_paths")
    for name in ("electrical-show", "electrical-export"):
        command = sub.add_parser(name)
        command.add_argument("project_id")
        if name == "electrical-show":
            command.add_argument("--collection")
            command.add_argument("--offset", type=int, default=0)
            command.add_argument("--limit", type=int, default=50)
            command.add_argument("--query")
    trace = sub.add_parser("electrical-trace")
    trace.add_argument("project_id")
    trace.add_argument("device_id")
    trace.add_argument("--terminal")
    trace.add_argument("--domain", choices=["electrical", "network"], default="electrical")
    compare = sub.add_parser("electrical-compare")
    compare.add_argument("before_project_id")
    compare.add_argument("after_project_id")
    args = parser.parse_args()
    if args.command == "serve" and args.workflow:
        from .framework_host import RUNTIME_BLOCKER

        parser.error(RUNTIME_BLOCKER)
    if args.command.startswith("framework-"):
        from pathlib import Path

        from . import framework_host

        state = Path(args.host_state)
        if args.command == "framework-prepare":
            result = framework_host.prepare(
                Path(args.config),
                state,
                port=args.port,
                highlighting=args.include_highlighting,
                discovery_profile=args.discovery_profile,
            )
            print(json.dumps(result))
        elif args.command == "framework-serve":
            framework_host.serve(
                state,
                Path(args.publication) if args.publication else state / "autocad-application.json",
                Path(args.config),
                registry=args.management_registry,
            )
        else:
            framework_host.proxy(state)
        return
    from .config import Config

    config = Config.load(args.config)
    if args.command == "serve":
        from .lifetime import server_lifetime

        with server_lifetime(config, backend=args.workflow, stdio=args.transport == "stdio"):
            _serve(config, args)
        return
    from .owned_resources import owned_resources
    from .service import DrawingService

    owned_resources.configure()
    try:
        service = DrawingService(config)
        _execute(service, args)
    finally:
        owned_resources.close()


def _serve(config, args):
    from .coordination import RequestScheduler
    from .owned_resources import owned_resources
    from .server import create_server
    from .service import DrawingService

    owned_resources.configure(args.management_registry)
    owned_resources.initialize()
    service = DrawingService(config)
    scheduler = RequestScheduler(service.config.max_concurrent_requests, service.config.max_queued_requests)
    server = create_server(service, args.port, workflow=args.workflow, scheduler=scheduler)
    reporting = nullcontext()
    if not args.workflow:
        from .management import Reporting

        def activity():
            value = scheduler.status()
            value["active"] += service.batch_jobs.activity()
            return value

        reporting = Reporting(activity, registry=args.management_registry)
    with reporting:
        try:
            if args.transport == "stdio":
                server.run(transport="stdio")
            else:
                server.run(transport="streamable-http", host="127.0.0.1", port=args.port)
        finally:
            try:
                service.batch_jobs.close(timeout=0)
            finally:
                owned_resources.close()
                service.batch_jobs.close(timeout=2)


def _execute(service, args):
    if args.command.startswith("electrical-"):
        from pathlib import Path

        from .electrical import ElectricalService

        electrical = ElectricalService(service)
        if args.command == "electrical-build":
            options = json.loads(Path(args.options).read_text(encoding="utf-8-sig")) if args.options else {}
            if args.wdp:
                options["electrical_project_path"] = args.wdp
            result = electrical.build(args.root_id, **options)
        elif args.command == "electrical-show":
            result = (
                electrical.query(args.project_id, args.collection, args.offset, args.limit, args.query)
                if args.collection
                else electrical.get(args.project_id)
            )
        elif args.command == "electrical-trace":
            result = electrical.trace(args.project_id, args.device_id, args.terminal, args.domain)
        elif args.command == "electrical-compare":
            result = electrical.compare(args.before_project_id, args.after_project_id)
        else:
            result = electrical.export(args.project_id)
    elif args.command == "status":
        result = service.status()
    elif args.command == "inventory":
        result = service.inventory(args.root_id, not args.all, args.offset, args.limit)
    elif args.command == "inspect":
        result = service.inspect(args.root_id, args.relative_path)
    elif args.command == "text":
        result = service.records(args.root_id, args.relative_path, "text")
    elif args.command == "render":
        result = service.render(args.root_id, args.relative_path)
    elif args.command == "index":
        result = service.index(args.root_id, args.offset, args.limit)
    else:
        result = service.search(args.root_id, args.query)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
