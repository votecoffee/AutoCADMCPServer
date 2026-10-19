"""Exercise real MCP initialization, tool discovery, annotations and calls through stdio."""

import argparse
import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(config, root, project_id=None):
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "autocad_mcp", "--config", str(Path(config).resolve()), "serve"]
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=180)) as session:
            initialized = await session.initialize()
            tools = (await session.list_tools()).tools
            assert len(tools) == 29
            status = await session.call_tool("cad_status", {})
            assert not status.isError
            inventory = await session.call_tool("cad_list_files", {"root_id": root, "limit": 1})
            assert not inventory.isError
            first = inventory.structuredContent["items"][0]["relative_path"]
            inspect = await session.call_tool("cad_inspect", {"root_id": root, "relative_path": first})
            assert not inspect.isError
            electrical_calls = []
            if project_id:
                for name in (
                    "cad_get_electrical_project",
                    "cad_get_device_inventory",
                    "cad_get_plc_io",
                    "cad_get_connections",
                    "cad_get_equipment_groups",
                    "cad_get_network_inventory",
                    "cad_check_drawing_consistency",
                    "cad_export_electrical_project",
                ):
                    arguments = {"project_id": project_id}
                    if name not in {"cad_get_electrical_project", "cad_export_electrical_project"}:
                        arguments["limit"] = 2
                    result = await session.call_tool(name, arguments)
                    assert not result.isError, result.content
                    assert result.structuredContent is not None
                    electrical_calls.append(name)
            print(
                json.dumps(
                    {
                        "server": initialized.serverInfo.name,
                        "tool_count": len(tools),
                        "read_tools": sum(t.annotations.readOnlyHint for t in tools),
                        "source_sha256": inspect.structuredContent["source"]["sha256"],
                        "electrical_calls": electrical_calls,
                        "passed": True,
                    }
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=".local/config.json")
    parser.add_argument("--root", required=True)
    parser.add_argument("--project-id", help="Also exercise electrical reads and app-owned JSON export")
    args = parser.parse_args()
    asyncio.run(run(args.config, args.root, args.project_id))
