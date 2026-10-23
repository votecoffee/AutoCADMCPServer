# AutoCAD MCP Server _(AutoCADMCPServer)_

<img src="assets/autocad.png" width="96" height="96" alt="AutoCAD MCP Server icon">

Source-preserving local DWG, DXF, PDF and AutoCAD Electrical information extraction for MCP

Extract drawing information through a shared Python service, command line interface and standalone Model Context Protocol server. Device and PLC I/O inventories, connection tracing, equipment grouping, documented network inventory, consistency checks, revision comparison and JSON exports retain source evidence. Native report assertions, observed attributes and interpretation stay distinct. The repository is named `AutoCADMCPServer`; the Python distribution is `autocad-mcp-server`.

AutoCAD owns its **standalone server, Codex plugin and drawing-analysis skill**. [CodexMCPBroker](https://github.com/votecoffee/CodexMCPBroker) supplies the pinned shared Python framework and a **separate Windows management application**. AutoCAD does not route through a broker or install a universal plugin. Its installer does not install or start the manager.

The default is **direct standalone offline** on Windows: local PDF/DXF and Electrical report analysis. A separate explicit [oda-read candidate](docs/oda-read.md) restores contained DWG/DWT/DWS structural conversion and previews with a pinned operator-installed ODA executable. Source/package preparation leaves an accepted offline installation unchanged. AutoCAD COM attachment/highlighting remains unavailable. See [offline profile and launch scope](docs/offline-profile.md).

The current implementation provides 38 tools, revision/hash-pinned workflow guidance, bounded background index jobs, chunked artifact reads and durable request receipts. Windows workers use app-owned Job Objects and creation-checked resource records. Stdio lifetime monitoring retains the original client pipe before SDK descriptor diversion; numerical libraries are limited to one numerical thread per app/worker process. See the [implementation guide](docs/implementation.md) for responsibilities and limits.

Current source release: **26.1023.113921**, stamped once in `America/New_York`. The app and both plugin manifests share the canonical package version `26.1023.113921`. [Versioning](docs/versioning.md) explains padded display timestamps, leading-zero normalization and release checks. Framework `0.20.0` and MCP SDK `2.3.0` remain independently pinned. Source/package verification does not establish installed or native acceptance.

## Table of Contents

- [Background](#background)
- [Install](#install)
  - [Dependencies](#dependencies)
- [Usage](#usage)
  - [CLI](#cli)
  - [Python](#python)
  - [Electrical projects](#electrical-projects)
  - [Shared app framework](#shared-app-framework)
  - [Standalone Codex plugin](#standalone-codex-plugin)
  - [Tools](#tools)
- [Extraction boundaries](#extraction-boundaries)
- [Validation](#validation)
- [Development](#development)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

## Background

Drawing review often requires finding text, part numbers, attributes, dimensions and references across several files. This server exposes those operations with source hashes and entity or page locations, so an MCP client can trace results back to the drawing. CLI and MCP operations use the same extraction service.

Retained DWG conversion code is disabled in the standalone offline profile. DXF parsing uses [ezdxf](https://ezdxf.readthedocs.io/), PDF extraction uses [PyMuPDF](https://pymupdf.readthedocs.io/), and the server uses the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk). Backend limitations are described under [Extraction boundaries](#extraction-boundaries).

## Install

From the project root, `InstallAndRun.cmd --help` lists options without installing dependencies or changing configuration. The same CMD installs and runs the application; `--install-only` stops after setup, and `--stdio` selects MCP stdio. Quote paths with spaces:

```powershell
.\InstallAndRun.cmd --framework-wheel "C:\Package files\universal_codex_tools-0.20.0-py3-none-any.whl" --root "drawings=C:\Engineering Drawings" --install-only
```

The default setup may register or refresh AutoCAD's standalone plugin. Use `--codex-integration none` to install the application without Codex registration. Existing roots are preserved. Setup remains an explicit installation operation; documentation and fixture checks do not require rerunning it on an existing installation.

### Dependencies

- [Python](https://www.python.org/downloads/) 3.11 or later. The PowerShell examples use Python 3.13.
- The verified local `universal-codex-tools==0.20.0` framework wheel built from the [pushed framework baseline](https://github.com/votecoffee/CodexMCPBroker/commit/5b2cac50ca24d21a15b732e0424bb02fd794e1fb). It is a normal pinned Python dependency; no public package feed is shipped yet. MCP is pinned at **2.3.0**; setup rejects an older framework SDK pin instead of downgrading the app. See [framework dependency and verification](docs/shared-app-framework.md#dependency-and-packaging).
- PDF/DXF extraction uses the locked Python libraries; no external converter or CAD application is needed. The default offline profile refuses ODA conversion even when ODA is installed. The separate [oda-read candidate](docs/oda-read.md) requires explicit configuration and a reviewed executable hash.

AutoCAD highlighting remains unavailable in both profiles. Retained native code and COM stubs do not activate it. No configuration, environment or tool option enables AutoCAD COM attachment.

ODA and Autodesk binaries are not redistributed. Python runtime dependencies are installed from the hash-locked requirements file below.

From a checkout on Windows:

For Windows setup and a foreground compatibility server, run `InstallAndRun.cmd` in the project root. On first setup, supply `--framework-wheel PATH`; the verified wheel is cached privately for subsequent installs. Setup creates or reuses this checkout's `.venv`, installs hash-locked dependencies and the application, preserves existing configuration, and starts legacy loopback MCP HTTP at `http://127.0.0.1:8796/mcp`. On first setup it prompts for a drawing folder. Python 3.11 or newer is required; `uv` is used when available, with pip as the fallback. Native conversion stays disabled. Framework source alignment does not automatically select its new host for an installed workflow.

```powershell
.\InstallAndRun.cmd --framework-wheel 'C:\Packages\universal_codex_tools-0.20.0-py3-none-any.whl' --install-only
.\InstallAndRun.cmd
.\InstallAndRun.cmd --install-only
.\InstallAndRun.cmd --port 8797
.\InstallAndRun.cmd --stdio
```

For unattended first setup, use `InstallAndRun.cmd --root "drawings=C:\Engineering\Drawings" --install-only` after staging the framework wheel; repeat `--root` for multiple roots. Setup creates `AutoCAD MCP Server.lnk` in the project root using the bundled icon. The shortcut contains local paths, is ignored by Git, and is recreated for each checkout. `--stdio` keeps setup messages on stderr and does not prompt, create a shortcut or change Codex integration implicitly. Keep the server window open and press Ctrl+C to stop. Standalone bindings start their own stdio backend. The experimental framework frontend connects to its already-running app-owned host.

Setup defaults to `--codex-integration auto`, which installs or refreshes AutoCAD's standalone plugin. It preserves an explicitly saved skip or a disabled app plugin. An absent CLI or unreadable plugin inventory defers optional installation while leaving the application usable. Use `--codex-integration none` to skip plugin installation or `--install-plugin` to explicitly refresh and enable it. See [standalone plugin installation](docs/codex-integrations.md).

Each application owns its Codex plugin and native skills; installation never depends on a universal plugin. The [shared framework and independent Windows manager](https://github.com/votecoffee/CodexMCPBroker) supply common code and management. The historical Python names `universal-codex-tools` and `universal_tools` identify that package, without adding a universal Codex connection.

For manual installation in PowerShell:

```powershell
git clone https://github.com/votecoffee/AutoCADMCPServer.git
cd AutoCADMCPServer
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes --find-links C:\Packages -r requirements-lock.txt
.venv\Scripts\python.exe -m pip install --no-deps -e .
.venv\Scripts\python.exe scripts\configure.py --root 'drawings=C:\Engineering\Drawings'
.venv\Scripts\python.exe -m autocad_mcp status
```

Repeat `--root name=directory` to configure multiple projects. Configuration, caches, search indexes, previews and local acceptance evidence live under ignored `.local/`. The state directory must be separate from all source roots. Existing configuration is preserved; edit `.local/config.json` explicitly to change roots. See `examples/config.example.json`.

## Usage

Server instances and worker descendants have explicit ownership limits and shared 0.20 durable records. See [resource ownership and launch coverage](docs/resource-ownership.md) for tested harmless fixtures, protected native attachments and remaining MCP/native acceptance checks. A service restart remains disabled.

### CLI

```powershell
.venv\Scripts\python.exe -m autocad_mcp --version
.venv\Scripts\python.exe -m autocad_mcp inventory drawings
.venv\Scripts\python.exe -m autocad_mcp inspect drawings 'Assembly.dxf'
.venv\Scripts\python.exe -m autocad_mcp text drawings 'Electrical.pdf'
.venv\Scripts\python.exe -m autocad_mcp index drawings --offset 0 --limit 2
.venv\Scripts\python.exe -m autocad_mcp search drawings 'PART-123'
.venv\Scripts\python.exe -m autocad_mcp render drawings 'Assembly.dxf'
.venv\Scripts\python.exe -m autocad_mcp serve
```

Continue index batches at the returned `next_offset` until it is null; check every file status. Tools expose explicit pagination, source hashes and extraction versions. Single-file extraction populates a cache but does not automatically populate the project search index. Search excludes changed or deleted sources and reports current, missing and stale coverage. Reindex changed roots before relying on complete project search. Index cursors are offsets into sorted inventory; restart at zero if files are added or removed during a batch sequence.

`--config PATH` is a global option before the subcommand. `AUTOCAD_MCP_CONFIG` can supply its default. Optional Streamable HTTP binds only to loopback: `serve --transport streamable-http --port 8796`; stdio is the default integration. The loopback HTTP listener does not add authentication and is intended only for a trusted local machine.

### Python

The shared service can also be imported after configuring a drawing root:

```python
from autocad_mcp.config import Config
from autocad_mcp.service import DrawingService

service = DrawingService(Config.load(".local/config.json"))
summary = service.inspect("drawings", "Assembly.dxf")
print(summary["source"]["sha256"])
```

### Electrical projects

Index the selected drawings first, then build an immutable electrical snapshot:

```powershell
.venv\Scripts\python.exe -m autocad_mcp electrical-build drawings --wdp 'Control.wdp'
.venv\Scripts\python.exe -m autocad_mcp electrical-show PROJECT_ID --collection devices
.venv\Scripts\python.exe -m autocad_mcp electrical-show PROJECT_ID --collection plc_io
.venv\Scripts\python.exe -m autocad_mcp electrical-trace PROJECT_ID DEVICE_ID --terminal 01
.venv\Scripts\python.exe -m autocad_mcp electrical-compare BEFORE_PROJECT_ID AFTER_PROJECT_ID
.venv\Scripts\python.exe -m autocad_mcp electrical-export PROJECT_ID
```

Replace IDs with returned values. Omit `--wdp` for ordinary PDF/DXF roots. Use `--options .local/build-options.json` for explicit drawing paths, native CSV/TSV/JSON reports, attribute mappings and wire layers. PDF tags stay separate candidates with page/bounding-box provenance. Analysis does not generate Electrical reports or read MDB databases directly. Unknown values, incomplete paths and ambiguous references remain explicit. See [Electrical data and report formats](docs/electrical-data.md) and the [JSON export schema](schemas/electrical-project.schema.json).

Python clients use `ElectricalService(service).build("drawings", ...)` from `autocad_mcp.electrical`, then its query, trace, compare and export methods. Keep build options and customer exports under ignored `.local/` or outside the checkout. Snapshot freshness is checked against current input hashes; historical snapshots remain readable for revision comparison.

### Shared app framework

The direct standalone server uses framework 0.20.0 for shared resource ownership and management. It exposes all 31 original operations plus guide/reference readers, a capability report, direct-owner index jobs and bounded artifact reads: 38 definitions. Source checks, app authorization and durable receipts remain authoritative.

The separate `ApplicationHost` prototype has fourteen fixed frontend tools and versioned drawing backends. `framework-prepare` creates isolated publications, but **host/proxy CLI startup is blocked** until SDK stdio processes have app-owned tracking and containment. Preparation does not activate that route. Earlier protocol fixtures and published snapshots remain source-assessment evidence.

See [shared framework setup](docs/shared-app-framework.md) and [feature profiles](docs/runtime-features.md) before a separately selected pilot. The default plugin uses direct stdio; the interactive root CMD starts loopback HTTP unless `--stdio` is selected. Setup does not select a shared host or enable Tasks, Redis, OAuth or UI extensions.

### Standalone Codex plugin

AutoCAD reports owning service processes and cached component versions to the existing Windows MCP Service Manager. Restart remains disabled until an app-owned supervisor can enforce quiescence across chats. Setup does not install another manager. See [service management](docs/service-management.md) for instance lifetimes, version reporting and the restart boundary.

AutoCAD keeps the packaged `drawing-analysis` skill short and stable. It reads detailed guidance from `cad_get_workflow` and revision/hash-pinned topic references. The same canonical source generates real Skills-over-MCP manifests/resources on direct servers and the app-owned HTTP host. Connected guide publications keep native tool definitions stable; native plugin/skill metadata changes still need installation/reload. See [guidance and skill profiles](docs/workflow-guidance.md).

For long index batches, direct-owner job tools provide durable submission, real file-unit progress and cooperative cancellation between files. Preview/export receipts provide scoped, hash-pinned 64 KiB reads and native resource views where supported. `cad_capabilities` reports implementation and acceptance boundaries. See [jobs, caching and artifacts](docs/runtime-features.md).

The application ships its own standalone plugin. Explicitly install or restore it after configuring drawing roots:

```powershell
.\InstallAndRun.cmd --install-only --install-plugin
```

This registers `autocad@autocad-local` using the Codex CLI after the verified framework dependency has been staged. Default legacy bindings start the app's own stdio server without a separate HTTP server. The package retains the application icon and small drawing-analysis skill; detailed guidance is read from the backend. Generated bindings and local paths stay under ignored `.local/codex-marketplace/`. The portable template has no personal configuration. Framework binding preparation remains separate from its blocked deployment. See [framework plugin preparation](docs/shared-app-framework.md#publish-and-run-an-isolated-app-host).

Use a new local chat or reload the plugin connection to discover the current tools after installation. The local Codex CLI must be available. `python scripts/install_plugin.py --prepare-only` creates the local package without changing Codex registration. Packaging follows [OpenAI's plugin format](https://developers.openai.com/plugins/build/plugins).

The direct server admits four active normal requests and 32 queued requests per process by default. Processes sharing app state coordinate a four-worker child-process budget, refuse native conversion and AutoCAD UI calls in the offline profile. The app-owned framework host additionally serializes calls to one backend. All state-changing tools accept `request_id` for durable replay and recovery; inspect `cad_get_transaction` after a lost response. Index batches commit per file. See [concurrency and transaction boundaries](docs/concurrency.md).

Direct stdio MCP configuration uses the absolute `.venv/Scripts/python.exe` command with arguments `['-m', 'autocad_mcp', '--config', 'ABSOLUTE_CONFIG_PATH', 'serve']` and the checkout as working directory. No shell invocation is needed.

### Tools

| Tool | Purpose |
| --- | --- |
| `cad_status` | Roots, backends, limits and format support |
| `cad_capabilities` | Effective profile, implemented features and acceptance boundaries |
| `cad_get_workflow` | Current workflow guidance with revision and content hashes |
| `cad_get_workflow_reference` | Read one revision/hash-pinned guidance topic |
| `cad_concurrency_status` | Active/queued request counts and shared worker limits |
| `cad_get_transaction` | Durable write status and recorded result by request ID |
| `cad_list_files` | Recursive paginated inventory, including unsupported formats on request |
| `cad_inspect` | Metadata, units, layouts, entity/page/text counts and warnings |
| `cad_get_entities` | Entity properties filtered by type, layout, layer, block or handle |
| `cad_get_text` | Text, multiline text and inserted attributes; PDF page and bounding box |
| `cad_read_text_record` | Full text through bounded slices of a record |
| `cad_entity_vertices` | LWPOLYLINE vertex slices |
| `cad_get_layers` | Colors, linetypes and visibility/lock flags |
| `cad_get_blocks` | Definitions, base points and xref declarations |
| `cad_get_dimensions` | Measurements, type, override text and definition points |
| `cad_get_references` | Xref, image and underlay paths without resolving them |
| `cad_get_pdf_pages` | Page sizes, rotation, text and image counts, OCR candidates |
| `cad_get_pdf_tables` | Heuristic cell extraction on one page |
| `cad_index_project` | Bounded indexing into app-owned SQLite state; write-classified |
| `cad_start_index_job` | Submit a bounded batch to a selected long-lived direct owner |
| `cad_get_index_job` | Poll durable job progress with its private access token |
| `cad_cancel_index_job` | Request cooperative cancellation between files |
| `cad_search_project` | Literal project text search with freshness and coverage |
| `cad_compare_drawings` | Text multiplicity and layer/block name changes |
| `cad_render_preview` | App-owned PNG previews; write-classified |
| `cad_get_artifact` | Read scoped preview/export bytes in hash-pinned 64 KiB chunks |
| `cad_build_electrical_project` | Build a source-bound snapshot from drawings, optional WDP and explicit reports; write-classified |
| `cad_get_electrical_project` | Counts, check coverage and current input freshness |
| `cad_get_device_inventory` | Device occurrences with field provenance; optional separate PDF candidates |
| `cad_get_plc_io` | Controller/module/channel/address, connected devices, wires and terminals |
| `cad_get_connections` | Reported/interpreted edges, cable details and source references |
| `cad_trace_connection` | Bounded electrical/network paths with ambiguity and incomplete ends |
| `cad_get_equipment_groups` | Installation, location, enclosure/panel, station and WDP context |
| `cad_get_network_inventory` | Documented addresses, switches, ports/interfaces and unassociated IP text |
| `cad_check_drawing_consistency` | Duplicate tags, address conflicts, descriptions, references and panel differences |
| `cad_compare_electrical_revisions` | Added, removed and changed device, I/O and connection records |
| `cad_export_electrical_project` | Readback-verified JSON with source hashes and references; write-classified |
| `cad_highlight_source_object` | Refused in both selected profiles before AutoCAD COM access; write-classified |

## Extraction boundaries

DXF is parsed by ezdxf. DWG/DWT/DWS conversion is unavailable in the standalone offline profile, even when an ODA converter is installed. These native formats remain unsupported inventory/report references. PDF embedded text and positions are extracted using PyMuPDF. PDF tables are heuristic and previews require visual review.

CAD results include handles, layout/layer identifiers, INSERT transforms and attached attributes, polyline vertices, spline control/fit points, knots, weights and XDATA where exposed by ezdxf. Block definitions retain local coordinates. Electrical analysis expands supported planar nested inserts separately and diagnoses unsupported arrays/extrusions; raw entity queries retain definition coordinates. Dimension values are raw entity measurements; formatted labels, scaling, style overrides and tolerances require separate interpretation. Drawing header extents can be stale or sentinel values and are reported as stored.

Native ACAD_TABLE cell semantics, proxy/custom objects, hatch boundaries, ACIS solids, dynamic block rules and arbitrary extension dictionaries are not fully decoded. There is no native AutoCAD acceptance claim. External references, images, underlays and fonts are not loaded by path; references are reported only. CAD previews use ezdxf's approximate renderer and installed fonts and can omit unsupported content.

Image-only or blank PDF pages are flagged as OCR candidates. No OCR engine is automatically invoked. PDF text can be split into characters, duplicated, hidden or incorrectly mapped by embedded fonts; search results must be interpreted with their page context. PDF point coordinates do not establish physical CAD dimensions. DGN, DWF/DWFx, STEP/IGES, SolidWorks, eDrawings, archives and other extensions are inventoried but not parsed.

File tools accept only named roots and relative paths. Path traversal and alternate data streams are rejected; inventory skips symlinks and junctions. Tool inputs cannot choose executables or output directories. Parsing, table extraction and rendering run in bounded child processes on source snapshots. The worker timeout is 120 seconds, ODA's is 60 seconds, the input limit is 256 MiB, and JSON tool responses are capped at 200 KB. Large rows carry explicit truncation/omission flags. Exceeding limits produces errors instead of a partial extraction. Read operations may create content-addressed caches; model files remain unchanged. Source identity uses SHA-256, checked around snapshots and operations. A concurrent external edit can still change a source after a response has been returned.

## Validation

See [VERIFICATION.md](VERIFICATION.md) for synthetic checks, real MCP protocol checks and optional private corpus acceptance. Customer drawings, configuration, extracted text, indexes and previews are excluded from release packages.

## Development

Install the verified framework wheel with the hash-locked `requirements-dev-lock.txt` using a local wheel directory, then install the editable app. Run `python -m pytest -q`, `ruff check .` and `ruff format --check .`. Keep framework development/editable dependencies in an isolated environment; never copy its implementation or use a source submodule. CLI, legacy MCP and framework workers share `DrawingService`; add domain logic there or in its workers rather than duplicating it in a transport.

Follow the [developer guide](docs/development.md) for isolated setup, installer/configuration fixtures, dependency updates and source packaging. The [implementation guide](docs/implementation.md) maps the services, workers, receipts and management boundary. Optional host prototypes and native profiles require their own acceptance before deployment.

The source tree keeps the shared service and workers in `src/autocad_mcp/`, reusable command line helpers in `scripts/`, synthetic fixtures and checks in `tests/`, and generic configuration examples in `examples/`. Machine configuration, runtime environments, customer inputs, extracted content and acceptance captures belong outside the tracked tree or under ignored `.local/`.

Electrical normalization and project/report readers retain separate evidence classes for observed block attributes, interpreted content and explicitly imported Electrical report relationships.

## Maintainers

[@votecoffee](https://github.com/votecoffee).

## Contributing

Use [GitHub Issues](https://github.com/votecoffee/AutoCADMCPServer/issues) for questions, bug reports and proposed changes. Pull requests are welcome; include a description of the behavior and the relevant verification results.

Use synthetic fixtures for routine tests, preserve source drawings, and keep customer data, personal paths, credentials and machine-specific evidence out of commits. Follow [AGENTS.md](AGENTS.md) for repository guidance and [VERIFICATION.md](VERIFICATION.md) for checks and source packaging. Update this README when the public interface or installation process changes.

## License

[MIT](LICENSE) Copyright (c) 2026 votecoffee.

Third-party dependencies retain their own licenses. PyMuPDF is available under AGPL/commercial licensing; this repository does not supply a commercial license. ODA File Converter must be obtained separately under its own terms.
