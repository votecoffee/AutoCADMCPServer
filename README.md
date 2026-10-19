# AutoCAD MCP Server

Local information extraction from DWG, DXF and PDF drawings through a shared Python service, command line interface and Model Context Protocol server. Sources are preserved. No CAD editing or native application control tools are exposed.

## Install

Python 3.11 or later is required. On Windows, install ODA File Converter separately for DWG extraction. The converter is detected under `C:/Program Files/ODA` or configured with an absolute executable path. ODA and Autodesk binaries are not redistributed.

From the checkout in PowerShell:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-lock.txt
.venv\Scripts\python.exe -m pip install --no-deps -e .
.venv\Scripts\python.exe scripts\configure.py --root 'drawings=C:\Engineering\Drawings'
.venv\Scripts\python.exe -m autocad_mcp status
```

Repeat `--root name=directory` to configure multiple projects. Configuration, caches, search indexes, previews and local acceptance evidence live under ignored `.local/`. The state directory must be separate from all source roots. Existing configuration is preserved; edit `.local/config.json` explicitly to change roots. See `examples/config.example.json`.

## Usage

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

### Connect through Universal Tools

Use the existing Universal Tools plugin and broker. This app does not require a separate Codex plugin. With the broker already installed:

```powershell
.venv\Scripts\python.exe scripts\register_broker.py `
  --broker-python 'C:\Tools\CodexMCPBroker\.local\runtime\Scripts\python.exe' `
  --broker-state 'C:\Tools\CodexMCPBroker\.local'
```

Then call Universal Tools `refresh_services`, search for `autocad`, describe the chosen tool and invoke it with its catalog revision. Registration preserves existing services and refuses an existing `autocad` registration. For deliberate updates, validate the generated descriptor and use the broker CLI's explicit `register --replace` option. The installer inspects the installed broker schema and supports the older version-1 descriptor. Newer brokers receive an exact write allowlist. Older brokers use their service-wide write flag; this server exposes only two write-classified operations, indexing and preview creation, both limited to app state.

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

## Extraction boundaries

DWG is converted to a temporary ACAD2018 DXF using the installed ODA File Converter, with audit and recursion disabled. DXF is parsed by ezdxf. DWT and DWS are routed through the same conversion path and need individual acceptance; these formats are not established by DWG tests. PDF embedded text and positions are extracted using PyMuPDF. PDF tables are heuristic and previews require visual review. The parser stack includes PyMuPDF, which is available under AGPL/commercial licensing; review dependency licenses before redistributing a combined product. No commercial license is supplied by this project.

CAD results include handles, layout/layer identifiers, INSERT transforms and attached attributes, polyline vertices, spline control/fit points, knots, weights and XDATA where exposed by ezdxf. Block definitions retain local coordinates. Nested insert transforms are not expanded into world geometry. Dimension values are raw entity measurements; formatted labels, scaling, style overrides and tolerances require separate interpretation. Drawing header extents can be stale or sentinel values and are reported as stored.

Native ACAD_TABLE cell semantics, proxy/custom objects, hatch boundaries, ACIS solids, dynamic block rules and arbitrary extension dictionaries are not fully decoded. There is no native AutoCAD acceptance claim. External references, images, underlays and fonts are not loaded by path; references are reported only. CAD previews use ezdxf's approximate renderer and installed fonts and can omit unsupported content.

Image-only or blank PDF pages are flagged as OCR candidates. No OCR engine is automatically invoked. PDF text can be split into characters, duplicated, hidden or incorrectly mapped by embedded fonts; search results must be interpreted with their page context. PDF point coordinates do not establish physical CAD dimensions. DGN, DWF/DWFx, STEP/IGES, SolidWorks, eDrawings, archives and other extensions are inventoried but not parsed.

File tools accept only named roots and relative paths. Path traversal and alternate data streams are rejected; inventory skips symlinks and junctions. Tool inputs cannot choose executables or output directories. Parsing, table extraction and rendering run in bounded child processes on source snapshots. The worker timeout is 120 seconds, ODA's is 60 seconds, the input limit is 256 MiB, and JSON tool responses are capped at 200 KB. Large rows carry explicit truncation/omission flags. Exceeding limits produces errors instead of a partial extraction. Read operations may create content-addressed caches; model files remain unchanged. Source identity uses SHA-256, checked around snapshots and operations. A concurrent external edit can still change a source after a response has been returned.

## Validation

See [VERIFICATION.md](VERIFICATION.md) for synthetic checks, real MCP protocol checks and optional private corpus acceptance. Customer drawings, configuration, extracted text, indexes and previews are excluded from release packages.

## Development

Install `requirements-dev-lock.txt` and the editable package, run `python -m pytest -q`, and run `ruff check .` plus `ruff format --check .`. CLI and MCP operations share `DrawingService`; add extraction logic there or in its workers rather than duplicating it in the transport.
