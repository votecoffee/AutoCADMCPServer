"""App-owned index batches with durable intent, capability access and cooperative stop."""

import hashlib
import json
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

from .coordination import ResourceBusy


class BatchJobs:
    def __init__(self, service):
        self.service = service
        self.path = service.config.state / "batch-jobs.sqlite3"
        self.guard = threading.Lock()
        self.active = 0
        self.closing = threading.Event()
        self.threads = {}
        self.slots = threading.BoundedSemaphore(service.config.max_concurrent_requests)
        self.scope = hashlib.sha256(
            json.dumps(
                {
                    "roots": {key: str(path) for key, path in service.config.roots.items()},
                    "signature": service.signature,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, token TEXT, scope TEXT, "
                "root TEXT, offset INTEGER, size INTEGER, state TEXT, cancel INTEGER, "
                "completed INTEGER, total INTEGER, stage TEXT, result TEXT)"
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def activity(self):
        with self.guard:
            return self.active

    def close(self, timeout=2):
        """Stop admission and request only this owner's jobs to stop; never replay."""
        with self.guard:
            self.closing.set()
            threads = dict(self.threads)
        with self.connect() as db:
            db.executemany(
                "UPDATE jobs SET cancel=1,state=CASE WHEN state='queued' THEN 'cancelled' ELSE 'cancel_requested' END WHERE id=? AND state IN ('queued','running')",
                ((job,) for job in threads),
            )
        deadline = time.monotonic() + timeout
        for thread in threads.values():
            thread.join(timeout=max(0, deadline - time.monotonic()))
        return {"still_active": sum(thread.is_alive() for thread in threads.values())}

    def start(self, root_id, offset=0, limit=5):
        if self.closing.is_set():
            raise ResourceBusy("Index job owner is shutting down")
        if root_id not in self.service.config.roots or offset < 0 or not 1 <= limit <= 5:
            raise ValueError("Select a configured root, nonnegative offset and 1..5 files")
        from .service import sha256

        selection = self.service.inventory(root_id, True, offset, limit)
        selection = {
            "total": selection["total"],
            "items": [
                {
                    "relative_path": item["relative_path"],
                    "sha256": sha256(self.service.config.resolve(root_id, item["relative_path"])),
                }
                for item in selection["items"]
            ],
        }
        job, token = uuid.uuid4().hex, secrets.token_hex(32)
        lease = self.service.coordinator.lock("batch-job:" + job)
        lease.__enter__()
        counted = False
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute(
                    "SELECT count(*) FROM jobs WHERE state IN ('queued','running','cancel_requested','unknown')"
                ).fetchone()[0] >= min(
                    self.service.config.max_index_jobs,
                    self.service.config.max_concurrent_requests + self.service.config.max_queued_requests,
                ):
                    raise ResourceBusy("Index job capacity or unresolved outcomes require inspection")
                db.execute(
                    "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        job,
                        hashlib.sha256(token.encode()).hexdigest(),
                        self.scope,
                        root_id,
                        offset,
                        limit,
                        "queued",
                        0,
                        0,
                        len(selection["items"]),
                        "queued",
                        json.dumps({"selection": selection}),
                    ),
                )
            with self.guard:
                if self.closing.is_set():
                    raise ResourceBusy("Index job owner is shutting down; inspect submitted intent")
                self.active += 1
                counted = True
                thread = threading.Thread(
                    target=self._run, args=(job, lease), daemon=True, name="autocad-index-job"
                )
                self.threads[job] = thread
                thread.start()
        except BaseException:
            if counted:
                with self.guard:
                    self.active -= 1
                    self.threads.pop(job, None)
            lease.__exit__(None, None, None)
            raise
        return {
            "job_id": job,
            "access_token": token,
            "state": "queued",
            "scope": "Keep this capability private; it is not a verified MCP principal or write approval",
        }

    def _row(self, job, token):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
        if (
            row is None
            or row["scope"] != self.scope
            or not secrets.compare_digest(row["token"], hashlib.sha256(token.encode()).hexdigest())
        ):
            raise ValueError("Unknown or unauthorized index job")
        return dict(row)

    def get(self, job, token):
        row = self._row(job, token)
        if row["state"] in {"queued", "running", "cancel_requested"}:
            try:
                with self.service.coordinator.lock("batch-job:" + job, timeout=0):
                    with self.connect() as db:
                        db.execute(
                            "UPDATE jobs SET state='unknown',stage='owner_lost' WHERE id=? AND state IN ('queued','running','cancel_requested')",
                            (job,),
                        )
                    row = self._row(job, token)
            except ResourceBusy:
                pass
        payload = json.loads(row["result"]) if row["result"] else {}
        return {
            "job_id": job,
            "state": row["state"],
            "completed": row["completed"],
            "total": row["total"],
            "stage": row["stage"],
            "cancel_requested": bool(row["cancel"]),
            "selection": payload.get("selection"),
            "result": payload.get("output"),
            "boundary": "Units are files examined; cancellation does not undo per-file commits or stop an in-flight converter",
        }

    def cancel(self, job, token):
        self._row(job, token)
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET cancel=1,state=CASE WHEN state='queued' THEN 'cancelled' ELSE 'cancel_requested' END WHERE id=? AND state IN ('queued','running')",
                (job,),
            )
        return self.get(job, token)

    def _cancelled(self, job):
        if self.closing.is_set():
            return True
        with self.connect() as db:
            return bool(db.execute("SELECT cancel FROM jobs WHERE id=?", (job,)).fetchone()[0])

    def _run(self, job, lease):
        try:
            with self.slots:
                with self.connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    row = dict(db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone())
                    row["cancel"] = row["cancel"] or self.closing.is_set()
                    db.execute(
                        "UPDATE jobs SET state=? WHERE id=?",
                        ("cancelled" if row["cancel"] else "running", job),
                    )
                if row["cancel"]:
                    return
                payload = json.loads(row["result"])

                def progress(completed, total, stage):
                    with self.connect() as db:
                        db.execute(
                            "UPDATE jobs SET completed=?,total=?,stage=? WHERE id=?",
                            (completed, total, stage, job),
                        )

                result = self.service.index(
                    row["root"],
                    row["offset"],
                    row["size"],
                    progress=progress,
                    cancelled=lambda: self._cancelled(job),
                    selection=payload["selection"],
                )
                with self.connect() as db:
                    db.execute(
                        "UPDATE jobs SET state=?,stage='finished',result=? WHERE id=?",
                        (
                            "cancelled" if result["cancelled"] else "completed",
                            json.dumps({**payload, "output": result}),
                            job,
                        ),
                    )
        except BaseException:
            with self.connect() as db:
                db.execute("UPDATE jobs SET state='unknown',stage='inspection_required' WHERE id=?", (job,))
        finally:
            lease.__exit__(None, None, None)
            with self.guard:
                self.active -= 1
                self.threads.pop(job, None)
