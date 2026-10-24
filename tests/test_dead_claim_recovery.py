from types import SimpleNamespace

import pytest

from autocad_mcp.recovery import reconcile_dead_claims


class Identity:
    def __init__(self, pid):
        self.pid = pid

    def model_dump(self, **kwargs):
        return {"host_id": "a" * 64, "pid": self.pid, "created": "123", "executable": "C:\\fixture.exe"}


def record(**updates):
    values = dict(
        app_id="autocad",
        resource_id="a" * 32,
        state="active",
        ownership="private",
        cleanup_mode="terminate",
        containment="windows_job",
        process=Identity(101),
        owner=Identity(100),
        members=[Identity(102)],
        receipt=None,
        recovery_barrier=None,
        reconciliation=None,
        label="AutoCAD extraction " + "b" * 32,
        revision="c" * 64,
    )
    return SimpleNamespace(**{**values, **updates})


class Owner:
    def __init__(self, row, states):
        self.effects = []
        self.ledger = SimpleNamespace(
            records=lambda: [row],
            driver=SimpleNamespace(state=lambda value: states.get(value["pid"], "absent")),
        )

    def reconcile(self, resource, revision, evidence):
        self.effects.append((resource, revision, evidence))
        return SimpleNamespace(resource_id=resource)


def test_metadata_retirement_requires_dead_members_and_empty_named_job():
    row = record()
    owner = Owner(row, {})
    result = reconcile_dead_claims(owner, job_probe=lambda token: "named_private_job_empty")
    assert result["retired"] == [row.resource_id]
    assert "no process stop" in owner.effects[0][2]
    assert "journal reset" in owner.effects[0][2]


@pytest.mark.parametrize(
    "updates,states",
    [
        ({}, {100: "alive"}),
        ({}, {100: "unknown"}),
        ({}, {101: "alive"}),
        ({}, {102: "alive"}),
        ({}, {102: "unknown"}),
        ({"ownership": "attached", "cleanup_mode": "report"}, {}),
        ({"ownership": "shared", "cleanup_mode": "report"}, {}),
        ({"recovery_barrier": "dirty/uncertain"}, {}),
        ({"state": "uncertain"}, {}),
        ({"receipt": {"outcome": "uncertain"}}, {}),
        ({"label": "Unrecognized private program"}, {}),
    ],
)
def test_live_foreign_shared_and_uncertain_claims_are_preserved(updates, states):
    owner = Owner(record(**updates), states)
    result = reconcile_dead_claims(
        owner, job_probe=lambda token: (_ for _ in ()).throw(AssertionError("Do not query a protected job"))
    )
    assert result["retired"] == [] and owner.effects == []


def test_live_named_job_and_job_query_failure_remain_unmodified():
    for probe in (lambda token: None, lambda token: (_ for _ in ()).throw(OSError("query unavailable"))):
        owner = Owner(record(), {})
        result = reconcile_dead_claims(owner, job_probe=probe)
        assert not result["retired"] and not owner.effects
