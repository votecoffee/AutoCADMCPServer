import asyncio
import json
import shutil
import socket
import subprocess
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from universal_tools.transport import http_session

from autocad_mcp import framework_host
from autocad_mcp.framework_entry import verify_deployment
from autocad_mcp.guidance import WORKFLOW
from autocad_mcp.integration import OFFLINE_WRITES
from autocad_mcp.server import create_server
from autocad_mcp.transactions import Transactions

FRONT_DOOR = {
    "broker_status",
    "list_services",
    "refresh_services",
    "search_tools",
    "describe_service",
    "describe_tool",
    "describe_capability",
    "refresh_capabilities",
    "call_read_tool",
    "call_write_tool",
    "get_request_status",
    "acquire_service",
    "release_service",
    "service_session_status",
}


def data(result):
    assert not result.is_error, result.content
    return result.structured_content or json.loads(result.content[0].text)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def publish(drawing_service, tmp_path, monkeypatch):
    service, source = drawing_service
    package = tmp_path / "development-package"
    shutil.copytree(
        Path(framework_host.__file__).parent, package, ignore=shutil.ignore_patterns("__pycache__")
    )
    monkeypatch.setattr(framework_host, "__file__", str(package / "framework_host.py"))
    config, state = source.parent / "config.json", tmp_path / "framework-state"
    result = framework_host.prepare(config, state, port=free_port())
    return service, config, state, package, result


def add_fixture_tool(package):
    server = package / "server.py"
    text = server.read_text(encoding="utf-8")
    added = '\n    @tool()\n    def cad_fixture_marker() -> dict:\n        """Disposable backend revision marker."""\n        return {"generation": 2}\n'
    server.write_text(text.replace("    return mcp\n", added + "    return mcp\n"), encoding="utf-8")


@pytest.mark.anyio
async def test_real_handlers_and_results_through_framework(
    drawing_service, tmp_path, monkeypatch, record_property
):
    service, config, state, package, result = publish(drawing_service, tmp_path, monkeypatch)
    publication = json.loads(Path(result["publication"]).read_bytes())["backends"][0]["service"]
    assert publication["session_mode"] == "transient" and publication["protocol_mode"] == "legacy"
    assert publication["discovery_cache_ttl_seconds"] == 0 and publication["watch_catalog"] is False
    assert publication["max_argument_depth"] == 64 and publication["max_argument_nodes"] == 100_000
    async with framework_host.create_host(state, Path(result["publication"]), config) as host:
        first, second = host.client(), host.client()
        native = {tool.name: tool for tool in await create_server(service).list_tools()}
        for name, tool in native.items():
            description = data(await first.invoke("describe_tool", {"tool_id": "drawing-engine/" + name}))
            assert description["definition"] == tool.model_dump(mode="json", by_alias=True, exclude_none=True)
            assert description["callable"] == (tool.annotations.read_only_hint or name in OFFLINE_WRITES)

        async def routed(name, arguments, outer=None, client=first):
            desc = data(await client.invoke("describe_tool", {"tool_id": "drawing-engine/" + name}))
            payload = {
                "tool_id": desc["tool_id"],
                "catalog_revision": desc["catalog_revision"],
                "arguments": arguments,
            }
            if outer:
                payload["request_id"] = outer
            return await client.invoke(desc["invocation"]["channel"], payload)

        assert data(await routed("cad_get_workflow", {}))["text"] == WORKFLOW
        args = {"root_id": "test", "relative_path": "sample.dxf"}
        before = (service.config.roots["test"] / "sample.dxf").read_bytes()
        assert data(await routed("cad_inspect", args)) == service.inspect("test", "sample.dxf")
        pdf_before = (service.config.roots["test"] / "sample.pdf").read_bytes()
        tables = data(
            await routed("cad_get_pdf_tables", {"root_id": "test", "relative_path": "sample.pdf", "page": 1})
        )
        assert tables == service.pdf_tables("test", "sample.pdf", 1)
        preview = data(
            await routed(
                "cad_render_preview",
                {
                    "root_id": "test",
                    "relative_path": "sample.pdf",
                    "width": 600,
                    "request_id": "app-framework-preview",
                },
                "host-preview-0001",
            )
        )
        reference_preview = service.render("test", "sample.pdf", width=600)
        assert {k: v for k, v in preview.items() if k not in {"transaction", "preview_path"}} == {
            k: v for k, v in reference_preview.items() if k != "preview_path"
        }
        assert (
            Path(preview["preview_path"]).read_bytes() == Path(reference_preview["preview_path"]).read_bytes()
        )
        assert (service.config.roots["test"] / "sample.pdf").read_bytes() == pdf_before
        indexed = data(
            await routed(
                "cad_index_project",
                {"root_id": "test", "request_id": "app-framework-index"},
                "host-index-0001",
            )
        )
        assert indexed["transaction"]["state"] == "succeeded"
        built = data(
            await routed(
                "cad_build_electrical_project",
                {"root_id": "test", "drawing_paths": ["sample.dxf"], "request_id": "app-framework-build"},
                "host-build-0001",
            )
        )
        identifier = built["project_id"]
        exported = data(
            await routed(
                "cad_export_electrical_project",
                {"project_id": identifier, "request_id": "app-framework-export"},
                "host-export-0001",
            )
        )
        receipt = data(
            await routed(
                "cad_get_transaction",
                {"request_id": "app-framework-export", "include_result": True},
                client=second,
            )
        )
        assert receipt["state"] == "succeeded" and receipt["result"]["path"] == exported["path"]
        denied = await routed(
            "cad_highlight_source_object",
            {"project_id": identifier, "device_id": "missing", "request_id": "app-denied-highlight"},
            "host-denied-highlight",
        )
        assert denied.is_error
        assert (
            data(await routed("cad_get_transaction", {"request_id": "app-denied-highlight"}))["state"]
            == "not_found"
        )
        assert (
            data(await first.invoke("get_request_status", {"request_id": "host-export-0001"}))["status"]
            == "completed"
        )
        assert (
            await routed(
                "cad_export_electrical_project",
                {"project_id": identifier, "request_id": "app-framework-export"},
                "host-export-0001",
            )
        ).is_error
        assert (service.config.roots["test"] / "sample.dxf").read_bytes() == before
        samples = []
        direct = []
        for _ in range(3):
            start = time.perf_counter()
            expected = service.inspect("test", "sample.dxf")
            direct.append((time.perf_counter() - start) * 1000)
            start = time.perf_counter()
            assert data(await routed("cad_inspect", args, client=second)) == expected
            samples.append((time.perf_counter() - start) * 1000)
        record_property(
            "warm_inspect_latency_ms", json.dumps({"direct": direct, "framework_transient": samples})
        )
        runtime = data(await first.invoke("broker_status", {}))["runtime"]
        assert set(runtime) == {"calls", "seconds"}
        assert runtime["calls"]["backend_call.returned"] >= 1
        assert all(isinstance(value, (int, float)) for group in runtime.values() for value in group.values())


@pytest.mark.anyio
@pytest.mark.parametrize("shape", ["depth", "nodes"])
async def test_structural_rejection_precedes_host_and_app_write_receipts(
    drawing_service, tmp_path, monkeypatch, shape
):
    service, config, state, package, result = publish(drawing_service, tmp_path, monkeypatch)
    original = (service.config.roots["test"] / "sample.dxf").read_bytes()
    value = [0] * 100_001
    if shape == "depth":
        value = 0
        for _ in range(70):
            value = [value]
    app_id, host_id = "app-shape-" + shape, "host-shape-" + shape
    async with framework_host.create_host(state, Path(result["publication"]), config) as host:
        client = host.client()
        description = data(
            await client.invoke("describe_tool", {"tool_id": "drawing-engine/cad_index_project"})
        )
        denied = await client.invoke(
            "call_write_tool",
            {
                "tool_id": description["tool_id"],
                "catalog_revision": description["catalog_revision"],
                "request_id": host_id,
                "arguments": {"root_id": "test", "request_id": app_id, "limit": value},
            },
        )
        assert denied.is_error and "budget" in denied.content[0].text
        missing = await client.invoke("get_request_status", {"request_id": host_id})
        assert missing.is_error and "unknown request_id" in missing.content[0].text
        assert Transactions(service.config.state, service.coordinator).get(app_id)["state"] == "not_found"
    assert (service.config.roots["test"] / "sample.dxf").read_bytes() == original


@pytest.mark.anyio
async def test_unknown_inner_receipt_blocks_publication_and_refresh(drawing_service, tmp_path, monkeypatch):
    service, config, state, package, result = publish(drawing_service, tmp_path, monkeypatch)
    async with framework_host.create_host(state, Path(result["publication"]), config) as host:
        active = (state / "framework/active.json").read_bytes()
        add_fixture_tool(package)
        framework_host.prepare(config, state, port=json.loads((state / "settings.json").read_bytes())["port"])
        transactions = Transactions(service.config.state, service.coordinator)
        transactions.execute(
            "fixture-unknown",
            "fixture",
            {},
            lambda: {"status": "unknown", "error": "Disposable unknown effect"},
        )
        assert (await host.client().invoke("refresh_services", {})).is_error
        assert (state / "framework/active.json").read_bytes() == active
        with pytest.raises(ValueError, match="Reconcile"):
            framework_host.prepare(config, state)
        assert transactions.get("fixture-unknown")["state"] == "unknown"


@pytest.mark.parametrize("changed", ["module", "config", "inventory"])
def test_deployment_source_and_configuration_are_bound(drawing_service, tmp_path, monkeypatch, changed):
    service, config, state, package, result = publish(drawing_service, tmp_path, monkeypatch)
    deployment = Path(result["deployment"])
    digest = deployment.name
    assert verify_deployment(deployment, digest)["config"] == str(config)
    if changed == "module":
        with (deployment / "autocad_mcp/server.py").open("a") as stream:
            stream.write("\n# modified deployment\n")
    elif changed == "config":
        config.write_bytes(config.read_bytes() + b"\n")
    else:
        (deployment / "unpublished.py").write_text("raise RuntimeError('must not import')")
    with pytest.raises(ValueError, match="changed"):
        verify_deployment(deployment, digest)


@pytest.mark.anyio
async def test_same_two_native_clients_refresh_backend_without_frontdoor_reload(
    drawing_service, tmp_path, monkeypatch
):
    service, config, state, package, result = publish(drawing_service, tmp_path, monkeypatch)
    port = json.loads((state / "settings.json").read_bytes())["port"]
    token = json.loads((state / "settings.json").read_bytes())["token"]
    log = (tmp_path / "app-host.log").open("wb")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "autocad_mcp",
            "--config",
            str(config),
            "framework-serve",
            "--host-state",
            str(state),
        ],
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
    )
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=0.5) as health:
            deadline = time.monotonic() + 45
            while True:
                assert process.poll() is None, (tmp_path / "app-host.log").read_text()
                try:
                    response = await health.get(
                        f"http://127.0.0.1:{port}/health", headers={"Authorization": "Bearer " + token}
                    )
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert time.monotonic() < deadline
                await asyncio.sleep(0.1)
        async with AsyncExitStack() as stack:
            clients = [
                await stack.enter_async_context(http_session(f"http://127.0.0.1:{port}/mcp", token))
                for _ in range(2)
            ]
            definitions = (await clients[0].list_tools()).model_dump(mode="json", by_alias=True)
            assert {tool["name"] for tool in definitions["tools"]} == FRONT_DOOR
            assert {str(resource.uri) for resource in (await clients[0].list_resources()).resources} == {
                "broker://catalog"
            }
            catalog = json.loads((await clients[0].read_resource("broker://catalog")).contents[0].text)
            assert set(catalog) == {"generation"}
            assert (
                catalog["generation"] == data(await clients[0].call_tool("broker_status", {}))["generation"]
            )
            guide = data(
                await clients[0].call_tool("describe_tool", {"tool_id": "drawing-engine/cad_get_workflow"})
            )
            payload = {
                "tool_id": guide["tool_id"],
                "catalog_revision": guide["catalog_revision"],
                "arguments": {},
            }
            original_guide = data(await clients[0].call_tool("call_read_tool", payload))
            add_fixture_tool(package)
            guidance = package / "guidance.py"
            guidance.write_text(
                guidance.read_text().replace("workflow v1.", "workflow fixture v2."), encoding="utf-8"
            )
            extractor = package / "extract.py"
            extractor.write_text(
                extractor.read_text().replace(
                    "    Path(destination).write_text(",
                    '    result["text"][0]["text"] = "Framework snapshot parser v2"\n    Path(destination).write_text(',
                ),
                encoding="utf-8",
            )
            replacement = framework_host.prepare(config, state, port=port)
            assert replacement["backend_revision"] != result["backend_revision"]
            data(await clients[1].call_tool("refresh_services", {}))
            next_catalog = json.loads((await clients[0].read_resource("broker://catalog")).contents[0].text)
            assert set(next_catalog) == {"generation"} and next_catalog["generation"] != catalog["generation"]
            assert (await clients[0].call_tool("call_read_tool", payload)).is_error
            marker = data(
                await clients[0].call_tool("describe_tool", {"tool_id": "drawing-engine/cad_fixture_marker"})
            )
            assert data(
                await clients[0].call_tool(
                    "call_read_tool",
                    {
                        "tool_id": marker["tool_id"],
                        "catalog_revision": marker["catalog_revision"],
                        "arguments": {},
                    },
                )
            ) == {"generation": 2}
            guide = data(
                await clients[1].call_tool("describe_tool", {"tool_id": "drawing-engine/cad_get_workflow"})
            )
            updated_guide = data(
                await clients[1].call_tool(
                    "call_read_tool",
                    {
                        "tool_id": guide["tool_id"],
                        "catalog_revision": guide["catalog_revision"],
                        "arguments": {},
                    },
                )
            )
            assert updated_guide["workflow_revision"] != original_guide["workflow_revision"]
            assert "workflow fixture v2." in updated_guide["text"]
            for client in clients:
                assert (await client.list_tools()).model_dump(mode="json", by_alias=True) == definitions
            text_tool = data(
                await clients[0].call_tool("describe_tool", {"tool_id": "drawing-engine/cad_get_text"})
            )
            parsed = data(
                await clients[0].call_tool(
                    "call_read_tool",
                    {
                        "tool_id": text_tool["tool_id"],
                        "catalog_revision": text_tool["catalog_revision"],
                        "arguments": {"root_id": "test", "relative_path": "sample.dxf"},
                    },
                )
            )
            assert parsed["items"][0]["text"] == "Framework snapshot parser v2"
            # Exercise the app-owned stdio frontend without a universal daemon or plugin installation.
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "autocad_mcp", "framework-proxy", "--host-state", str(state)],
            )
            async with stdio_client(parameters) as (read, write):
                async with ClientSession(read, write, read_timeout_seconds=30.0) as frontend:
                    await frontend.initialize()
                    assert {t.name for t in (await frontend.list_tools()).tools} == FRONT_DOOR
    finally:
        process.terminate()
        try:
            await asyncio.to_thread(process.wait, 10)
        except subprocess.TimeoutExpired:
            process.kill()
            await asyncio.to_thread(process.wait, 5)
        log.close()
