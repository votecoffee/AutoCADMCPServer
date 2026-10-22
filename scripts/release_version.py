"""Check release identities, or explicitly set one already-chosen New York timestamp."""

import argparse
import json
import re
import runpy
import tomllib
from pathlib import Path

PLUGIN_MANIFESTS = ("plugins/autocad/plugin.json", "plugins/autocad/.codex-plugin/plugin.json")


def release(repo: Path) -> dict:
    values = runpy.run_path(str(repo / "src/autocad_mcp/version.py"))
    return {
        "version": values["PACKAGE_VERSION"],
        "display_version": values["DISPLAY_VERSION"],
        "version_timezone": values["VERSION_TIMEZONE"],
    }


def check(repo: Path) -> dict:
    identity = release(repo)
    metadata = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    versions = {"pyproject.toml": metadata["project"]["version"]}
    versions.update({name: json.loads((repo / name).read_bytes())["version"] for name in PLUGIN_MANIFESTS})
    if any(value != identity["version"] for value in versions.values()):
        raise ValueError(f"Release identity mismatch: {versions}")
    return identity


def stamp(repo: Path, display: str) -> dict:
    values = runpy.run_path(str(repo / "src/autocad_mcp/version.py"))
    if display != values["display_timestamp_version"](display):
        raise ValueError("Supply the padded display timestamp YY.MMDD.HHmmss")
    canonical = values["canonical_timestamp_version"](display)
    version_path = repo / "src/autocad_mcp/version.py"
    source = version_path.read_text(encoding="utf-8")
    source, count = re.subn(r'(?m)^DISPLAY_VERSION = "[^"]+"$', f'DISPLAY_VERSION = "{display}"', source)
    if count != 1:
        raise ValueError("Expected exactly one fixed display version")
    project_path = repo / "pyproject.toml"
    project, count = re.subn(
        r'(?m)^version = "[^"]+"$',
        f'version = "{canonical}"',
        project_path.read_text(encoding="utf-8"),
    )
    if count != 1:
        raise ValueError("Expected exactly one project version")
    manifests = {name: json.loads((repo / name).read_bytes()) for name in PLUGIN_MANIFESTS}
    version_path.write_text(source, encoding="utf-8", newline="\n")
    project_path.write_text(project, encoding="utf-8", newline="\n")
    for name, manifest in manifests.items():
        manifest["version"] = canonical
        (repo / name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return check(repo)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--set", metavar="YY.MMDD.HHmmss", help="Explicit fixed release stamp; never reads a clock"
    )
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    print(json.dumps(stamp(repo, args.set) if args.set else check(repo)))


if __name__ == "__main__":
    main()
