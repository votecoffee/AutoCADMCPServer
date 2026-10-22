"""Exercise real MCP initialization, tool discovery, annotations and calls through stdio."""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def run(config, root, project_id=None, *, management_registry):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "autocad_mcp", "--config", str(Path(config).resolve()), "serve"],
        env={"AUTOCAD_MCP_MANAGEMENT_REGISTRY": str(management_registry)},
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=180.0) as session:
            initialized = await session.initialize()
            tools = (await session.list_tools()).tools
            assert len(tools) == 38
            status = await session.call_tool("cad_status", {})
            assert not status.is_error
            inventory = await session.call_tool("cad_list_files", {"root_id": root, "limit": 1})
            assert not inventory.is_error
            first = inventory.structured_content["items"][0]["relative_path"]
            inspect = await session.call_tool("cad_inspect", {"root_id": root, "relative_path": first})
            assert not inspect.is_error
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
                    assert not result.is_error, result.content
                    assert result.structured_content is not None
                    electrical_calls.append(name)
            print(
                json.dumps(
                    {
                        "server": initialized.server_info.name,
                        "tool_count": len(tools),
                        "read_tools": sum(t.annotations.read_only_hint for t in tools),
                        "source_sha256": inspect.structured_content["source"]["sha256"],
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
    with tempfile.TemporaryDirectory(prefix="autocad-management-") as registry:
        asyncio.run(run(args.config, args.root, args.project_id, management_registry=registry))
