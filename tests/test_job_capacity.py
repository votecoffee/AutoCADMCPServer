"""File/database-only admission test; no job thread, worker or MCP server starts."""

import dataclasses

import pytest

from autocad_mcp import batch_jobs
from autocad_mcp.batch_jobs import BatchJobs
from autocad_mcp.coordination import ResourceBusy
from autocad_mcp.service import DrawingService


def test_unknown_job_retains_bounded_admission_without_starting_a_thread(drawing_service, monkeypatch):
    original, _ = drawing_service
    service = DrawingService(dataclasses.replace(original.config, max_index_jobs=1))
    jobs = BatchJobs(service)
    with jobs.connect() as db:
        db.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "retained-unknown",
                "a" * 64,
                jobs.scope,
                "test",
                0,
                1,
                "unknown",
                0,
                0,
                1,
                "inspection_required",
                None,
            ),
        )
    monkeypatch.setattr(
        batch_jobs.threading, "Thread", lambda *args, **kwargs: pytest.fail("Capacity bypass")
    )
    with pytest.raises(ResourceBusy, match="inspection"):
        jobs.start("test", 0, 1)
    with jobs.connect() as db:
        assert db.execute("SELECT id,state FROM jobs").fetchall()[0]["state"] == "unknown"
        assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 1
