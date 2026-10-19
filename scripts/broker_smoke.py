"""Compare direct MCP and Universal Tools on disposable drawings and isolated broker state."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import AsyncExitStack
from pathlib import Path

import ezdxf
import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from autocad_mcp.electrical import atomic_json
from autocad_mcp.guidance import WORKFLOW
from autocad_mcp.integration import OFFLINE_WRITES, broker_manifest, broker_metadata, file_hash


def data(result):
    if result.is_error:
        raise AssertionError(result.content)
    return result.structured_content or json.loads(result.content[0].text)


async def exercise(repo, config, broker_python, state):
    async with AsyncExitStack() as stack:

        async def client(parameters):
            read, write = await stack.enter_async_context(stdio_client(parameters))
            session = await stack.enter_async_context(ClientSession(read, write, read_timeout_seconds=90.0))
            initialized = await session.initialize()
            return session, initialized

        direct, initialized = await client(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", "autocad_mcp", "--config", str(config), "serve"],
                cwd=str(repo),
            )
        )
        parameters = StdioServerParameters(
            command=str(broker_python),
            args=["-m", "universal_tools", "--state", str(state), "proxy"],
        )
        broker, _ = await client(parameters)
        second, _ = await client(parameters)
        service = data(await broker.call_tool("describe_service", {"service_id": "autocad"}))
        assert service["initialization"]["instructions"] == initialized.instructions == WORKFLOW
        assert service["session_mode"] == "transient" and not service["context_required"]
        definitions = (await direct.list_tools()).tools
        described = {}
        for tool in definitions:
            description = data(await broker.call_tool("describe_tool", {"tool_id": "autocad/" + tool.name}))
            assert description["definition"] == tool.model_dump(mode="json", by_alias=True, exclude_none=True)
            assert description["classification"] == (
                "read" if tool.annotations.read_only_hint else "write_or_unknown"
            )
            assert description["callable"] == (tool.annotations.read_only_hint or tool.name in OFFLINE_WRITES)
            described[tool.name] = description

        async def routed(name, arguments, outer_id=None, frontend=broker):
            description = described[name]
            payload = {
                "tool_id": description["tool_id"],
                "catalog_revision": description["catalog_revision"],
                "arguments": arguments,
            }
            if outer_id:
                payload["request_id"] = outer_id
            return await frontend.call_tool(description["invocation"]["channel"], payload)

        # Both connections intentionally address the same app state and same known operation.
        index_args = {"root_id": "fixture", "request_id": "app-index-0001"}
        indexed = await asyncio.gather(
            direct.call_tool("cad_index_project", index_args),
            routed("cad_index_project", index_args, "broker-index-0001"),
        )
        assert sorted(data(r)["transaction"]["replayed"] for r in indexed) == [False, True]
        build = data(
            await routed(
                "cad_build_electrical_project",
                {
                    "root_id": "fixture",
                    "request_id": "app-build-0001",
                },
                "broker-build-0001",
            )
        )
        identifier = build["project_id"]
        inventory_args = {"project_id": identifier}
        native_inventory, routed_inventory = await asyncio.gather(
            direct.call_tool("cad_get_device_inventory", inventory_args),
            routed("cad_get_device_inventory", inventory_args, frontend=second),
        )
        assert data(native_inventory) == data(routed_inventory)
        assert data(native_inventory)["total"] > 0
        exported = data(
            await routed(
                "cad_export_electrical_project",
                {
                    "project_id": identifier,
                    "request_id": "app-export-0001",
                },
                "broker-export-0001",
            )
        )
        receipt = data(
            await routed("cad_get_transaction", {"request_id": "app-export-0001", "include_result": True})
        )
        assert receipt["state"] == "succeeded" and receipt["result"]["path"] == exported["path"]
        duplicate = await routed(
            "cad_export_electrical_project",
            {
                "project_id": identifier,
                "request_id": "app-export-0001",
            },
            "broker-export-0001",
        )
        assert duplicate.is_error  # Broker journal does not replay writes.
        outer = data(await broker.call_tool("get_request_status", {"request_id": "broker-export-0001"}))
        assert outer["status"] == "completed"
        wrong = {"root_id": "fixture", "relative_path": "missing.dxf"}
        errors = await asyncio.gather(direct.call_tool("cad_inspect", wrong), routed("cad_inspect", wrong))
        assert all(r.is_error for r in errors)
        assert errors[0].content == errors[1].content
        denied = await routed(
            "cad_highlight_source_object",
            {
                "project_id": identifier,
                "device_id": "missing",
                "request_id": "app-denied-0001",
            },
            "broker-denied-0001",
        )
        assert denied.is_error
        assert (
            data(await direct.call_tool("cad_get_transaction", {"request_id": "app-denied-0001"}))["state"]
            == "not_found"
        )
        return {
            "tool_definitions_equal": len(definitions),
            "workflow_guidance_preserved": True,
            "two_broker_frontends": True,
            "cross_route_idempotency": True,
            "inventory_equal": True,
            "separate_journals_verified": True,
            "app_errors_preserved": True,
            "native_highlighting_blocked_without_dispatch": True,
        }


def run(repo, broker_python):
    parent = repo / ".local/validation"
    parent.mkdir(parents=True, exist_ok=True)
    metadata = broker_metadata(broker_python)
    required = {"allowed_write_tools", "session_mode", "resource_id"}
    if not required <= set(metadata["fields"]):
        raise ValueError(
            "Selected broker runtime lacks the migration contract; use a current isolated installation"
        )
    with tempfile.TemporaryDirectory(prefix="broker-fixture-", dir=parent) as temp:
        workspace = Path(temp)
        drawings = workspace / "drawings"
        drawings.mkdir()
        doc = ezdxf.new("R2018")
        block = doc.blocks.new("COMPONENT")
        block.add_attdef("TAG1", (0, 0))
        block.add_attdef("DESC1", (0, 1))
        doc.modelspace().add_blockref("COMPONENT", (0, 0)).add_auto_attribs(
            {"TAG1": "MTR1", "DESC1": "Fixture motor"}
        )
        drawing = drawings / "fixture.dxf"
        doc.saveas(drawing)
        before = file_hash(drawing)
        config = workspace / "config.json"
        atomic_json(config, {"roots": {"fixture": str(drawings)}, "state_dir": str(workspace / "app-state")})
        state = workspace / "broker-state"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        command = [str(broker_python), "-m", "universal_tools", "--state", str(state)]
        subprocess.run(
            command + ["init", "--port", str(port)], check=True, stdout=subprocess.DEVNULL, timeout=30
        )
        manifest = broker_manifest(repo, config)
        # Exercise the running app environment; never borrow a native project's configuration.
        manifest["transport"]["command"] = sys.executable
        atomic_json(state / "services/autocad.json", manifest)
        settings = json.loads((state / "settings.json").read_text())  # This fixture's credentials only.
        with (workspace / "broker.log").open("wb") as log:
            process = subprocess.Popen(command + ["serve"], stdin=subprocess.DEVNULL, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 45
                with httpx.Client(trust_env=False, timeout=0.5) as client:
                    while True:
                        if process.poll() is not None:
                            raise RuntimeError("Disposable broker exited before readiness")
                        try:
                            response = client.get(
                                f"http://127.0.0.1:{port}/health",
                                headers={"Authorization": "Bearer " + settings["token"]},
                            )
                            if response.status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        if time.monotonic() > deadline:
                            raise TimeoutError("Disposable broker readiness timed out")
                        time.sleep(0.1)
                result = asyncio.run(exercise(repo, config, broker_python, state))
                assert file_hash(drawing) == before
                return {
                    "passed": True,
                    "broker_version": metadata["version"],
                    "broker_code_sha256": metadata["code_sha256"],
                    **result,
                    "source_preserved": True,
                    "host_acceptance": "unassessed",
                    "migration_performed": False,
                }
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker-python", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    result = run(repo, args.broker_python.resolve(strict=True))
    atomic_json(repo / ".local/validation/broker-compatibility.json", result)
    print(json.dumps(result))
