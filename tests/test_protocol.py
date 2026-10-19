import sys
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
