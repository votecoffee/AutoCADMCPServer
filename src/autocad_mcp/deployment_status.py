"""Actual running generation and bounded selected-installation metadata; no launches."""

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

_guard = threading.Lock()
_running = {}
_selected = {}
_warning = None


def bind_deployment_status(value):
    global _running, _selected
    with _guard:
        _running = {
            key: value[key]
            for key in (
                "home",
                "generation",
                "version",
                "profile",
                "app_wheel_sha256",
                "library_id",
                "bootstrap_id",
            )
        }
        _selected = {
            "generation": value["generation"],
            "version": value["version"],
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }


def refresh_selection():
    global _selected, _warning
    with _guard:
        running = dict(_running)
    if not running:
        return {}
    try:
        home = Path(running["home"])
        pointer = home / "launcher/current.json"
        if (
            pointer.is_symlink()
            or getattr(pointer.lstat(), "st_file_attributes", 0) & 0x400
            or not 0 < pointer.stat().st_size <= 65536
        ):
            raise ValueError("Invalid installed selection")
        value = json.loads(pointer.read_bytes())
        identity = value["generation"]
        if value["schema_version"] != 1 or not re.fullmatch("[0-9a-f]{64}", identity):
            raise ValueError("Invalid installed generation")
        snapshot = home / "launcher/snapshots" / identity
        manifest = snapshot / "manifest.json"
        for current in [*reversed(manifest.parents), manifest]:
            if current.is_symlink() or getattr(current.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError("Linked installed metadata path")
        if pointer.stat().st_nlink != 1 or manifest.stat().st_nlink != 1:
            raise ValueError("Hard-linked installed metadata")
        if snapshot.is_symlink() or getattr(snapshot.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("Invalid installed snapshot")
        if (
            manifest.is_symlink()
            or getattr(manifest.lstat(), "st_file_attributes", 0) & 0x400
            or not 0 < manifest.stat().st_size <= 4_000_000
        ):
            raise ValueError("Invalid installed manifest")
        raw = manifest.read_bytes()
        metadata = json.loads(raw)
        if (
            hashlib.sha256(raw).hexdigest() != identity
            or metadata["app_id"] != "autocad"
            or metadata["profile"] != "offline"
        ):
            raise ValueError("Installed metadata differs")
        selected = {
            "generation": identity,
            "version": metadata["version"],
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        with _guard:
            _selected, _warning = selected, None
        return selected
    except (OSError, ValueError, KeyError, TypeError):
        with _guard:
            _warning = "Installed selection is unavailable; running generation retained"
        return {}


def snapshot():
    with _guard:
        return {
            "kind": "app_owned_stable" if _running else "direct_unbound",
            "running": dict(_running),
            "selected_observation": dict(_selected),
            "selection_warning": _warning,
            "selection_is_runtime_health": False,
        }
