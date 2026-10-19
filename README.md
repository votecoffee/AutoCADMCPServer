# AutoCAD MCP Server _(AutoCADMCPServer)_

Source-preserving local DWG, DXF, PDF and AutoCAD Electrical information extraction for MCP

Extract drawing information through a shared Python service, command line interface and Model Context Protocol server. Version 0.2 adds device and PLC I/O inventories, connection tracing, equipment grouping, documented network inventory, consistency checks, revision comparison and traceable JSON exports. Native report assertions, observed attributes and interpreted drawing content remain distinct. Sources are preserved. An optional guarded operation highlights a source object in an unchanged drawing already open in AutoCAD. The repository is named `AutoCADMCPServer`; the Python distribution uses `autocad-mcp-server` to follow Python package naming conventions.

## Table of Contents

- [Background](#background)
- [Install](#install)
  - [Dependencies](#dependencies)
- [Usage](#usage)
  - [CLI](#cli)
  - [Python](#python)
  - [Electrical projects](#electrical-projects)
  - [Connect through Universal Tools](#connect-through-universal-tools)
  - [Tools](#tools)
- [Extraction boundaries](#extraction-boundaries)
- [Validation](#validation)
- [Development](#development)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

## Background

Drawing review often requires finding text, part numbers, attributes, dimensions and references across several files. This server exposes those operations with source hashes and entity or page locations, so an MCP client can trace results back to the drawing. CLI and MCP operations use the same extraction service.

DWG conversion uses an independently installed ODA File Converter. DXF parsing uses [ezdxf](https://ezdxf.readthedocs.io/), PDF extraction uses [PyMuPDF](https://pymupdf.readthedocs.io/), and the server uses the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk). Backend limitations are described under [Extraction boundaries](#extraction-boundaries).

## Install

### Dependencies

- [Python](https://www.python.org/downloads/) 3.11 or later. The PowerShell examples use Python 3.13.
- [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter), installed separately, for DWG extraction. Windows installations are detected under `C:/Program Files/ODA`; an absolute executable path can also be configured. DXF and PDF extraction do not need ODA.

Optional source highlighting requires full AutoCAD running on Windows and pywin32, included in the Windows runtime lock through the MCP dependency. TrueView and ODA do not provide the live operation.

ODA and Autodesk binaries are not redistributed. Python runtime dependencies are installed from the hash-locked requirements file below.

In PowerShell:

```powershell
git clone https://github.com/votecoffee/AutoCADMCPServer.git
cd AutoCADMCPServer
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-lock.txt
.venv\Scripts\python.exe -m pip install --no-deps -e .
.venv\Scripts\python.exe scripts\configure.py --root 'drawings=C:\Engineering\Drawings'
.venv\Scripts\python.exe -m autocad_mcp status
```

Repeat `--root name=directory` to configure multiple projects. Configuration, caches, search indexes, previews and local acceptance evidence live under ignored `.local/`. The state directory must be separate from all source roots. Existing configuration is preserved; edit `.local/config.json` explicitly to change roots. See `examples/config.example.json`.

## Usage

### CLI

```powershell
.venv\Scripts\python.exe -m autocad_mcp inventory drawings
.venv\Scripts\python.exe -m autocad_mcp inspect drawings 'Assembly.dwg'
.venv\Scripts\python.exe -m autocad_mcp text drawings 'Electrical.pdf'
.venv\Scripts\python.exe -m autocad_mcp index drawings --offset 0 --limit 2
.venv\Scripts\python.exe -m autocad_mcp search drawings 'PART-123'
.venv\Scripts\python.exe -m autocad_mcp render drawings 'Assembly.dwg'
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
summary = service.inspect("drawings", "Assembly.dwg")
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

Replace IDs with returned values. Omit `--wdp` for ordinary DWG/DXF/PDF roots. Use `--options .local/build-options.json` for explicit drawing paths, native CSV/TSV/JSON reports, attribute mappings and wire layers. PDF tags stay separate candidates with page/bounding-box provenance. Analysis does not generate Electrical reports or read MDB databases directly. Unknown values, incomplete paths and ambiguous references remain explicit. See [Electrical data and report formats](docs/electrical-data.md) and the [JSON export schema](schemas/electrical-project.schema.json).

Python clients use `ElectricalService(service).build("drawings", ...)` from `autocad_mcp.electrical`, then its query, trace, compare and export methods. Keep build options and customer exports under ignored `.local/` or outside the checkout. Snapshot freshness is checked against current input hashes; historical snapshots remain readable for revision comparison.

### Connect through Universal Tools

Use the existing Universal Tools plugin and broker. This app does not require a separate Codex plugin. With the broker already installed:

```powershell
.venv\Scripts\python.exe scripts\register_broker.py `
  --broker-python 'C:\Tools\CodexMCPBroker\.local\runtime\Scripts\python.exe' `
  --broker-state 'C:\Tools\CodexMCPBroker\.local'
```

Then call Universal Tools `refresh_services`, search for `autocad`, describe the chosen tool and invoke it with its catalog revision. Registration preserves other services and refuses an existing `autocad` registration unless `--replace` is supplied. The installer inspects the installed broker schema and supports the older version-1 descriptor. Newer brokers receive an exact write allowlist. Older brokers use their service-wide write flag; five operations are write-classified: indexing, preview creation, electrical snapshot building, JSON export and AutoCAD UI highlighting. Only highlighting affects the running CAD display; file outputs are limited to app state.

Direct stdio MCP configuration uses the absolute `.venv/Scripts/python.exe` command with arguments `['-m', 'autocad_mcp', '--config', 'ABSOLUTE_CONFIG_PATH', 'serve']` and the checkout as working directory. No shell invocation is needed.

### Tools

| Tool | Purpose |
| --- | --- |
| `cad_status` | Roots, backends, limits and format support |
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
| `cad_search_project` | Literal project text search with freshness and coverage |
| `cad_compare_drawings` | Text multiplicity and layer/block name changes |
| `cad_render_preview` | App-owned PNG previews; write-classified |
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
| `cad_highlight_source_object` | Highlight/clear one top-level source object in an unchanged open AutoCAD drawing; write-classified |

## Extraction boundaries

DWG is converted to a temporary ACAD2018 DXF using the installed ODA File Converter, with audit and recursion disabled. DXF is parsed by ezdxf. DWT and DWS are routed through the same conversion path and need individual acceptance; these formats are not established by DWG tests. PDF embedded text and positions are extracted using PyMuPDF. PDF tables are heuristic and previews require visual review.

CAD results include handles, layout/layer identifiers, INSERT transforms and attached attributes, polyline vertices, spline control/fit points, knots, weights and XDATA where exposed by ezdxf. Block definitions retain local coordinates. Electrical analysis expands supported planar nested inserts separately and diagnoses unsupported arrays/extrusions; raw entity queries retain definition coordinates. Dimension values are raw entity measurements; formatted labels, scaling, style overrides and tolerances require separate interpretation. Drawing header extents can be stale or sentinel values and are reported as stored.

Native ACAD_TABLE cell semantics, proxy/custom objects, hatch boundaries, ACIS solids, dynamic block rules and arbitrary extension dictionaries are not fully decoded. There is no native AutoCAD acceptance claim. External references, images, underlays and fonts are not loaded by path; references are reported only. CAD previews use ezdxf's approximate renderer and installed fonts and can omit unsupported content.

Image-only or blank PDF pages are flagged as OCR candidates. No OCR engine is automatically invoked. PDF text can be split into characters, duplicated, hidden or incorrectly mapped by embedded fonts; search results must be interpreted with their page context. PDF point coordinates do not establish physical CAD dimensions. DGN, DWF/DWFx, STEP/IGES, SolidWorks, eDrawings, archives and other extensions are inventoried but not parsed.

File tools accept only named roots and relative paths. Path traversal and alternate data streams are rejected; inventory skips symlinks and junctions. Tool inputs cannot choose executables or output directories. Parsing, table extraction and rendering run in bounded child processes on source snapshots. The worker timeout is 120 seconds, ODA's is 60 seconds, the input limit is 256 MiB, and JSON tool responses are capped at 200 KB. Large rows carry explicit truncation/omission flags. Exceeding limits produces errors instead of a partial extraction. Read operations may create content-addressed caches; model files remain unchanged. Source identity uses SHA-256, checked around snapshots and operations. A concurrent external edit can still change a source after a response has been returned.

## Validation

See [VERIFICATION.md](VERIFICATION.md) for synthetic checks, real MCP protocol checks and optional private corpus acceptance. Customer drawings, configuration, extracted text, indexes and previews are excluded from release packages.

## Development

Install `requirements-dev-lock.txt` and the editable package, run `python -m pytest -q`, and run `ruff check .` plus `ruff format --check .`. CLI and MCP operations share `DrawingService`; add extraction logic there or in its workers rather than duplicating it in the transport.

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
