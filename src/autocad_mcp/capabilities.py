"""Implementation profile, including precise opt-in and acceptance boundaries."""

from . import __display_version__, __version__
from .version import VERSION_TIMEZONE


def report(backend=False):
    return {
        "app_id": "autocad",
        "version": __version__,
        "display_version": __display_version__,
        "version_timezone": VERSION_TIMEZONE,
        "execution_profile": "offline",
        "numerical_threads_per_process": 1,
        "native_operations_available": False,
        "available_formats": [".dxf", ".pdf"],
        "blocked_formats": [".dwg", ".dwt", ".dws"],
        "framework": "0.20.0",
        "sdk": "2.3.0",
        "selected_surface": "drawing-engine backend" if backend else "direct native server",
        "features": {
            "process_lifetimes": {
                "state": "implemented",
                "evidence": "Harmless Windows timeout, owner-death, nested-helper, protected-attachment and EOF-fence fixtures passed",
                "boundary": "Native MCP server, Codex activation and AutoCAD cleanup acceptance remain unassessed; no restart supervisor or native rollback claim.",
            },
            "durable_resource_recovery": {
                "state": "implemented",
                "evidence": "Shared 0.20 ResourceLedger/ResourceOwner; durable binding before resume, exact creation identities, cleanup receipts and reviewed harmless orphan recovery",
                "boundary": "No automatic cleanup/retry, shared native launch, live-registration migration or installed-manager acceptance. Native attachments stay report-only.",
            },
            "framework_stdio_ownership": {
                "state": "blocked",
                "reason": "SDK backend stdio creation has no integrated app-owned launch/containment hook. Experimental host/proxy CLI startup is disabled; the background launcher is not an MCP stdio transport.",
            },
            "workflow_readers": {
                "state": "enabled",
                "evidence": "revision/hash-pinned canonical guide and references",
            },
            "skills": {
                "state": "enabled",
                "evidence": "generated SkillCatalog, list/get/resource hashes and connected publication tests; no native host activation claim",
            },
            "resource_notifications": {
                "state": "enabled",
                "boundary": "Catalog hints only; reconnect and refetch manifests/resources",
            },
            "discovery_cache": {
                "state": "opt_in" if backend else "enabled",
                "boundary": "Native modern listings carry two-second private hints; legacy clients get none. Default transient legacy backend has no watching/cache. Separate retained-modern publication requires dedicated host state. Catalog events invalidate discovery; no hints means no caching.",
            },
            "index_progress": {
                "state": "enabled",
                "boundary": "Monotonic files-examined units; batch-job structured status remains available without notifications",
            },
            "index_jobs": {
                "state": "blocked" if backend else "enabled",
                "boundary": "Start requires an owning long-lived direct service. Access capability is not a verified principal. Persisted intent, cancel between files, inspect owner loss; no automatic replay.",
            },
            "cancellation": {
                "state": "blocked" if backend else "enabled",
                "boundary": "Explicit job cancellation is cooperative. No interruption/rollback guarantee for an in-flight converter; queued, requested, completed, cancelled and unknown remain distinct.",
            },
            "tasks": {
                "state": "blocked",
                "reason": "No per-request authenticated principal/job supervisor across transient workers. Ordinary batch job tools exist; TaskExtension is not composed.",
            },
            "approval_continuations": {
                "state": "outside_workflow",
                "reason": "Offline state writes need no new approval UI. Highlighting still needs the user's request and unchanged native source preflight; guidance is not approval.",
            },
            "artifacts": {
                "state": "enabled",
                "boundary": "Completed preview/export receipts, current configured-root scope, hash-pinned 64 KiB chunks. Same-user app state; no per-chat confidentiality claim. Captured freshness is not a new native validation.",
            },
            "framework_proxy_resources": {
                "state": "blocked",
                "reason": "The fixed stdio proxy forwards tools, not native skill/resource methods. Use the same selected route's guide/artifact tools; direct and app-owned HTTP profiles supply native resources.",
            },
            "restart": {
                "state": "blocked",
                "reason": "No surviving supervisor/cross-chat quiescence fence; never clear uncertain journals",
            },
            "redis_oauth_apps": {"state": "deferred", "reason": "Not required for local drawing workflows"},
        },
        "acceptance": "Source/synthetic/protocol evidence is separate from installed route, Codex skill selection, UI rendering and native AutoCAD acceptance",
    }
