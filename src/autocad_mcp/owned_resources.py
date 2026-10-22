"""Cached observations plus the actual app supervisor's shared durable resource owner."""

import json
import os
import threading
import uuid


class OwnedResources:
    def __init__(self, registry=None, *, ledger=None):
        self.guard = threading.Lock()
        self.accepting = True
        self.registry = registry
        self.ledger = ledger
        self.owner = None
        self.launch_guard = threading.RLock()
        self.launches = {}
        self.durable_cache = {}
        self.close_warning = None

    def configure(self, registry=None):
        with self.launch_guard:
            if self.owner is not None:
                raise RuntimeError("Resource supervisor is already bound to its registry")
            self.registry = registry or os.environ.get("AUTOCAD_MCP_MANAGEMENT_REGISTRY")

    def _owner(self):
        # No process lookup, ledger I/O, or software launch occurs on import/status.
        if self.owner is None:
            from universal_tools.resources import ResourceLedger

            from .owned_process import StreamProcessDriver

            self.ledger = self.ledger or ResourceLedger(
                self.registry or os.environ.get("AUTOCAD_MCP_MANAGEMENT_REGISTRY"),
                driver=StreamProcessDriver(),
            )
            self.owner = self.ledger.owner("autocad")
        return self.owner

    def _observe(self, record):
        value = record.model_dump(mode="json")
        with self.guard:
            self.durable_cache[record.resource_id] = value
            if len(self.durable_cache) > 64:
                retired = next(
                    (
                        key
                        for key, row in self.durable_cache.items()
                        if row["state"] in {"released", "terminated", "failed"}
                    ),
                    None,
                )
                if retired is not None:
                    self.durable_cache.pop(retired)
        return record

    def launch_worker(self, argv, streams, kind):
        with self.launch_guard:
            with self.guard:
                if not self.accepting:
                    raise RuntimeError("Resource supervisor is closing")
            owner = self._owner()
            token = uuid.uuid4().hex
            label = "AutoCAD " + kind + " " + token
            environment = dict(os.environ)
            environment["AUTOCAD_MCP_OWNED_TREE"] = json.dumps(
                {
                    "registry": str(owner.ledger.directory.parent),
                    "owner_id": owner.owner_id,
                    "owner": owner.identity.model_dump(mode="json"),
                    "label": label,
                    "job_token": token,
                }
            )
            launch = owner.launch(
                argv,
                label,
                allow_termination=True,
                streams=streams,
                env=environment,
                max_processes=8,
                job_name="Local\\AutoCADMCP-" + token,
            )
            wrapped = TrackedLaunch(self, launch)
            self.launches[launch.resource_id] = wrapped
            self._observe(owner.ledger.get(launch.resource_id))
            return wrapped

    def attach(self, pid):
        with self.launch_guard:
            if not self.accepting:
                raise RuntimeError("Resource supervisor is closing")
            return self._observe(
                self._owner().remember_process(
                    pid,
                    "AutoCAD user-owned attachment",
                    ownership="attached",
                    kind="native-app",
                )
            )

    def detach(self, resource_id, *, uncertain=False):
        with self.launch_guard:
            if uncertain:
                self.owner.set_recovery_barrier(
                    resource_id,
                    "Native display outcome needs independent inspection; preserve app write receipt",
                )
            return self._observe(self.owner.release_attachment(resource_id))

    def snapshot(self):
        with self.guard:
            durable = [
                {
                    "resource_id": row["resource_id"],
                    "owner_id": row["owner_id"],
                    "ownership": row["ownership"],
                    "state": row["state"],
                    "label": row["label"],
                    "pid": row["process"]["pid"] if row["process"] else None,
                    "creation_identity": row["process"]["created"] if row["process"] else None,
                    "member_count": len(row["members"]),
                    "recovery_barrier": bool(row["recovery_barrier"]),
                    "cleanup_outcome": row["receipt"]["outcome"] if row["receipt"] else None,
                }
                for row in self.durable_cache.values()
            ]
            active = [row for row in durable if row["state"] not in {"released", "terminated", "failed"}]
            return {
                "scope": "This supervisor's cached private/attached claims; exact identities remain in the durable ledger; no PID/name cleanup",
                "accepting": self.accepting,
                "active_count": len(active),
                "owned_tree_count": sum(row["ownership"] == "private" for row in active),
                "attached_count": sum(row["ownership"] == "attached" for row in active),
                "active": [dict(record) for record in active],
                "durable_recovery": "shared_0.20_ledger" if self.owner else "available_not_initialized",
                "durable_resources": durable,
                "close_warning": self.close_warning,
                "attached_native_policy": "GetActiveObject only; release COM references, never Quit/Close/save",
                "shared_native_policy": "No app-launched shared native instance is supported; no ownership transfer",
            }

    def close(self):
        with self.guard:
            self.accepting = False
        with self.launch_guard:
            for launch in list(self.launches.values()):
                try:
                    launch.close()
                except Exception:
                    self.close_warning = (
                        "Resource cleanup requires inspection; original ledger receipt retained"
                    )
            if self.owner is not None:
                try:
                    self.owner.close()
                except Exception:
                    self.close_warning = (
                        "Resource owner has unresolved recovery; no write replay or foreign cleanup"
                    )
        return self.snapshot()


class TrackedLaunch:
    def __init__(self, resources, launch):
        self.resources, self.launch = resources, launch
        self.group = launch.group
        self.pid = launch.pid

    def refresh(self):
        return self.resources._observe(self.launch.refresh())

    def close(self):
        with self.resources.launch_guard:
            try:
                result = self.launch.close()
                if result["outcome"] == "uncertain":
                    raise RuntimeError("Owned-tree cleanup is uncertain; preserve its original receipt")
                return result
            finally:
                # Safe private workers have no dirty native documents. Even a
                # journal/cleanup error cannot detach their kernel containment.
                self.group.close()
                self.resources.launches.pop(self.launch.resource_id, None)
                self.resources._observe(self.launch.owner.ledger.get(self.launch.resource_id))


owned_resources = OwnedResources()
