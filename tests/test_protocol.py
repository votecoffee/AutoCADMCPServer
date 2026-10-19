import asyncio
import sys
from contextlib import AsyncExitStack
from datetime import timedelta

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.anyio
async def test_cold_worker_extraction_through_real_stdio(drawing_service):
    service, source = drawing_service
    assert list((service.config.state / "cache").glob("*.json")) == []
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "autocad_mcp", "--config", str(source.parent / "config.json"), "serve"],
    )
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=20)) as client:
            await client.initialize()
            for path in ("sample.pdf", "sample.dxf"):
                result = await client.call_tool("cad_inspect", {"root_id": "test", "relative_path": path})
                assert not result.isError, result.content
                assert result.structuredContent["text_records"] > 0
            tables = await client.call_tool(
                "cad_get_pdf_tables", {"root_id": "test", "relative_path": "sample.pdf", "page": 1}
            )
            assert not tables.isError, tables.content
            assert tables.structuredContent["total"] == 1
            built = await client.call_tool(
                "cad_build_electrical_project",
                {"root_id": "test", "drawing_paths": ["sample.dxf", "sample.pdf"]},
            )
            assert not built.isError, built.content
            project_id = built.structuredContent["project_id"]
            for name in (
                "cad_get_device_inventory",
                "cad_get_plc_io",
                "cad_get_connections",
                "cad_get_equipment_groups",
                "cad_get_network_inventory",
                "cad_check_drawing_consistency",
                "cad_export_electrical_project",
            ):
                result = await client.call_tool(name, {"project_id": project_id})
                assert not result.isError, result.content
                assert result.structuredContent is not None
            compared = await client.call_tool(
                "cad_compare_electrical_revisions",
                {"before_project_id": project_id, "after_project_id": project_id},
            )
            assert not compared.isError and compared.structuredContent["total"] == 0
            rejected = await client.call_tool(
                "cad_highlight_source_object", {"project_id": project_id, "device_id": "missing"}
            )
            assert rejected.isError


@pytest.mark.anyio
async def test_two_mcp_processes_share_transactions_and_state(drawing_service):
    service, source = drawing_service
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "autocad_mcp", "--config", str(source.parent / "config.json"), "serve"],
    )
    async with AsyncExitStack() as stack:
        clients = []
        for _ in range(2):
            read, write = await stack.enter_async_context(stdio_client(parameters))
            client = await stack.enter_async_context(
                ClientSession(read, write, read_timeout_seconds=timedelta(seconds=60))
            )
            await client.initialize()
            clients.append(client)
        arguments = {"root_id": "test", "offset": 1, "limit": 1, "request_id": "shared-index"}
        indexed = await asyncio.gather(
            *(client.call_tool("cad_index_project", arguments) for client in clients)
        )
        assert all(not r.isError for r in indexed), [r.content for r in indexed]
        assert sorted(r.structuredContent["transaction"]["replayed"] for r in indexed) == [False, True]
        assert all(r.structuredContent["results"][0]["status"] == "indexed" for r in indexed)
        builds = await asyncio.gather(
            *(
                client.call_tool(
                    "cad_build_electrical_project",
                    {"root_id": "test", "drawing_paths": ["sample.dxf"], "request_id": f"build-{i}"},
                )
                for i, client in enumerate(clients)
            )
        )
        assert all(not r.isError for r in builds), [r.content for r in builds]
        identifier = builds[0].structuredContent["project_id"]
        assert builds[1].structuredContent["project_id"] == identifier
        exports = await asyncio.gather(
            *(
                client.call_tool(
                    "cad_export_electrical_project", {"project_id": identifier, "request_id": "one-export"}
                )
                for client in clients
            )
        )
        assert all(not r.isError for r in exports), [r.content for r in exports]
        assert exports[0].structuredContent["path"] == exports[1].structuredContent["path"]
        assert len(list((service.config.state / "electrical/exports").glob("*.json"))) == 1
        receipt = await clients[0].call_tool(
            "cad_get_transaction", {"request_id": "one-export", "include_result": True}
        )
        assert receipt.structuredContent["state"] == "succeeded"
        assert receipt.structuredContent["result"]["path"] == exports[0].structuredContent["path"]
        rejected = await clients[1].call_tool(
            "cad_export_electrical_project", {"project_id": "different", "request_id": "one-export"}
        )
        assert rejected.isError
    with service.database() as db:
        count = db.execute("SELECT count(*) FROM records WHERE root='test' AND path='sample.dxf'").fetchone()[
            0
        ]
    assert count == len(service.load("test", "sample.dxf")["text"])
