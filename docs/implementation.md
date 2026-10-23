# Implementation guide

AutoCAD is an independent application. Its direct `serve` endpoint, CLI, Codex plugin
and `drawing-analysis` skill belong to this repository. The
[CodexMCPBroker project](https://github.com/votecoffee/CodexMCPBroker) provides a
shared Python framework and a separate Windows MCP Service Manager. The historical
distribution `universal-codex-tools` and import `universal_tools` are dependency
identities. No universal plugin or broker route is selected.

## Components

| Source | Responsibility |
| --- | --- |
| `src/autocad_mcp/service.py` | Root authorization, source identity, cache/index access and drawing operations shared by CLI/MCP |
| `extract.py`, `render.py`, `oda.py` | Bounded parsing/rendering and explicitly configured ODA conversion |
| `electrical*.py` | WDP/report imports, normalization, provenance, graph queries and immutable electrical snapshots |
| `server.py`, `electrical_server.py` | The 38 direct `cad_*` tool definitions and thin service calls |
| `coordination.py`, `transactions.py`, `batch_jobs.py`, `artifacts.py` | Admission, durable request receipts, bounded index jobs and scoped artifact reads |
| `owned_resources.py`, `owned_process.py`, `worker_launch.py`, `lifetime.py` | Supervisor ownership, private containment and client/parent lifetime monitoring |
| `management.py` | Authenticated management registration, cached status and separate component versions |
| `guidance.py`, `workflow_guidance.py`, `plugins/autocad/` | Current guidance/resources and the app-owned plugin/skill bootstrap |
| `scripts/launcher.py`, `install_plugin.py`, `framework_dependency.py` | Root CMD setup, standalone plugin preparation and exact framework-wheel verification |

Domain mutations belong in shared services. A transport must not bypass root/hash
checks, select an executable from a tool argument, or create another operation after
an uncertain reply. Experimental `framework-host`/`framework-proxy` deployment is
blocked pending its SDK stdio ownership adapter; direct standalone remains selected.

## Data and evidence

PDF and DXF extraction use PyMuPDF and ezdxf. The default `offline` profile refuses
DWG/DWT/DWS conversion and AutoCAD COM operations. Explicit Windows `oda-read`
configuration adds structural conversion using an operator-installed, SHA-256-pinned
executable. Conversion uses private snapshots and records input/converter/DXF hashes;
converted handles are unverified against the original DWG. It is not native AutoCAD
validation. See [ODA configuration and acceptance](oda-read.md).

Electrical results distinguish native report assertions, observed block attributes,
interpreted geometry and PDF candidates. WDP membership does not invent missing
Electrical relationships. Unknown fields, incomplete paths, unresolved cross-references
and ambiguity remain explicit. Snapshots and JSON exports retain source hashes,
sheet/revision context and handles/reference paths or PDF page/bounding boxes. See
[electrical data](electrical-data.md).

## Concurrency and recovery

Defaults admit four active normal requests and 32 queued requests per process, with
four extraction workers and one ODA converter per shared state. Server-instance,
index-job, queue and payload limits are independent; configured values are visible
through status/capability tools. Framework prototype calls to one backend serialize.
There is no project-wide transaction rollback or private per-chat drawing selection.

Every intended write has an app `request_id`; replay returns its durable receipt.
After a lost reply, inspect `cad_get_transaction` before taking further action.
Index batches commit per file. Background jobs require a selected long-lived owner
and capability token; cancellation is cooperative between files. MCP Tasks are not
enabled. Preview/export artifacts support scoped, hash-pinned 64 KiB reads. See
[concurrency](concurrency.md) and [runtime features](runtime-features.md).

On Windows, app-created trees receive private Job Objects and durable exact
host/PID/creation/image claims before execution. Nested workers retain their original
supervisor's ownership. Last-handle close covers abrupt owner loss; this is a lifetime
boundary, not a filesystem/network sandbox or engineering rollback. Parent monitoring
and the original stdio pipe fence remain independent. Pre-existing applications are
not private children, and AutoCAD COM attachment/highlighting remains unavailable in
both selected profiles. See [resource ownership](resource-ownership.md).

## Management and acceptance

The owning direct service reports cached app/plugin/framework/SDK versions and active
work to the separate Windows manager. Setup does not install/start that manager or
start a drawing service merely to populate it. Inventory failure is metadata
degradation, distinct from native-operation success. Restart remains blocked until a
surviving supervisor and cross-chat quiescence contract exist. See
[service management](service-management.md).

Framework 0.20.0 and MCP SDK/types 2.3.0 are pinned independently. Reviewed wheel bytes,
source/package fixtures, installed-cache verification, actual MCP use, native ODA and
native AutoCAD acceptance are separate evidence layers. Keep personal deployment
reports and preserved failures under ignored `.local/private-docs/`; do not turn
synthetic passes into installed or native claims.
