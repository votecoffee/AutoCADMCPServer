"""Exercise real MCP initialization, tool discovery, annotations and calls through stdio."""

import argparse
import asyncio
import json
import sys
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(config, root):
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
            print(
                json.dumps(
                    {
                        "server": initialized.serverInfo.name,
                        "tool_count": len(tools),
                        "read_tools": sum(t.annotations.readOnlyHint for t in tools),
                        "source_sha256": inspect.structuredContent["source"]["sha256"],
                        "passed": True,
                    }
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=".local/config.json")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.config, args.root))
