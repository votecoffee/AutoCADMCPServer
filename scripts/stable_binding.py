"""Create an exact, read-only host-settings proposal for a serialized publisher."""

import hashlib
import json
import tomllib
from pathlib import Path

try:
    from scripts.stable_entry import canonical_json, selection
    from scripts.stable_install import binding, sha256
except ModuleNotFoundError:
    from stable_entry import canonical_json, selection
    from stable_install import binding, sha256


def propose(home, settings, output, *, evidence=None):
    home, settings, output = Path(home).absolute(), Path(settings).absolute(), Path(output).absolute()
    root = Path(__file__).resolve().parents[1]
    if home.is_relative_to(root) or output == settings or settings.is_relative_to(output):
        raise ValueError(
            "Published entry must be outside the checkout; proposal must not target shared settings"
        )
    pointer = selection(home)
    generation = pointer["generation"]
    selected = home / "launcher/snapshots" / generation / "manifest.json"
    if sha256(selected) != generation:
        raise ValueError("Selected launcher metadata differs")
    existed = settings.exists()
    raw = settings.read_bytes() if existed else b""
    if b"\r" in raw.replace(b"\r\n", b""):
        raise ValueError("Malformed shared TOML must be preserved, never silently repaired")
    parsed = tomllib.loads(raw.decode("utf-8-sig"))
    expected = parsed.get("mcp_servers", {}).get("autocad")
    if expected is not None and not isinstance(expected, dict):
        raise ValueError("Unexpected current AutoCAD route")
    desired = {**(expected or {}), "enabled": True, **binding(home)}
    output.mkdir(parents=True, exist_ok=False)
    backup = output / "expected-config.toml"
    backup.write_bytes(raw)
    proposal = {
        "schema_version": 1,
        "app_id": "autocad",
        "shared_settings": str(settings),
        "expected_config_exists": settings.exists(),
        "expected_config_sha256": hashlib.sha256(raw).hexdigest(),
        "exact_backup": str(backup),
        "expected_route": expected,
        "expected_route_sha256": hashlib.sha256(canonical_json(expected)).hexdigest(),
        "proposed_route": desired,
        "expected_plugin_settings": parsed.get("plugins", {}).get("autocad@autocad-local"),
        "plugin_policy": "Retain the standalone plugin and skill. Retain the existing disabled duplicate packaged route; do not edit immutable caches.",
        "selected_home": str(home),
        "selected_generation": generation,
        "selection_sha256": sha256(home / "launcher/current.json"),
        "configuration_written": False,
        "evidence": evidence or {},
        "publication_contract": "Serialized publisher must compare current config bytes/hash and selected generation, preserve BOM/comments/newlines/unrelated settings, atomically write binary TOML bytes and validate readback. Never restore the stale global backup.",
    }
    (output / "binding-proposal.json").write_bytes((json.dumps(proposal, indent=2) + "\n").encode())
    if settings.exists() != existed or (existed and settings.read_bytes() != raw):
        raise ValueError(
            "Shared configuration changed while preparing the proposal; retain this stale proposal, prepare a fresh one"
        )
    return proposal
