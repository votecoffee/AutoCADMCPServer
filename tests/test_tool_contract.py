import pytest
from mcp import Client

from autocad_mcp.server import create_server


@pytest.mark.anyio
async def test_emitted_bounds_defaults_and_safe_expected_errors(drawing_service, monkeypatch):
    service, _ = drawing_service
    server = create_server(service)
    async with Client(server, cache=None) as client:
        catalog = (await client.list_tools()).model_dump(mode="json", by_alias=True)
        tools = {tool["name"]: tool["inputSchema"]["properties"] for tool in catalog["tools"]}
        assert tools["cad_list_files"]["offset"]["minimum"] == 0
        assert tools["cad_list_files"]["limit"]["maximum"] == 200
        assert tools["cad_index_project"]["limit"]["maximum"] == 5
        assert tools["cad_start_index_job"]["limit"]["default"] == 5
        assert tools["cad_render_preview"]["width"]["maximum"] == 3000
        assert tools["cad_get_artifact"]["length"]["maximum"] == 65536
        assert tools["cad_read_text_record"]["length"]["maximum"] == 16000
        assert tools["cad_trace_connection"]["max_depth"]["maximum"] == 100
        assert tools["cad_trace_connection"]["max_paths"]["default"] == 20
        invalid = await client.call_tool("cad_list_files", {"root_id": "test", "limit": True})
        assert invalid.is_error
        invalid = await client.call_tool("cad_list_files", {"root_id": "test", "offset": -1})
        assert invalid.is_error
        missing = await client.call_tool("cad_list_files", {"root_id": "not-configured"})
        assert missing.is_error and "Unknown root_id" in missing.content[0].text
        monkeypatch.setattr(
            service,
            "inventory",
            lambda *args: (_ for _ in ()).throw(RuntimeError("private-unexpected-detail")),
        )
        unexpected = await client.call_tool("cad_list_files", {"root_id": "test"})
        assert unexpected.is_error and "private-unexpected-detail" not in unexpected.content[0].text
        assert "Error executing tool" in unexpected.content[0].text
