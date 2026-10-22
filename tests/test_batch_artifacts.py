import asyncio
import base64
import threading
import time

import pytest
from mcp import Client

from autocad_mcp.artifacts import Artifacts
from autocad_mcp.batch_jobs import BatchJobs
from autocad_mcp.server import create_server
from autocad_mcp.service import DrawingService


def wait_job(jobs, started):
    deadline = time.monotonic() + 30
    while True:
        value = jobs.get(started["job_id"], started["access_token"])
        if value["state"] in {"completed", "cancelled", "unknown"}:
            return value
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_job_cancellation_access_and_independent_effect_counts(drawing_service, monkeypatch):
    service, source = drawing_service
    jobs = BatchJobs(service)
    entered, release = threading.Event(), threading.Event()
    calls = []
    original = service._index_file

    def counted(*args, **kwargs):
        calls.append(args)
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_index_file", counted)
    before = (source / "sample.dxf").read_bytes()
    first = jobs.start("test", 0, 5)
    assert entered.wait(10)
    with pytest.raises(ValueError, match="unauthorized"):
        jobs.cancel(first["job_id"], "foreign")
    assert jobs.cancel(first["job_id"], first["access_token"])["state"] == "cancel_requested"
    release.set()
    result = wait_job(jobs, first)
    assert result["state"] == "cancelled" and result["completed"] == 1
    assert len(calls) == 1
    assert jobs.cancel(first["job_id"], first["access_token"])["state"] == "cancelled"
    assert (source / "sample.dxf").read_bytes() == before
    assert BatchJobs(service).get(first["job_id"], first["access_token"])["state"] == "cancelled"


def test_queued_job_cancel_and_lost_owner_never_reexecute(drawing_service):
    import hashlib
    import secrets

    service, _ = drawing_service
    jobs = BatchJobs(service)
    jobs.slots.acquire()
    # Occupy all local admission slots before dispatching the queued batch.
    for _ in range(service.config.max_concurrent_requests - 1):
        jobs.slots.acquire()
    queued = jobs.start("test", 0, 1)
    assert jobs.cancel(queued["job_id"], queued["access_token"])["state"] == "cancelled"
    for _ in range(service.config.max_concurrent_requests):
        jobs.slots.release()
    assert wait_job(jobs, queued)["state"] == "cancelled"
    token = secrets.token_hex(32)
    with jobs.connect() as db:
        db.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "lost",
                hashlib.sha256(token.encode()).hexdigest(),
                jobs.scope,
                "test",
                0,
                1,
                "running",
                0,
                0,
                1,
                "indexing",
                None,
            ),
        )
    assert jobs.get("lost", token)["state"] == "unknown"
    assert BatchJobs(service).get("lost", token)["state"] == "unknown"


def test_job_binds_selected_paths_and_hashes_before_dispatch(drawing_service):
    service, source = drawing_service
    service._index_file("test", "sample.dxf")
    with service.database() as db:
        prior = db.execute("SELECT * FROM documents").fetchall()
    jobs = BatchJobs(service)
    for _ in range(service.config.max_concurrent_requests):
        jobs.slots.acquire()
    try:
        started = jobs.start("test", 1, 1)
        selected = jobs.get(started["job_id"], started["access_token"])["selection"]
        assert selected["items"][0]["relative_path"] == "sample.dxf"
        import ezdxf

        changed = ezdxf.new("R2018")
        changed.modelspace().add_text("changed after submission")
        changed.saveas(source / "sample.dxf")
        (source / "aaa.dxf").write_bytes((source / "sample.dxf").read_bytes())
    finally:
        for _ in range(service.config.max_concurrent_requests):
            jobs.slots.release()
    finished = wait_job(jobs, started)
    assert finished["selection"] == selected
    result = finished["result"]["results"]
    assert len(result) == 1 and result[0]["path"] == "sample.dxf"
    assert result[0]["status"] == "failed" and "since job submission" in result[0]["error"]
    with service.database() as db:
        assert db.execute("SELECT * FROM documents").fetchall() == prior


def test_owner_close_cancels_queued_jobs_and_rejects_new_work(drawing_service):
    from autocad_mcp.coordination import ResourceBusy

    service, _ = drawing_service
    jobs = BatchJobs(service)
    for _ in range(service.config.max_concurrent_requests):
        jobs.slots.acquire()
    started = jobs.start("test", 0, 1)
    assert jobs.close(timeout=0)["still_active"] == 1
    with pytest.raises(ResourceBusy, match="shutting down"):
        jobs.start("test", 0, 1)
    for _ in range(service.config.max_concurrent_requests):
        jobs.slots.release()
    assert wait_job(jobs, started)["state"] == "cancelled"


def test_process_loss_preserves_unknown_job_and_one_effect(drawing_service, tmp_path):
    import json
    import os
    import signal
    import subprocess
    import sys

    service, source = drawing_service
    marker, info = tmp_path / "effect.txt", tmp_path / "private-job.json"
    helper = tmp_path / "synthetic_job_owner.py"
    helper.write_text(
        "import json,sys,time,os\nfrom pathlib import Path\n"
        "from autocad_mcp.config import Config\nfrom autocad_mcp.service import DrawingService\n"
        "from autocad_mcp.batch_jobs import BatchJobs\n"
        "s=DrawingService(Config.load(sys.argv[1]))\n"
        "def fake(*args,**kwargs):\n Path(sys.argv[2]).write_text('one-effect')\n time.sleep(60)\n"
        "s._index_file=fake\nj=BatchJobs(s).start('test',0,1)\n"
        "j['owner_pid']=os.getpid()\np=Path(sys.argv[3]); t=p.with_suffix('.tmp'); t.write_text(json.dumps(j)); t.replace(p)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [sys.executable, str(helper), str(source.parent / "config.json"), str(marker), str(info)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 20
        while not (info.exists() and marker.exists()):
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(0.02)
        job = json.loads(info.read_bytes())
        assert job["owner_pid"] != os.getpid()
        os.kill(job["owner_pid"], signal.SIGTERM)
        process.wait(timeout=10)
        deadline = time.monotonic() + 10
        while True:
            state = BatchJobs(service).get(job["job_id"], job["access_token"])
            if state["state"] == "unknown":
                break
            assert time.monotonic() < deadline
            time.sleep(0.02)
        assert state["state"] == "unknown" and marker.read_text() == "one-effect"
        assert BatchJobs(service).get(job["job_id"], job["access_token"])["state"] == "unknown"
        assert marker.read_text() == "one-effect"
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


@pytest.mark.anyio
async def test_duplicate_start_receipt_does_not_duplicate_real_job_dispatch(drawing_service, monkeypatch):
    service, _ = drawing_service
    entered, release = threading.Event(), threading.Event()
    original = service._index_file
    effects = []

    def block(*args, **kwargs):
        effects.append(args)
        entered.set()
        assert release.wait(15)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_index_file", block)
    async with Client(create_server(service), mode="2026-07-28", cache=None) as client:
        arguments = {"root_id": "test", "offset": 1, "limit": 1, "request_id": "batch-start-once"}
        first = await client.call_tool("cad_start_index_job", arguments)
        assert not first.is_error
        assert await asyncio.to_thread(entered.wait, 10)
        second = await client.call_tool("cad_start_index_job", arguments)
        assert second.structured_content["job_id"] == first.structured_content["job_id"]
        assert second.structured_content["transaction"]["replayed"]
        release.set()
        result = await asyncio.to_thread(wait_job, service.batch_jobs, first.structured_content)
        assert result["state"] == "completed" and len(effects) == 1


@pytest.mark.anyio
async def test_index_progress_is_per_request_and_old_schema_stays_clean(drawing_service):
    service, _ = drawing_service
    events = []

    async def progress(completed, total, message):
        events.append((completed, total, message))

    async with Client(create_server(service), mode="2026-07-28", cache=None) as client:
        tool = next(t for t in (await client.list_tools()).tools if t.name == "cad_index_project")
        assert "ctx" not in tool.input_schema["properties"]
        result = await client.call_tool(
            "cad_index_project",
            {"root_id": "test", "limit": 1, "request_id": "progress-one"},
            progress_callback=progress,
        )
        assert not result.is_error
        assert events[0][0] == 0 and events[-1][0] == 1
        assert [entry[0] for entry in events] == sorted(entry[0] for entry in events)


@pytest.mark.anyio
async def test_artifact_receipt_scope_hash_bounds_notifications_and_resource_parity(drawing_service):
    service, source = drawing_service
    server = create_server(service)
    async with Client(server, mode="2026-07-28", cache=None) as client:
        preview = await client.call_tool(
            "cad_render_preview",
            {
                "root_id": "test",
                "relative_path": "sample.pdf",
                "width": 300,
                "request_id": "artifact-preview",
            },
        )
        assert not preview.is_error
        expected = preview.structured_content["sha256"]
        async with client.listen(resources_list_changed=True) as events:
            got = await client.call_tool(
                "cad_get_artifact", {"request_id": "artifact-preview", "sha256": expected}
            )
            assert not got.is_error
            await asyncio.wait_for(anext(events), timeout=10)
        descriptor = got.structured_content
        resource = (await client.read_resource(descriptor["uri"])).contents[0]
        assert base64.b64decode(resource.blob) == base64.b64decode(descriptor["base64"])
        with pytest.raises(ValueError):
            Artifacts(service).describe("artifact-preview", "0" * 64)
        with pytest.raises(ValueError):
            Artifacts(service).describe("artifact-preview", expected, length=65537)
        root = source.parent / "other-root"
        root.mkdir()
        import dataclasses

        changed = DrawingService(dataclasses.replace(service.config, roots={"test": root}))
        with pytest.raises(ValueError, match="authorization"):
            Artifacts(changed).describe("artifact-preview", expected)
        from pathlib import Path

        Path(preview.structured_content["preview_path"]).write_bytes(b"tampered")
        with pytest.raises(Exception):
            await client.read_resource(descriptor["uri"])
