from __future__ import annotations

import argparse
import json
import os
import sys


def main():
    if len(sys.argv) > 1 and sys.argv[1] in {"_extract", "_render", "_tables"}:
        if sys.argv[1] == "_extract":
            from .extract import run_worker
        elif sys.argv[1] == "_render":
            from .render import run_worker
        else:
            from .render import run_tables as run_worker
        run_worker(*sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description="AutoCAD MCP Server - local DWG/DXF/PDF extraction")
    parser.add_argument("--config", default=os.environ.get("AUTOCAD_MCP_CONFIG", ".local/config.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument("--port", type=int, default=8796)
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
    args = parser.parse_args()
    from .config import Config
    from .service import DrawingService

    service = DrawingService(Config.load(args.config))
    if args.command == "serve":
        from .server import create_server

        create_server(service, args.port).run(transport=args.transport)
        return
    if args.command == "status":
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
