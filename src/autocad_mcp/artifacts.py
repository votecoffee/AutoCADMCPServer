"""Hash-pinned, bounded views of completed preview/export receipts; no arbitrary paths."""

import asyncio
import base64
import json
import threading
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from mcp.server.extension import Extension

from .config import inside
from .service import sha256
from .transactions import Transactions


class Artifacts:
    identifier = "autocad.artifacts"

    def __init__(self, service):
        self.service = service
        self.receipts = Transactions(service.config.state, service.coordinator)
        self.listeners = set()
        self.guard = threading.Lock()
        self.known = {}
        self.generation = 0

    @property
    def revision(self):
        import hashlib

        with self.guard:
            return hashlib.sha256(json.dumps(self.known, sort_keys=True).encode()).hexdigest()

    def _resolve(self, request_id):
        receipt = self.receipts.get(request_id, include_result=True)
        if receipt["state"] != "succeeded" or receipt["operation"] not in {
            "cad_render_preview",
            "cad_export_electrical_project",
        }:
            raise ValueError("Artifact requires a completed preview/export receipt")
        result = receipt["result"]
        path = Path(result.get("preview_path") or result.get("path", "")).resolve(strict=True)
        allowed = self.service.config.state / (
            "previews" if receipt["operation"] == "cad_render_preview" else "electrical/exports"
        )
        if not inside(path, allowed) or path.is_symlink():
            raise ValueError("Artifact escaped the selected app state")
        scope = result.get("authorization", {})
        root = self.service.config.roots.get(scope.get("root_id"))
        if root is None or str(root) != scope.get("root_path"):
            raise ValueError(
                "Artifact has no matching current root authorization; regenerate legacy artifacts"
            )
        return path, result

    def describe(self, request_id, expected_sha256, offset=0, length=65536):
        if offset < 0 or not 1 <= length <= 65536:
            raise ValueError("Artifact chunks require nonnegative offset and 1..65536 bytes")
        path, result = self._resolve(request_id)
        actual = sha256(path)
        if actual != expected_sha256:
            raise ValueError("Stale artifact SHA-256")
        size = path.stat().st_size
        if offset > size:
            raise ValueError("Artifact offset exceeds its size")
        uri = f"artifact://autocad/{quote(request_id, safe='')}/{actual}/{offset}/{length}/" + path.name
        # Stable receipt scope and content hash authorize every later resource read.
        with path.open("rb") as stream:
            stream.seek(offset)
            raw = stream.read(length)
        if sha256(path) != actual:
            raise ValueError("Artifact changed during bounded read")
        entry = {
            "uri": uri,
            "request_id": request_id,
            "sha256": actual,
            "offset": offset,
            "length": len(raw),
            "size_bytes": size,
            "next_offset": offset + len(raw) if offset + len(raw) < size else None,
            "source": result.get("source"),
            "freshness": result.get(
                "freshness",
                "Source hashes describe the captured rendering; refetch current source evidence separately",
            ),
            "base64": base64.b64encode(raw).decode(),
        }
        with self.guard:
            if uri not in self.known:
                self.generation += 1
            if len(self.known) >= 64:
                self.known.clear()
            self.known[uri] = {
                "uri": uri,
                "name": path.name,
                "mimeType": "image/png" if path.suffix == ".png" else "application/json",
            }
        return entry

    def claims_uri(self, uri):
        return uri.startswith("artifact://autocad/")

    def resource_metadata(self):
        with self.guard:
            return list(self.known.values())

    async def read_bytes(self, uri):
        parts = urlsplit(uri)
        fields = parts.path.strip("/").split("/")
        if (
            parts.scheme != "artifact"
            or parts.netloc != "autocad"
            or len(fields) != 5
            or parts.query
            or parts.fragment
        ):
            raise ValueError("Invalid artifact reference")
        request, digest, offset, length, filename = fields
        value = await asyncio.to_thread(self.describe, unquote(request), digest, int(offset), int(length))
        if value["uri"] != uri:
            raise ValueError("Artifact reference identity changed")
        return base64.b64decode(value["base64"])

    async def changed(self):
        for listener in tuple(self.listeners):
            try:
                await asyncio.wait_for(listener(), timeout=0.5)
            except Exception:
                pass


class GuidanceResources(Extension):
    """One framework skill provider plus app-scoped artifacts; no generic federation."""

    def __init__(self, catalog, artifacts):
        self.catalog, self.artifacts = catalog, artifacts
        self.listeners = catalog.listeners
        artifacts.listeners = self.listeners
        self.identifier = catalog.identifier

    @property
    def generation(self):
        return self.catalog.generation + self.artifacts.generation

    @property
    def revision(self):
        import hashlib

        return hashlib.sha256((self.catalog.revision + self.artifacts.revision).encode()).hexdigest()

    def settings(self):
        return self.catalog.settings()

    def methods(self):
        return self.catalog.methods()

    def resources(self):
        return self.catalog.resources()

    def claims_uri(self, uri):
        return self.catalog.claims_uri(uri) or self.artifacts.claims_uri(uri)

    def resource_metadata(self):
        return self.catalog.resource_metadata() + self.artifacts.resource_metadata()

    async def read_bytes(self, uri):
        return await (
            self.catalog.read_bytes(uri) if self.catalog.claims_uri(uri) else self.artifacts.read_bytes(uri)
        )
