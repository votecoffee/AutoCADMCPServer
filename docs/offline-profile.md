# Standalone offline profile

The selected Windows profile is the app's independent native stdio MCP endpoint with `execution_profile: "offline"`. It provides local PDF/DXF extraction, previews, PDF tables, Electrical report/WDP membership analysis, inventories, tracing, consistency checks, revision comparison, bounded index jobs and scoped exports. Imported native Electrical relationships remain report assertions; PDF candidates and ordinary block interpretation retain their separate provenance.

DWG/DWT/DWS extraction and AutoCAD highlighting are unavailable in this release. These formats can appear in inventory or report references, but the app does not convert or open them. `cad_status` and `cad_capabilities` report the effective formats and refused operations. Native acceptance is separate from this useful offline profile.

## Enforced gates

- Missing `execution_profile` means `offline`; any other value is rejected. `AUTOCAD_MCP_EXECUTION_PROFILE` must be absent or `offline`, and generated standalone bindings explicitly set it to `offline`.
- `oda_executable` must be absent or empty. There is no ODA installation scan. Existing configurations with a converter path fail validation without being edited. Programmatic `DrawingService` construction applies the same check before state or executable access.
- Converter entrypoints reject native formats before output creation or process launch, even with a supplied executable. Highlight service, tool and private worker entrypoints reject before source lookup, COM attachment or helper launch. No environment, request or CLI option enables these native routes. Retained internals are tested only with stubbed gates/APIs.
- Experimental shared-host/backend/proxy startup remains blocked by its existing SDK stdio ownership gate. It is not part of this profile. There are no controller, source-control, vendor-application or drawing-edit tools. Source references do not execute commands.

Do not rewrite an installed configuration to adopt this release automatically. Prepare a separate explicit offline configuration and immutable package for a staged canary. Installation/activation needs its own release authorization.

Numerical library pools are fixed at one thread per process by package bootstrap before ezdxf/NumPy imports. Generated plugin environments also set OpenBLAS/OpenMP/MKL/BLIS/NumExpr/vecLib thread limits to one. These values override ambient numerical-pool settings; they are separate from the bounded MCP request and Python worker counts. Programmatic embedding that initializes numerical libraries before importing this package is outside the direct standalone startup contract.

## Enabled launch and ownership scope

The standalone binding uses the app Python executable directly, with no shell. Windows/Python/SDK launches can also create private OS console helpers; include their exact identities in job accounting and cleanup proof. They do not become drawing-worker supervisors. Codex owns the front-door launch and any Windows venv redirector; the running Python server is the actual durable supervisor of app-created children. The app never substitutes a temporary registration helper as owner. Server admission, captured-parent identity and non-consuming stdio EOF fences are in `lifetime.py`. Actual installed transport/redirector behavior needs a disposable MCP canary.

Extraction, render and table workers are private Python trees created in suspended Windows jobs, reserved durably before launch, bound to exact host/PID/creation/image identities before resume, and limited to eight processes per tree. The existing request, server, worker and job quotas also apply. No native converter or highlighting worker is reachable in this profile. Python libraries render to files without launching a viewer. Worker input is fixed app argv/files; stdin is disconnected and diagnostics are bounded.

The management listener runs inside the same front-door process; no manager application is launched. Its fixed read-only Codex inventory probe uses a contained native CLI, or explicit Node plus the official npm entrypoint. Unsupported shells are refused. Descendants remain in the same private job; exact binary/package hashes and real CLI behavior must be checked in the canary environment. Setup scripts and `InstallAndRun.cmd` are explicit operator installation paths, outside MCP runtime child ownership and outside a source-only assessment.

Normal close fences work and closes jobs before reporting ends. Timeout, failed startup, EOF/parent loss and abrupt owner death have pure/harmless Windows fixture coverage; last-handle job closure contains unsampled descendants. Unfinished jobs and writes remain unknown without replay. The independent manager can inspect the durable ledger and apply a reviewed current-revision cleanup plan only when its exact identity, ownership and barrier checks permit it. Existing attached/shared/dirty/foreign/uncertain resources remain protected. See [resource ownership](resource-ownership.md).

## Acceptance boundary

Source/package checks and harmless process fixtures establish the implementation gate. They do not establish actual MCP transport, installed cache, Codex activation, native engineering behavior or manager UI acceptance. After independent source review, one explicitly authorized disposable direct stdio canary should verify exact packages/config/binding, real offline reads and workers, manager identity/reporting, two clients, EOF/close/crash cleanup and retained unknown work. No normal installed configuration, plugin or existing application is changed by source preparation.
