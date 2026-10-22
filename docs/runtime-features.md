# Runtime feature profiles

`cad_capabilities` is a read-only doctor/capability report. It names enabled implementations and concrete boundaries without attaching an engineering project. Source/package, protocol, installed-profile and actual Codex/native acceptance remain separate.

| Feature | Implementation/evidence | Installed/operational boundary |
| --- | --- | --- |
| Current guide and references | Enabled; canonical revision/hash-pinned tool and native skill views | Native metadata changes require installation; running workers use explicit publication/refresh |
| Native modern discovery caching | Enabled; two-second private tools/resource listing hints; independent SDK caches and event invalidation tested | Legacy clients get no hints; missing hints disable caching; no app results/effects are cached by this choice |
| Retained modern host | Explicit opt-in, synthetic same-result and warm-latency comparison | Dedicated host state; not selected by setup; real host/native acceptance remains unassessed |
| Progress | Enabled for synchronous indexing and job polling; monotonic files-examined units | No fabricated percentages; disconnected progress recipients do not stop or roll back work |
| Cooperative cancellation | Enabled for direct-owner index jobs; queued versus in-flight behavior and independent effects tested | A running converter finishes/fails under its existing deadline before cancellation can stop the next file |
| App-owned index jobs | Enabled on a long-lived direct service; durable intent, request receipt deduplication, capability access and owner-loss barriers | Worker threads are not portable or supervised; keep the owner alive; abandoned ownership becomes unknown |
| MCP Tasks | Blocked | No verified per-request principal/job supervisor across HTTP/proxy/transient workers; no `TaskExtension` claim or generic task wrapper |
| Approval continuations | Outside current offline workflow | No new approval prompts for metadata/state-only work; highlighting retains the user's request and native source preflight |
| Preview/export resources | Enabled; completed receipt, root scope, hash and bounded byte reads tested | Same-user app-state scope, not per-chat confidentiality; native fixed proxies use the ordinary reader |
| Service management | Enabled, cached status and versions | Restart disabled; no surviving supervisor/cross-chat quiescence fence |
| Process lifetimes | Implemented, operationally unassessed; bounded instance leases, Windows owned descendants and parent/EOF fences | Windows synthetic shutdown/owner-loss checks must pass before deployment; no native rollback or detached supervisor claim |
| Redis, remote OAuth, MCP Apps | Deferred | No deployment requirement or native/UI acceptance is implied by the dependency |

## Retained modern pilot

The default remains `transient-legacy` with catalog watching and discovery caching disabled. A separately selected host may use:

```powershell
python -m autocad_mcp --config .local/test-config.json framework-prepare --host-state .local/pilot-modern --discovery-profile retained-modern
```

This changes worker lifetime deliberately: one shared retained backend, wire revision `2026-07-28`, catalog watching and a two-second connection-scoped discovery ceiling. Switching an existing state's transient/retained profile is rejected; use dedicated host state and assess its ownership/lifecycle. Business targets, receipt IDs, source checks, write allowlist and cross-process resource locks remain authoritative. No install path selects this profile or changes the standalone plugin route.

SDK clients cache only when supported hints are present; discovery definitions never authorize a write. Invocation still checks schema, effect, policy and current catalog/review revision. Tool schema changes in immutable workers require publication and guarded replacement. Catalog notifications do not load code; resource notifications carry hints rather than artifact bytes. Reconnect and refetch after a stream ends. Use the existing app-admin retained-adapter retirement API only after app-owned quiescence and receipt/job reconciliation. Never seize another chat's context or acknowledge an uncertain effect automatically.

Tests record exact local samples as private JUnit properties. The discovery test counts four SDK listings served by one server round trip, verifies invalidation and prevents cache sharing between client instances. The retained pilot compares complete synthetic DXF results and warm timings against the transient profile. This is process/protocol evidence, not native AutoCAD performance certification.

## Bounded index jobs

`cad_start_index_job(root_id, offset, limit, request_id=...)` accepts 1..5 files. The app receipt confirms submission; the job's state confirms execution. Save its private `job_id`/`access_token`, poll `cad_get_index_job` and use `cad_cancel_index_job` for an explicit stop request. Tokens are checked against the job's configured-root/parser scope. A token is an app capability, not an authenticated MCP principal or approval.

Intent is committed before dispatch, including the exact selected paths and source hashes. Added files cannot shift a queued batch; changed inputs fail before replacing that file's index. Duplicate start request IDs return the original job; changed arguments are rejected. Queued cancellation prevents dispatch. Running cancellation is requested and takes effect between files. Completed, cancelled and unknown are terminal execution observations; a request cancellation or disconnect does not prove rollback or native stop. Each file commits independently. Failures remain in the result. Capacity follows the configured active/queued limits, with unknown jobs retaining reservations until inspected. A lost owner is marked unknown without redispatch, including after process loss. Active/unknown jobs block backend publication. Operator reconciliation/archival must preserve original operation IDs and uncertainty; no model-facing clear/retry override exists.

Transient backend processes cannot promise job survival, so app-host job start is rejected and job mutation tools are absent from its write allowlist. Direct services must remain alive; their worker threads have no surviving supervisor. Ordinary status/results remain available when notification support is absent. No Tasks extension is advertised until ownership and supervision can meet that separate contract.

## Scoped artifact reads

New previews/exports include a root authorization anchor in their completed app receipt. `cad_get_artifact(request_id, sha256, offset, length)` verifies the current configured root, allowed app-state output folder, successful receipt and exact file hash. It returns a bounded base64 chunk and an `artifact://autocad/...` resource URI. Length is limited to 65,536 bytes; consumers can reassemble chunks and verify the whole artifact hash. Resource reads enforce the same checks. Ordinary tool reads remain usable through fixed proxies without native resource forwarding.

Metadata discovery lists only already described resources and never opens drawings. List-change notifications signal new immutable URIs; resource bodies have no caching hints. Freshness describes captured source evidence rather than a new check against native CAD. An altered file/hash or changed root scope is denied. Historical artifacts lacking the authorization metadata are denied by the new resource view and can be regenerated through the existing render/export tools. Existing file/receipt readers are retained.
