"""Pure app facade/real durable-ledger checks with a harmless in-memory process driver."""

import os
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from universal_tools.resources import ResourceLedger

from autocad_mcp.owned_resources import OwnedResources


class Driver:
    def __init__(self):
        self.processes, self.groups, self.effects = {}, [], []
        self.processes[os.getpid()] = self.identity(os.getpid(), 1000)

    @staticmethod
    def identity(pid, created):
        return {
            "host_id": "a" * 64,
            "pid": pid,
            "created": str(created),
            "executable": os.path.normcase(sys.executable),
        }

    def capture(self, pid):
        return self.processes[pid]

    def state(self, identity):
        current = self.processes.get(identity["pid"])
        return "absent" if current is None else "alive" if current == identity else "different"

    def open(self, identity):
        assert self.state(identity) == "alive"

        class Handle:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return Handle()

    def create_suspended(self, argv, **options):
        driver = self
        pid = 9000000 + len(self.groups)
        identity = self.identity(pid, 2000 + len(self.groups))
        self.processes[pid] = identity

        class Group:
            fail_stop = False

            def __init__(self):
                self.pid, self.identity = pid, identity

            def resume(self):
                driver.effects.append((pid, "resume"))

            def identities(self):
                return [identity] if driver.state(identity) == "alive" else []

            def stop(self):
                driver.effects.append((pid, "stop"))
                if self.fail_stop:
                    raise OSError("Synthetic stop failure")
                driver.processes.pop(pid, None)

            def close(self):
                driver.processes.pop(pid, None)

        group = Group()
        self.groups.append(group)
        return group


def fixture(tmp_path, maximum=32):
    driver = Driver()
    ledger = ResourceLedger(tmp_path, driver=driver, max_active_per_app=maximum)
    return OwnedResources(ledger=ledger), driver


def test_concurrent_close_is_journaled_once_and_fences_new_launches(tmp_path):
    resources, driver = fixture(tmp_path, maximum=2)
    for _ in range(2):
        resources.launch_worker(["synthetic"], (), "unit")
    with pytest.raises(ValueError, match="limit"):
        resources.launch_worker(["synthetic"], (), "unit")
    with ThreadPoolExecutor(4) as pool:
        snapshots = list(pool.map(lambda _: resources.close(), range(4)))
    assert sum(effect == "stop" for _, effect in driver.effects) == 2
    assert all(not snapshot["accepting"] for snapshot in snapshots)
    assert all(record.receipt.outcome == "terminated" for record in resources.ledger.records())
    with pytest.raises(RuntimeError, match="closing"):
        resources.launch_worker(["synthetic"], (), "unit")


def test_attached_and_foreign_generation_resources_are_not_closed(tmp_path, monkeypatch):
    resources, driver = fixture(tmp_path)
    driver.processes[8000000] = driver.identity(8000000, 500)  # Existing user software predates the owner.
    attachment = resources.attach(8000000)
    assert attachment.ownership == "attached" and attachment.cleanup_mode == "report"
    foreign = resources.ledger.owner("autocad")
    launch = foreign.launch(["synthetic"], "Other generation", allow_termination=True)
    resources.close()
    assert driver.state(attachment.process.model_dump()) == "alive"
    assert driver.state(launch.group.identity) == "alive"
    assert not any(effect == "stop" for _, effect in driver.effects)
    resources.detach(attachment.resource_id, uncertain=True)
    record = resources.ledger.get(attachment.resource_id)
    assert record.state == "released" and record.recovery_barrier
    snapshot = resources.snapshot()
    snapshot["durable_resources"][0]["pid"] = 123
    assert resources.snapshot()["durable_resources"][0]["pid"] == 8000000
    monkeypatch.setattr(resources.ledger, "records", lambda: pytest.fail("Status performed ledger I/O"))
    assert resources.snapshot()["attached_count"] == 0


def test_uncertain_cleanup_keeps_original_receipt_without_replay(tmp_path):
    resources, driver = fixture(tmp_path)
    launch = resources.launch_worker(["synthetic"], (), "unit")
    launch.group.fail_stop = True
    with pytest.raises(RuntimeError, match="uncertain"):
        launch.close()
    record = resources.ledger.records()[0]
    original = record.receipt.model_dump()
    assert record.state == "uncertain" and original["outcome"] == "uncertain"
    resources.close()
    resources.close()
    assert resources.ledger.get(record.resource_id).receipt.model_dump() == original
    assert sum(effect == "stop" for _, effect in driver.effects) == 1
