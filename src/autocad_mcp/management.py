"""Cached, read-only tray reporting for owning processes; no native restart effects."""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import threading
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path

from universal_tools import __version__ as framework_version
from universal_tools.management import ComponentVersion, ManagedService, ManagedStatus, RestartResult
from universal_tools.manager_inventory import CodexInventory, newer_numeric_version, parse_inventory

from . import __display_version__, __version__
from .owned_process import run_owned
from .owned_resources import owned_resources

PLUGIN_ID = "autocad@autocad-local"
RESTART_REASON = (
    "No surviving app supervisor or cross-chat quiescence fence; "
    "leases, queued work and unresolved drawing effects require operator reconciliation"
)


class OwnedCodexInventory(CodexInventory):
    """Fixed metadata probes are owned trees, including the official npm Node shim."""

    def __init__(self, *, command=None, interval=60):
        super().__init__(
            command=command or shutil.which("codex.exe") or shutil.which("codex"), interval=interval
        )

    def argv(self):
        command = self.command
        if not command:
            raise ValueError("Codex CLI is unavailable")
        executable = Path(command).resolve(strict=True)
        if os.name != "nt" or executable.suffix.lower() == ".exe":
            return [str(executable), "plugin", "list", "--json"]
        script = executable.parent / "node_modules/@openai/codex/bin/codex.js"
        adjacent = executable.parent / "node.exe"
        node = str(adjacent) if adjacent.is_file() else shutil.which("node.exe")
        if executable.name.lower() not in {"codex.cmd", "codex.bat"} or not script.is_file() or not node:
            raise ValueError("No supported owned Codex metadata launcher")
        return [
            str(Path(node).resolve(strict=True)),
            str(script.resolve(strict=True)),
            "plugin",
            "list",
            "--json",
        ]

    def refresh(self, *, force=False):
        now = time.monotonic()
        if not force and self.checked_at and now - self.checked_at < self.interval:
            return self.rows, self.error
        self.checked_at = now
        try:
            result = run_owned(
                self.argv(),
                timeout=15,
                check=True,
                resource_kind="codex-inventory",
                capture_limit=2 * 1024 * 1024,
            )
            if getattr(result, "stdout_truncated", False):
                raise ValueError("Codex inventory exceeds its private capture budget")
            self.rows = parse_inventory(json.loads(result.stdout))
            self.error = None
        except Exception:
            self.error = "Plugin inventory is unavailable; previously observed versions may be stale"
        return self.rows, self.error


class Activity:
    def __init__(self):
        self.guard = threading.Lock()
        self.pending = 0

    @contextmanager
    def operation(self):
        with self.guard:
            self.pending += 1
        try:
            yield
        finally:
            with self.guard:
                self.pending -= 1

    def status(self):
        with self.guard:
            return {"active": self.pending, "queued": 0, "control_requests": 0}


def installed(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


class Reporting:
    """Only metadata refresh touches disk/CLI; HTTP callbacks read cached data and counters."""

    def __init__(self, activity, *, registry=None, publisher=None, inventory=None, interval=30):
        self.activity = activity
        self.publisher = Path(publisher) if publisher else Path(__file__).resolve().parents[2]
        self.inventory = inventory if inventory is not None else OwnedCodexInventory()
        self.interval = interval
        self.guard = threading.Lock()
        self.versions = {}
        self.metadata_warning = "Version metadata is pending"
        self.running = {"app": __version__, "framework": framework_version, "sdk": installed("mcp")}
        # Only a generated plugin binding can identify the package that launched this process.
        self.plugin_running = os.environ.get("AUTOCAD_MCP_PLUGIN_VERSION") or None
        self.stop = threading.Event()
        self.thread = None
        self.agent = ManagedService(
            "autocad",
            "AutoCAD MCP Server",
            self.status,
            restart=self.deny_restart,
            plugin_id=PLUGIN_ID,
            registry=registry or os.environ.get("AUTOCAD_MCP_MANAGEMENT_REGISTRY"),
        )

    @staticmethod
    def deny_restart(_):
        return RestartResult(outcome="blocked", message=RESTART_REASON)

    def refresh_versions(self):
        versions = {}
        for component, distribution in (
            ("app", "autocad-mcp-server"),
            ("framework", "universal-codex-tools"),
            ("sdk", "mcp"),
        ):
            value = installed(distribution)
            if value:
                versions[component] = ComponentVersion(installed=value, running=self.running[component])
        # Source metadata supplies availability only; no feed/engineering files are searched.
        try:
            value = tomllib.loads((self.publisher / "pyproject.toml").read_text(encoding="utf-8"))
            if value["project"]["name"] == "autocad-mcp-server" and "app" in versions:
                available = value["project"]["version"]
                versions["app"] = ComponentVersion.model_validate(
                    {
                        **versions["app"].model_dump(),
                        "available": available,
                        "update_pending": newer_numeric_version(available, versions["app"].installed),
                    }
                )
        except (OSError, ValueError, KeyError, TypeError):
            pass
        rows, warning = self.inventory.refresh()
        plugin = next((row for row in rows if row["plugin_id"] == PLUGIN_ID), None)
        if plugin:
            available = plugin["available"]
            try:
                value = json.loads((self.publisher / "plugins/autocad/plugin.json").read_bytes())
                available = value["version"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
            versions["plugin"] = ComponentVersion(
                installed=plugin["installed"],
                running=self.plugin_running,
                available=available,
                update_pending=newer_numeric_version(available, plugin["installed"]),
            )
        with self.guard:
            self.versions = versions
            self.metadata_warning = warning or ("Plugin installation is unobserved" if not plugin else "")

    def status(self):
        counts = self.activity()
        active = counts["active"] + counts["queued"] + counts["control_requests"]
        resources = owned_resources.snapshot()
        active = max(active, resources["active_count"])
        with self.guard:
            versions = {key: value.model_copy(deep=True) for key, value in self.versions.items()}
            warning = self.metadata_warning
        return ManagedStatus(
            state="busy" if active else ("degraded" if warning else "running"),
            message=(warning or "Drawing service process; no drawings opened for status")
            + f"; release {__display_version__} (package {__version__})"
            + f"; owned worker trees: {resources['owned_tree_count']}; protected attachments: {resources['attached_count']}",
            active_operations=active,
            versions=versions,
            restart_allowed=False,
            restart_reason=RESTART_REASON,
        )

    def _refresh(self):
        while not self.stop.is_set():
            try:
                self.refresh_versions()
            except Exception:
                # Do not log tokens, paths or third-party exceptions; keep stale data explicit.
                with self.guard:
                    self.metadata_warning = "Version metadata is stale; refresh failed"
            if self.stop.wait(self.interval):
                break

    def __enter__(self):
        try:
            self.agent.start()
            self.thread = threading.Thread(target=self._refresh, name="autocad-versions", daemon=True)
            self.thread.start()
        except BaseException:
            self.stop.set()
            self.agent.close()
            raise
        return self

    def __exit__(self, *_):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=17)
        self.agent.close()
