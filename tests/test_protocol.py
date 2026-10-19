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
