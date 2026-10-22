"""Pure registry/stub checks: no process launch, MCP connection or native API."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from autocad_mcp.owned_resources import OwnedResources


def test_only_exclusive_launches_accept_cleanup_and_snapshots_cannot_mutate_history():
    resources = OwnedResources()
    for ownership in ("attached_user_owned", "shared"):
        with pytest.raises(ValueError, match="cannot be owned"):
            resources.register(lambda: pytest.fail("Foreign cleanup"), "native", ownership=ownership)
    resource = resources.register(lambda: None, "worker")
    resources.started(resource, 42, 123456)
    snapshot = resources.snapshot()
    snapshot["active"][0]["pid"] = 999
    assert resources.snapshot()["active"][0]["pid"] == 42
    resources.finished(resource)
    snapshot = resources.snapshot()
    snapshot["recent"][0]["creation_identity"] = 0
    assert resources.snapshot()["recent"][0]["creation_identity"] == 123456
    assert resources.snapshot()["recent"][0]["state"] == "handles_released"


def test_close_calls_owned_handles_once_and_never_admits_a_replacement():
    resources, effects = OwnedResources(), []
    for index in range(16):
        resources.register(lambda index=index: effects.append(index), "worker")
    with pytest.raises(RuntimeError, match="capacity"):
        resources.register(lambda: None, "worker")
    with ThreadPoolExecutor(4) as pool:
        snapshots = list(pool.map(lambda _: resources.close(), range(4)))
    assert sorted(effects) == list(range(16))
    assert all(not snapshot["accepting"] for snapshot in snapshots)
    with pytest.raises(RuntimeError, match="closed"):
        resources.register(lambda: pytest.fail("Replacement was started"), "worker")


def test_failed_cleanup_keeps_uncertainty_without_replay():
    resources, effects = OwnedResources(), []

    def fail():
        effects.append("called")
        raise OSError("Synthetic handle failure")

    resource = resources.register(fail, "worker")
    resources.started(resource, 42, 123456)
    snapshot = resources.close()
    assert snapshot["active"][0]["state"] == "cleanup_unconfirmed"
    assert snapshot["active"][0]["creation_identity"] == 123456
    resources.close()
    assert effects == ["called"]
