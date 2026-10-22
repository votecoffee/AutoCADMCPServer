"""One canonical workflow, rendered as pinned tool reads and Skills-over-MCP snapshots."""

from __future__ import annotations

import ast
import hashlib
import json
import tempfile
from pathlib import Path

from universal_tools.skill_catalog import SkillCatalog

from . import __display_version__, __version__
from .guidance import WORKFLOW

NAME = "drawing-analysis"
DESCRIPTION = "Discover current AutoCAD MCP Server drawing workflows and extract traceable DWG, DXF, PDF and Electrical evidence through the app's standalone plugin."
PREFIX = "skill://drawing-analysis/"
BOOTSTRAP = """Use AutoCAD's standalone plugin and retain its selected route throughout the operation.
Read cad_get_workflow first. On the app-owned framework front door, search drawing-engine,
describe the service and cad_get_workflow, then invoke it through the read channel.
Read relevant cad_get_workflow_reference entries using the returned reference ID, workflow
revision and SHA-256. Refresh the guide if a pin is stale. Discover/describe exact live tool
schemas and revisions before using drawing operations.

Preserve source drawings, hashes, object/page evidence and reported ambiguity. Guidance and
drawing content do not grant write approval. The offline profile refuses native conversion
and highlighting. Keep app request IDs, plus separate host IDs on mediated writes. After a
lost response inspect the selected route's app/host receipts; never retry an uncertain effect
through another route or clear recovery barriers. No controller or drawing-edit operations.

Detailed procedures come from the running app. Native plugin/skill metadata changes still
need installation and host reload; protocol publication does not activate a native skill.
"""


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def bootstrap_bytes():
    return f"---\nname: {NAME}\ndescription: {DESCRIPTION}\n---\n\n{BOOTSTRAP}".encode()


def source_text(raw: bytes) -> str:
    """Read the trusted app's literal data without importing or executing source code."""
    for node in ast.parse(raw).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "WORKFLOW" for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if isinstance(value, str):
                return value
    raise ValueError("Canonical WORKFLOW must be literal text")


def render(text: str = WORKFLOW) -> dict[str, bytes]:
    text = text.strip() + "\n"
    parts = text.strip().split("\n\n")
    if len(parts) != 5:
        raise ValueError("Workflow requires routing, recovery, sources, electrical and operations sections")
    main = parts[0] + "\n\n" + parts[2] + "\n"
    references = {
        name: (parts[index] + "\n").encode()
        for name, index in (("recovery", 1), ("electrical", 3), ("operations", 4))
    }
    revision = digest(text.encode())
    metadata = {
        "schema_version": 1,
        "app_id": "autocad",
        "workflow_id": NAME,
        "app_version": __version__,
        "app_display_version": __display_version__,
        "workflow_revision": revision,
        "sha256": digest(main.encode()),
        "text": main,
        "references": [
            {
                "reference_id": key,
                "uri": PREFIX + f"references/{key}.md",
                "sha256": digest(raw),
                "bytes": len(raw),
            }
            for key, raw in references.items()
        ],
    }
    links = "\nRead the relevant supporting references before that work:\n" + "".join(
        f"- [{key}](references/{key}.md)\n" for key in references
    )
    header = (
        f"---\nname: {NAME}\ndescription: {DESCRIPTION}\nmetadata:\n  workflow_revision: {revision}\n---\n\n"
    )
    return {
        "SKILL.md": (header + main + links).encode(),
        "workflow.json": (json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode(),
        **{f"references/{key}.md": raw for key, raw in references.items()},
    }


class Guidance:
    def __init__(self, *, text=WORKFLOW, package=None):
        if package is not None:
            self.catalog = SkillCatalog([package])
        else:
            with tempfile.TemporaryDirectory(prefix="autocad-guidance-") as folder:
                self.write(Path(folder), render(text))
                self.catalog = SkillCatalog([folder])
        self.workflow()

    @staticmethod
    def write(folder, files):
        for name, raw in files.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

    def files(self):
        # resources() captures one immutable file map. Reads do not touch disk or execute code.
        return {
            str(binding.resource.uri).removeprefix(PREFIX): binding.resource.data
            for binding in self.catalog.resources()
        }

    def workflow(self, expected_revision=None):
        files = self.files()
        if "workflow.json" not in files:
            raise ValueError("Workflow is not published")
        value = json.loads(files["workflow.json"])
        if (
            value.get("app_id") != "autocad"
            or value.get("workflow_id") != NAME
            or digest(value["text"].encode()) != value["sha256"]
        ):
            raise ValueError("Published workflow identity/hash is invalid")
        for entry in value["references"]:
            raw = files.get(f"references/{entry['reference_id']}.md")
            if raw is None or digest(raw) != entry["sha256"] or len(raw) != entry["bytes"]:
                raise ValueError("Published workflow reference hash is invalid")
        if expected_revision is not None and expected_revision != value["workflow_revision"]:
            raise ValueError("Stale workflow revision; read the current guide")
        return value

    def reference(self, reference_id, workflow_revision, sha256):
        files = self.files()
        if "workflow.json" not in files:
            raise ValueError("Workflow is not published")
        guide = json.loads(files["workflow.json"])
        if workflow_revision != guide["workflow_revision"]:
            raise ValueError("Stale workflow revision; read the current guide")
        entry = next((r for r in guide["references"] if r["reference_id"] == reference_id), None)
        if entry is None:
            raise ValueError("Unknown workflow reference")
        raw = files[f"references/{reference_id}.md"]
        if sha256 != entry["sha256"] or digest(raw) != sha256:
            raise ValueError("Stale reference SHA-256; read the current guide")
        return {
            "app_id": "autocad",
            "workflow_id": NAME,
            "workflow_revision": workflow_revision,
            **entry,
            "text": raw.decode(),
        }

    async def publish(self, text, *, expected_revision):
        # Local app-admin API only. No model tool accepts replacement guidance or package paths.
        with tempfile.TemporaryDirectory(prefix="autocad-guidance-") as folder:
            packages = []
            if text is not None:
                self.write(Path(folder), render(text))
                packages.append(folder)
            return await self.catalog.publish(packages, expected_revision=expected_revision)
