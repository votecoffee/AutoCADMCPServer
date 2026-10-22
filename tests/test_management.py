"""Only synthetic counters, metadata and private registries; no native restart effects."""

import concurrent.futures
import json
import secrets
import threading

from universal_tools.management import ManagementClient

from autocad_mcp import __version__
from autocad_mcp.management import PLUGIN_ID, RESTART_REASON, Activity, Reporting


class Inventory:
    def refresh(self):
        return [{"plugin_id": PLUGIN_ID, "installed": "0.1.0", "available": None}], None


def reporting(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOCAD_MCP_PLUGIN_VERSION", "0.1.0")
    publisher = tmp_path / "publisher"
    (publisher / "plugins/autocad").mkdir(parents=True, exist_ok=True)
    (publisher / "plugins/autocad/plugin.json").write_text(json.dumps({"version": "99.0.0"}))
    (publisher / "pyproject.toml").write_text('[project]\nname="autocad-mcp-server"\nversion="99.0.0"\n')
    activity = Activity()
    reporter = Reporting(
        activity.status,
        registry=tmp_path / "registry",
        publisher=publisher,
        inventory=Inventory(),
        interval=3600,
    )
    reporter.refresh_versions()
    return reporter, activity, ManagementClient(tmp_path / "registry")


def restart(client, row, key=None):
    return client.restart(row["app_id"], row["instance_id"], row["revision"], key or secrets.token_hex(16))


def test_cached_versions_and_status_do_not_read_projects_or_inventory(tmp_path, monkeypatch):
    reporter, activity, _ = reporting(tmp_path, monkeypatch)
    monkeypatch.setattr(reporter.inventory, "refresh", lambda: (_ for _ in ()).throw(AssertionError()))
    status = reporter.status()
    assert status.versions["app"].running == __version__
    assert status.versions["app"].available == "99.0.0" and status.versions["app"].update_pending
    assert status.versions["plugin"].running == "0.1.0" and status.versions["plugin"].update_pending
    assert status.versions["framework"].available is None
    assert status.versions["sdk"].available is None
    assert status.restart_reason == RESTART_REASON and not status.restart_allowed
    status.versions["app"] = status.versions["app"].model_copy(update={"installed": "mutated"})
    assert reporter.status().versions["app"].installed != "mutated"
    with activity.operation():
        assert reporter.status().state == "busy" and reporter.status().active_operations == 1
    assert reporter.status().active_operations == 0


def test_actual_http_denies_stale_busy_and_concurrent_restart_duplicates(tmp_path, monkeypatch):
    reporter, activity, client = reporting(tmp_path, monkeypatch)
    effects = []
    reporter.agent.restart_callback = lambda request: effects.append(request.request_id)
    with reporter:
        row = client.snapshot()["services"][0]
        assert row["plugin_id"] == PLUGIN_ID and row["status"]["restart_reason"] == RESTART_REASON
        with activity.operation():
            assert restart(client, row)["outcome"] == "blocked"
            busy = client.snapshot()["services"][0]
            assert busy["status"]["active_operations"] == 1
            assert restart(client, busy)["outcome"] == "blocked"
        current = client.snapshot()["services"][0]
        key = secrets.token_hex(16)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: restart(client, current, key), range(4)))
        assert all(result == results[0] for result in results)
        assert results[0]["outcome"] == "blocked" and effects == []
        changed = {**current, "revision": "0" * 64}
        assert restart(client, changed, key)["outcome"] == "uncertain"
        safe = json.dumps(client.snapshot())
        assert reporter.agent.token not in safe and "endpoint" not in safe
    assert client.snapshot()["services"][0]["status"]["state"] == "stopped"


def test_lost_restart_intent_survives_instance_lifetime_without_effects(tmp_path, monkeypatch):
    first, _, client = reporting(tmp_path, monkeypatch)
    with first:
        key = secrets.token_hex(16)
        first.agent.journal.claim("autocad", "1" * 64, key)
        assert first.agent.pending_restarts()[0]["request_id"] == key
    second, _, _ = reporting(tmp_path, monkeypatch)
    assert first.agent.instance_id != second.agent.instance_id
    with second:
        row = next(
            row for row in client.snapshot()["services"] if row["instance_id"] == second.agent.instance_id
        )
        assert "prior restart" in row["status"]["restart_reason"]
        assert restart(client, row)["outcome"] == "blocked"
        assert second.agent.pending_restarts()[0]["request_id"] == key


def test_activity_counts_concurrent_work_and_exception_cleanup():
    activity = Activity()
    entered = threading.Barrier(3)
    finish = threading.Event()

    def work():
        with activity.operation():
            entered.wait(timeout=5)
            finish.wait(timeout=5)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(work) for _ in range(2)]
        entered.wait(timeout=5)
        assert activity.status()["active"] == 2
        finish.set()
        for job in jobs:
            job.result()
    assert activity.status()["active"] == 0
