from __future__ import annotations

import inspect
import json
import logging
from functools import partial, wraps
from typing import Any, get_type_hints

import anyio
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from universal_tools.extensions import ExtensionServer as MCPServer

from . import __version__
from .artifacts import Artifacts
from .batch_jobs import BatchJobs
from .coordination import RequestScheduler
from .service import DrawingService
from .tool_types import ArtifactLength, IndexLimit, Limit, Offset, Page, TextLength, Width
from .transactions import Transactions
from .workflow_guidance import BOOTSTRAP, Guidance


class DrawingServer(MCPServer):
    """Private, short-lived modern discovery hints; legacy clients retain explicit refresh."""

    async def _handle_list_tools(self, ctx, params):
        self.discovery_round_trips["tools"] += 1
        result = await super()._handle_list_tools(ctx, params)
        return (
            result.model_copy(update={"ttl_ms": 2000, "cache_scope": "private"})
            if ctx.protocol_version == "2026-07-28"
            else result
        )

    async def _handle_list_resources(self, ctx, params):
        self.discovery_round_trips["resources"] += 1
        result = await super()._handle_list_resources(ctx, params)
        return (
            result.model_copy(update={"ttl_ms": 2000, "cache_scope": "private"})
            if ctx.protocol_version == "2026-07-28"
            else result
        )


def create_server(
    service: DrawingService, port: int = 8796, *, workflow: bool = False, scheduler=None, guidance=None
) -> MCPServer:
    scheduler = scheduler or RequestScheduler(
        service.config.max_concurrent_requests, service.config.max_queued_requests
    )
    transactions = Transactions(service.config.state, service.coordinator)
    guidance = guidance or Guidance()
    artifacts = Artifacts(service)
    jobs = BatchJobs(service)
    service.batch_jobs = jobs
    mcp = DrawingServer(
        "AutoCAD MCP Server",
        instructions=BOOTSTRAP,
        extensions=[guidance.catalog],
        resource_providers=[guidance.catalog, artifacts],
        version=__version__,
    )
    mcp.discovery_round_trips = {"tools": 0, "resources": 0}

    def tool(*, read=True, control=False):
        def decorate(fn):
            fn.__annotations__ = {**get_type_hints(fn, include_extras=True), "return": dict[str, Any]}
            original_signature = inspect.signature(fn)

            @wraps(fn)
            async def wrapped(*args, **kwargs):
                request_id = kwargs.pop("request_id", None) if not read else None
                bound = original_signature.bind(*args, **kwargs)
                bound.apply_defaults()

                def execute():
                    return fn(*args, **kwargs)

                try:
                    if read:
                        result = await scheduler.run(execute, control=control)
                    else:
                        result = await scheduler.run(
                            transactions.execute,
                            request_id,
                            fn.__name__,
                            {key: value for key, value in bound.arguments.items() if key != "ctx"},
                            execute,
                            control=control,
                        )
                except FileNotFoundError:
                    raise ToolError(
                        "Requested source or app artifact is unavailable; refresh its inventory or receipt"
                    ) from None
                except ValueError as error:
                    message = str(error)
                    if (
                        "\n" in message
                        or "\r" in message
                        or any(
                            text in message
                            for text in ("worker failed:", "Preview failed:", "Extraction worker failed:")
                        )
                    ):
                        logging.getLogger("autocad_mcp").error(
                            "Drawing processing diagnostic: %s", message[:8192]
                        )
                        message = "Drawing processing failed; retained app receipts and private diagnostics require inspection"
                    raise ToolError(message[:500]) from None
                if fn.__name__ == "cad_get_artifact":
                    await artifacts.changed()
                if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 200_000:
                    raise ToolError("Response exceeds budget; use smaller limit or narrower filters")
                return result

            if not read:
                wrapped.__signature__ = original_signature.replace(
                    parameters=[
                        *original_signature.parameters.values(),
                        inspect.Parameter(
                            "request_id", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=str | None
                        ),
                    ]
                )
                wrapped.__annotations__ = {**fn.__annotations__, "request_id": str | None}
                wrapped.__doc__ = (
                    (fn.__doc__ or "")
                    + "\nOptional request_id provides durable idempotency; inspect cad_get_transaction after a lost response."
                )

            return mcp.tool(
                structured_output=True,
                annotations=ToolAnnotations.model_validate(
                    {
                        "readOnlyHint": read,
                        "destructiveHint": False,
                        "idempotentHint": read,
                        "openWorldHint": False,
                    }
                ),
            )(wrapped)

        return decorate

    @tool(control=True)
    def cad_get_workflow(expected_revision: str | None = None) -> dict:
        """Read current drawing workflow and the revision/hash-pinned reference catalog."""
        return guidance.workflow(expected_revision)

    @tool(control=True)
    def cad_get_workflow_reference(reference_id: str, workflow_revision: str, sha256: str) -> dict:
        """Read a named supporting reference using its exact current guide revision and SHA-256."""
        return guidance.reference(reference_id, workflow_revision, sha256)

    @tool(control=True)
    def cad_capabilities() -> dict:
        """Read feature/doctor status, selected profile, implementation evidence and concrete blockers."""
        from .capabilities import report

        return {**report(workflow, service.config), "discovery_round_trips": dict(mcp.discovery_round_trips)}

    @tool(read=False)
    def cad_start_index_job(root_id: str, offset: Offset = 0, limit: IndexLimit = 5) -> dict:
        """Start one durable-intent index batch on a long-lived direct owner. Keep its capability private."""
        if workflow:
            raise ValueError(
                "Start index jobs on an explicitly selected long-lived direct service; backend worker survival is unassessed"
            )
        return jobs.start(root_id, offset, limit)

    @tool(control=True)
    def cad_get_index_job(job_id: str, access_token: str, ctx: Context) -> dict:
        """Read authorized batch status/progress. An abandoned owner is unknown, never restarted."""
        value = jobs.get(job_id, access_token)
        anyio.from_thread.run(
            partial(ctx.report_progress, value["completed"], value["total"] or None, value["stage"])
        )
        return value

    @tool(read=False, control=True)
    def cad_cancel_index_job(job_id: str, access_token: str) -> dict:
        """Request a cooperative stop between files. Acknowledgment does not prove native stop or rollback."""
        return jobs.cancel(job_id, access_token)

    @tool()
    def cad_get_artifact(
        request_id: str, sha256: str, offset: Offset = 0, length: ArtifactLength = 65536
    ) -> dict:
        """Read a hash-pinned preview/export chunk from its completed app receipt; URI and base64 fallback."""
        return artifacts.describe(request_id, sha256, offset, length)

    @tool(control=True)
    def cad_status() -> dict:
        """List configured source roots, installed backends, supported formats and extraction limits."""
        return service.status()

    @tool(control=True)
    def cad_concurrency_status() -> dict:
        """Inspect per-process request admission, queue and worker limits; control calls remain responsive under load."""
        return {
            **scheduler.status(),
            "shared_worker_process_limit": service.config.max_worker_processes,
            "shared_oda_process_limit": service.config.max_oda_processes,
            "autocad_ui": "serialized across processes",
        }

    @tool(control=True)
    def cad_get_transaction(request_id: str, include_result: bool = False) -> dict:
        """Read a durable write receipt/result. An abandoned owner is reported unknown; no operation is retried."""
        return transactions.get(request_id, include_result)

    @tool()
    def cad_list_files(
        root_id: str, supported_only: bool = True, offset: Offset = 0, limit: Limit = 100
    ) -> dict:
        """Inventory a configured drawing root recursively. Unsupported CAD formats can be listed too."""
        return service.inventory(root_id, supported_only, offset, limit)

    @tool()
    def cad_inspect(root_id: str, relative_path: str) -> dict:
        """Extract source SHA-256, metadata, units, entity counts, layouts, PDF page count and limitations."""
        return service.inspect(root_id, relative_path)

    @tool()
    def cad_get_entities(
        root_id: str,
        relative_path: str,
        layout: str | None = None,
        layer: str | None = None,
        entity_type: str | None = None,
        handle: str | None = None,
        block: str | None = None,
        offset: Offset = 0,
        limit: Limit = 50,
    ) -> dict:
        """Read CAD entities and geometry properties by layer/layout/type/handle. Block coordinates are local.

        INSERT entities include transforms and attached attributes. Use layout '@block' and block name for
        definitions. Polyline vertices are limited to 256 per record; cad_entity_vertices retrieves slices.
        """
        return service.records(
            root_id,
            relative_path,
            "entities",
            offset,
            limit,
            layout=layout,
            layer=layer,
            entity_type=entity_type,
            handle=handle,
            block=block,
        )

    @tool()
    def cad_get_text(
        root_id: str,
        relative_path: str,
        query: str | None = None,
        layout: str | None = None,
        layer: str | None = None,
        page: Page | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> dict:
        """Read/search literal CAD text, block attributes or positioned PDF text. PDF pages are one-based.

        Every row has a record_index plus CAD handle/location or PDF page/bbox. Long text is explicitly
        truncated at 8000 characters; cad_read_text_record retrieves full text in slices.
        """
        return service.records(
            root_id, relative_path, "text", offset, limit, query=query, layout=layout, layer=layer, page=page
        )

    @tool()
    def cad_read_text_record(
        root_id: str, relative_path: str, record_index: Offset, start: Offset = 0, length: TextLength = 8000
    ) -> dict:
        """Read a slice of one text record, using its zero-based record_index. Maximum length is 16000."""
        return service.text_slice(root_id, relative_path, record_index, start, length)

    @tool()
    def cad_entity_vertices(
        root_id: str, relative_path: str, handle: str, offset: Offset = 0, limit: Limit = 100
    ) -> dict:
        """Read LWPOLYLINE vertex slices [x,y,start_width,end_width,bulge] using a CAD entity handle."""
        doc = service.load(root_id, relative_path)
        row = next((row for row in doc["entities"] if row["handle"] == handle), None)
        if row is None or "vertices" not in row:
            raise ValueError("Handle is not an extracted LWPOLYLINE")
        from .service import paginate

        return {
            "source": doc["source"],
            "handle": handle,
            "closed": row["closed"],
            **paginate(row["vertices"], offset, limit),
        }

    @tool()
    def cad_get_layers(root_id: str, relative_path: str, offset: Offset = 0, limit: Limit = 100) -> dict:
        """Read CAD layer names, colors, linetypes and off/frozen/locked flags."""
        return service.records(root_id, relative_path, "layers", offset, limit)

    @tool()
    def cad_get_blocks(root_id: str, relative_path: str, offset: Offset = 0, limit: Limit = 100) -> dict:
        """Read block definitions, base points and xref paths. Read INSERT entities for attributes/placements."""
        return service.records(root_id, relative_path, "blocks", offset, limit)

    @tool()
    def cad_get_dimensions(
        root_id: str, relative_path: str, layout: str | None = None, offset: Offset = 0, limit: Limit = 100
    ) -> dict:
        """Read dimension entities, raw measurement, type, text override and definition points.

        Values are not formatted dimension labels; dimension style rounding/scaling is not applied.
        """
        return service.records(
            root_id, relative_path, "entities", offset, limit, entity_type="DIMENSION", layout=layout
        )

    @tool()
    def cad_get_references(root_id: str, relative_path: str, offset: Offset = 0, limit: Limit = 100) -> dict:
        """List declared xrefs, image and PDF/DWF/DGN underlay paths; never open or load references."""
        return service.records(root_id, relative_path, "references", offset, limit)

    @tool()
    def cad_get_pdf_pages(root_id: str, relative_path: str, offset: Offset = 0, limit: Limit = 100) -> dict:
        """Read PDF page sizes, rotation, text counts, image counts and image-only OCR candidates."""
        return service.records(root_id, relative_path, "pages", offset, limit)

    @tool()
    def cad_get_pdf_tables(
        root_id: str, relative_path: str, page: Page, offset: Offset = 0, limit: Limit = 20
    ) -> dict:
        """Detect and extract PDF table cells on one one-based page; verify against cad_render_preview."""
        return service.pdf_tables(root_id, relative_path, page, offset, limit)

    @tool(read=False)
    def cad_index_project(root_id: str, ctx: Context, offset: Offset = 0, limit: IndexLimit = 2) -> dict:
        """Index 1..5 files into app-owned search state. Continue next_offset until null; inspect failures.

        This writes only the server's cache/index and preserves all source files.
        """

        def progress(completed, total, stage):
            try:
                anyio.from_thread.run(partial(ctx.report_progress, completed, total, stage))
            except Exception:
                pass  # A lost progress recipient does not cancel or roll back committed indexing.

        return service.index(root_id, offset, limit, progress=progress)

    @tool()
    def cad_search_project(root_id: str, query: str, offset: Offset = 0, limit: Limit = 50) -> dict:
        """Search indexed drawing text/attributes literally across one root with exact provenance.

        Stale or deleted files are excluded. Coverage reports missing/stale sources; index first.
        """
        return service.search(root_id, query, offset, limit)

    @tool()
    def cad_compare_drawings(
        root_id: str,
        relative_path: str,
        other_root_id: str,
        other_relative_path: str,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> dict:
        """Compare text multiplicities and layer/block names across two files; structural content diff only."""
        return service.compare(root_id, relative_path, other_root_id, other_relative_path, offset, limit)

    @tool(read=False)
    def cad_render_preview(
        root_id: str, relative_path: str, page: Page = 1, layout: str = "Model", width: Width = 1600
    ) -> dict:
        """Write a PNG preview in app-owned state. PDF page is one-based; CAD uses an exact layout name.

        Width is limited to 3000 pixels. CAD rendering is approximate and may omit unsupported entities.
        """
        return service.render(root_id, relative_path, page, layout, width)

    from .electrical_server import register

    register(tool, service)
    return mcp
