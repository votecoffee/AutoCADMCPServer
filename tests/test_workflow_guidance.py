import asyncio
import base64
import hashlib
import json

import pytest
from mcp import Client
from mcp.types import Request, RequestParams
from universal_tools.models import BrokerError
from universal_tools.skill_catalog import SkillGet, SkillList, SkillParams
from universal_tools.skill_client import SkillClient

from autocad_mcp.guidance import WORKFLOW
from autocad_mcp.server import create_server
from autocad_mcp.workflow_guidance import BOOTSTRAP, Guidance, bootstrap_bytes


def content(result):
    item = result.contents[0]
    return item.text.encode() if hasattr(item, "text") else base64.b64decode(item.blob)


async def skills(client):
    return (
        await client.session.send_request(Request(method="skills/list", params=RequestParams()), SkillList)
    ).skills


@pytest.mark.anyio
async def test_real_direct_skill_resources_guide_pins_and_atomic_live_publication(drawing_service):
    service, _ = drawing_service
    guidance = Guidance()
    server = create_server(service, guidance=guidance)
    async with Client(server, mode="2026-07-28", extensions=[SkillClient()], cache=None) as client:
        before = (await client.list_tools()).model_dump(mode="json", by_alias=True)
        entry = (await skills(client))[0]
        got = await client.session.send_request(
            Request(method="skills/get", params=SkillParams(uri=entry["uri"])), SkillGet
        )
        assert got.skill == entry
        for resource in entry["resources"]:
            raw = content(await client.read_resource(resource["uri"]))
            assert len(raw) == resource["size"]
            assert "sha256:" + hashlib.sha256(raw).hexdigest() == resource["digest"]
        guide = (await client.call_tool("cad_get_workflow", {})).structured_content
        assert guide == json.loads(
            content(await client.read_resource("skill://drawing-analysis/workflow.json"))
        )
        for reference in guide["references"]:
            read = await client.call_tool(
                "cad_get_workflow_reference",
                {
                    "reference_id": reference["reference_id"],
                    "workflow_revision": guide["workflow_revision"],
                    "sha256": reference["sha256"],
                },
            )
            assert read.structured_content["text"].encode() == content(
                await client.read_resource(reference["uri"])
            )
        revision = guidance.catalog.revision
        with pytest.raises(ValueError):
            await guidance.publish("invalid canonical workflow", expected_revision=revision)
        assert (await skills(client))[0] == entry and guidance.catalog.revision == revision
        await guidance.publish(
            WORKFLOW.replace("workflow v1.", "workflow fixture v2."), expected_revision=revision
        )
        changed = (await client.call_tool("cad_get_workflow", {})).structured_content
        assert changed["workflow_revision"] != guide["workflow_revision"]
        assert (await skills(client))[0] != entry
        assert (
            await client.call_tool("cad_get_workflow", {"expected_revision": guide["workflow_revision"]})
        ).is_error
        assert (
            await client.call_tool(
                "cad_get_workflow_reference",
                {
                    "reference_id": guide["references"][0]["reference_id"],
                    "workflow_revision": guide["workflow_revision"],
                    "sha256": guide["references"][0]["sha256"],
                },
            )
        ).is_error
        with pytest.raises(BrokerError, match="revision"):
            await guidance.publish(WORKFLOW, expected_revision=revision)
        assert (await client.list_tools()).model_dump(mode="json", by_alias=True) == before
        await guidance.publish(None, expected_revision=guidance.catalog.revision)
        assert await skills(client) == []
        assert (await client.call_tool("cad_get_workflow", {})).is_error
        await guidance.publish(WORKFLOW, expected_revision=guidance.catalog.revision)
        assert len(await skills(client)) == 1


@pytest.mark.anyio
async def test_private_discovery_cache_notifications_and_reconnect(drawing_service, record_property):
    service, _ = drawing_service
    guidance = Guidance()
    server = create_server(service, guidance=guidance)
    async with Client(server, mode="2026-07-28", extensions=[SkillClient()]) as first:
        await first.list_tools()
        measured = server.discovery_round_trips["tools"]
        for _ in range(3):
            await first.list_tools()
        assert server.discovery_round_trips["tools"] == measured
        await first.list_resources()
        resource_count = server.discovery_round_trips["resources"]
        async with first.listen(resources_list_changed=True) as events:
            await guidance.publish(
                WORKFLOW.replace("workflow v1.", "workflow connected v2."),
                expected_revision=guidance.catalog.revision,
            )
            await asyncio.wait_for(anext(events), timeout=10)
            await first.list_resources()
        assert server.discovery_round_trips["resources"] > resource_count
        async with Client(server, mode="2026-07-28", extensions=[SkillClient()]) as second:
            before = server.discovery_round_trips["tools"]
            await second.list_tools()
            assert server.discovery_round_trips["tools"] > before
            assert (
                "connected v2"
                in content(await second.read_resource("skill://drawing-analysis/SKILL.md")).decode()
            )
    record_property(
        "discovery_round_trips",
        json.dumps(
            {
                "uncached_reference_requests": 4,
                "observed_rpc_for_four_lists": 1,
                "cache_ttl_ms": 2000,
                "scope": "independent client instances",
            }
        ),
    )


def test_packaged_bootstrap_is_generated_and_stays_small():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert (root / "plugins/autocad/skills/drawing-analysis/SKILL.md").read_bytes() == bootstrap_bytes()
    assert len(BOOTSTRAP.split()) < 230
