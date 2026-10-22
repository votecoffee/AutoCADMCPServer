"""Live exclusive-resource registry; durable recovery awaits the shared package API."""

import os
import threading
import uuid
from collections import deque


class OwnedResources:
    def __init__(self):
        self.guard = threading.Lock()
        self.accepting = True
        self.active = {}
        self.recent = deque(maxlen=32)

    def register(self, cleanup, kind, *, ownership="launched_exclusive"):
        if ownership != "launched_exclusive":
            raise ValueError("Attachments and shared native leases cannot be owned by this registry")
        with self.guard:
            if not self.accepting or len(self.active) >= 16:
                raise RuntimeError("Owned-resource admission is closed or at capacity")
            identifier = uuid.uuid4().hex
            self.active[identifier] = (
                {
                    "id": identifier,
                    "owner_pid": os.getpid(),
                    "kind": kind,
                    "ownership": "launched_exclusive",
                    "state": "starting",
                    "pid": None,
                    "creation_identity": None,
                },
                cleanup,
            )
            return identifier

    def started(self, identifier, pid, creation_identity, *, suspended=False):
        with self.guard:
            record, _ = self.active[identifier]
            record.update(
                pid=pid,
                creation_identity=creation_identity,
                state=("bound_suspended" if suspended else "running")
                if self.accepting
                else "close_requested",
            )

    def resumed(self, identifier):
        with self.guard:
            record, _ = self.active[identifier]
            if self.accepting:
                record["state"] = "running"

    def finished(self, identifier):
        with self.guard:
            record, _ = self.active.pop(identifier)
            self.recent.append({**record, "state": "handles_released"})

    def unconfirmed(self, identifier):
        with self.guard:
            if identifier in self.active:
                self.active[identifier][0]["state"] = "cleanup_unconfirmed"

    def snapshot(self):
        with self.guard:
            return {
                "scope": "This process only; retained exclusive worker/job handles; no PID/name cleanup",
                "accepting": self.accepting,
                "active_count": len(self.active),
                "active": [dict(record) for record, _ in self.active.values()],
                "recent": [dict(record) for record in self.recent],
                "durable_recovery": "blocked_pending_shared_ledger_API",
                "attached_native_policy": "GetActiveObject only; release COM references, never Quit/Close/save",
                "shared_native_policy": "No app-launched shared native instance is supported; no ownership transfer",
            }

    def close(self):
        with self.guard:
            self.accepting = False
            callbacks = []
            for record, cleanup in self.active.values():
                if record["state"] not in {"close_requested", "cleanup_unconfirmed"}:
                    record["state"] = "close_requested"
                    callbacks.append((record["id"], cleanup))
        for identifier, cleanup in callbacks:
            try:
                cleanup()
            except Exception:
                with self.guard:
                    if identifier in self.active:
                        self.active[identifier][0]["state"] = "cleanup_unconfirmed"
        return self.snapshot()


owned_resources = OwnedResources()
