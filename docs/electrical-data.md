# Electrical project analysis

Project operations provide inventories, PLC I/O, connection graphs, equipment groups, network observations, consistency checks, revision comparison and JSON exports. All operations share `ElectricalService` behind the CLI and MCP adapters. The [export schema](../schemas/electrical-project.schema.json) defines snapshot version 1.

## Workflow

1. Configure a named source root and index every selected drawing with `cad_index_project`. Continue its batches and inspect failures. Analysis requires an extraction cache matching the current source hash and extractor signature; it does not silently start a long conversion job.
2. Call `cad_build_electrical_project` with the root, optional WDP, optional drawing selection and explicitly supplied report files.
3. Use the returned `project_id` with inventory, PLC, group, network, connection and consistency tools. Queries are paginated. Read `freshness` on every result.
4. Use `cad_trace_connection` for one device and optional terminal/code. Fetch full edge evidence through `cad_get_connections` using returned connection IDs.
5. Export the complete snapshot with `cad_export_electrical_project`. This writes an app-owned JSON file, verifies readback and returns its SHA-256.

Example build arguments, with files inside the configured `drawings` root:

```json
{
  "root_id": "drawings",
  "electrical_project_path": "Control.wdp",
  "reports": [
    {"kind": "drawing_map", "relative_path": "reports/drawings.csv"},
    {"kind": "components", "relative_path": "reports/components.csv"},
    {"kind": "plc_connections", "relative_path": "reports/plc.csv"},
    {"kind": "from_to", "relative_path": "reports/connections.csv"},
    {"kind": "panel", "relative_path": "reports/panel.csv"}
  ],
  "wire_layers": ["WIRES"],
  "tolerance": 0.0001
}
```

Save the options without `root_id` under ignored `.local/` for `electrical-build drawings --options .local/build-options.json`. Without a WDP or explicit selection, analysis includes DWG, DXF and PDF files below the root. DWT/DWS templates require explicit selection. WDP defaults to its existing, allowed drawing members. A selected scope is limited to 200 drawings, 100,000 physical occurrences per drawing and 30,000 eligible straight wire segments per drawing. Smaller selections can be analyzed separately.

## Evidence and identities

| Evidence | Meaning |
| --- | --- |
| `autocad_electrical_report` / `native_report` | An explicitly imported report asserts a relationship. Original fields and report SHA/record ordinal are retained. The server has not authenticated the report or run Electrical's report engine. |
| `electrical_attribute_convention` | Observed Electrical-style attributes on a placed block. Attribute values are observations; they do not establish native database relationships. |
| `block_attributes` | Ordinary block attributes mapped by supported aliases or an explicit `attribute_map`. |
| `attribute_assertion` | A declared signal code, peer tag or other interpreted attribute relationship. |
| `geometric_interpretation` | Pins and selected wire geometry coincide within the configured tolerance, in drawing units. |
| `pdf_text_interpretation` | A tag-shaped or address-shaped text candidate with a page/bounding box. It is not a resolved device or electrical connection. |

`device_type` classification from descriptions is explicitly interpreted. Unknown manufacturer, catalog, controller, rack, slot, channel or equipment codes remain null/absent. Device rows represent occurrences: parent, child, panel and terminal representations remain identifiable. Counts are not counts of unique purchased hardware. Additional `MFGnn/CATnn` assignments are retained separately. Group records use explicit installation, location, enclosure/panel and station values; WDP section/subsection/folder groups remain project membership context. WD_M installation/location defaults are exposed as drawing context without silently applying inheritance rules.

Drawing provenance includes configured root alias, relative path, source SHA-256, observed revision/sheet candidates, layout, object handle and nested reference path. A unique WD_M drawing sheet takes priority over component/signal destination sheet attributes. Otherwise conflicting sheet/revision candidates leave the selected value unknown. PDF provenance uses page/bounding box and text index; it cannot provide a DWG handle. Report rows without drawing mapping retain report provenance and explicitly unresolved drawing provenance. Hash equality establishes byte identity, not native validity or semantic completeness.

Physical expansion excludes unplaced definitions. Supported planar nested inserts include transform/base-point handling and constant attributes. Arrays report their base occurrence only; cycles, deep nesting and unsupported extrusion are diagnosed. External references are declared but never loaded automatically.

## Native project and report inputs

WDP parsing reads project membership, descriptions, sections, subsections, folders and settings as data. It does not run macros, update a project database, generate reports, open drawings or resolve files outside configured roots. Direct MDB/Access, AEPX and spreadsheet report reading are not implemented; export selected report fields as CSV/TSV or a flat JSON array.

Reports accept UTF-8, BOM-marked UTF-16 and Windows-1252. CSV/TSV require unique headers. `field_map` maps an original customized label to its canonical field name, for example `{"Module tag": "PLCTAG"}`. Original fields remain in the snapshot. CSV row ordinals start at 2, counting the header; quoted multiline cells do not change the logical ordinal. JSON row ordinals start at 1. Nested cells are rejected. No formulas are evaluated.

| Kind | Required columns | Useful additional columns |
| --- | --- | --- |
| `components`, `panel` | `TAG` or documented `TAGNAME` | `DESC1..3`, `MFG`, `CAT`, `INST`, `LOC`, `HDL`, `SH`, `FILENAME`, `DWGIX`, `P1C2` |
| `plc_connections` | `PLCTAG`, `PLCADDR` | `PLCWNUM`, `PLCDESCA..E`, `PLCTERM`, `PLCTERMCODE`, `PLCDWGIX`, `PLCHDL`, `PLCMFG`, `PLCCAT`, `PLCINST`, `PLCLOC`, `CMP*`, `TERM*`, `CBL`, `CBLWC` |
| `from_to` | `CMP1`, `CMP2` or canonical `FROM_TAG`, `TO_TAG` | `PIN1/2`, `CMPHDL1/2`, `DWGIX1/2`, `SH1/2`, `INST1/2`, `LOC1/2`, `WIRENO`, `CBL`, `CBLWC` |
| `network` | `TAG` | `IP_ADDRESS`, `MAC_ADDRESS`, `HOSTNAME`, `NETWORK`, `INTERFACE`, `PORT`, `PEER`, `FILENAME`, `HDL` |
| `drawing_map` | `DWGIX`, `FILENAME` | Export an explicit project database FILETIME mapping; filenames must match the selected drawing paths. |

`DWGIX` is a database FILETIME identifier. It is never inferred from WDP drawing order. `DWGNAM` is not assumed to be a filesystem path. Explicit `FILENAME`, `FROM_FILENAME`, `TO_FILENAME`, `PLCFILENAME`, `CMPFILENAME` and `TERMFILENAME` can bind a selected drawing directly. Exact filename plus handle merges a report observation into one observed occurrence; multiple nested placements are ambiguous and remain separate. Unmapped report-only devices remain traceable to their report rows.

`PLCTERMCODE` and `TAGAxx` suffixes identify connection attributes, not hardware channels. Channels require an explicit `CHANNEL`/`CHANNELxx` field. `LINE1/LINE2` rack/slot text interpretation is separated in `inferred_fields`. Native PLC reports may name both a connected component and a terminal strip; the import preserves both without inventing their intermediate ordering. Use a From/To report for explicitly reported segments. Original terminal descriptions, wire layers, cable handles and other unused fields remain available in the complete export.

## Tracing and checks

Eligible wire layers come from explicit configuration, observed `WD_M.WIRELAYS` with simple `*`/`?` wildcard expansion, or a conservative layer-name rule, in that order. The selected layers and basis appear in `geometry_scope`. Other native wildcard operators require explicit layer configuration and produce diagnostics. An empty native wire-layer setting is not interpreted as every drawing layer; configure layers explicitly when needed. Straight LINE and unbulged LWPOLYLINE segments are supported. Curved wires and other geometric representations require report evidence or further implementation.

Endpoint/T joins and explicit WDDOT junctions connect. Unmarked interior crossings do not. Ambiguous pin/label positions at a crossing are left unattached. Unique SIGCODE source/destination matches can link sheets; missing, multiple or unrecognized source roles produce diagnostics. Parent/child, schematic/panel and LINKTERM relationships are nonconductive associations. LINKTERM alone does not bridge separate terminal levels. A trace can continue through a terminal at the same documented pin, and stops at another component; tracing another pin requires an explicit new request. Cable/core and connector segments are followed where reports provide endpoints. There is no inferred continuity through a component body or cable based solely on a shared label.

Traces distinguish reported paths, interpreted paths, branching, unresolved ends and budget truncation. Open paths remain incomplete. Trace budgets are bounded by 100 depth, 200 paths and 10,000 visited/queued nodes; tool payloads are limited to 200 KB. An explicit error or truncation prevents a complete-path claim. This is drawing evidence, not a continuity measurement.

Checks cover duplicate qualified primary tags, conflicting attributes, missing descriptions, PLC/network address conflicts, unresolved cross-references, declared external references, signal ambiguities and schematic/panel differences. Missing controller/network scope yields potential conflicts. If one inventory is absent, the panel comparison is not evaluable. Configurable cross-reference strings are preserved and marked unresolved unless a literal known identifier matches; even such a match does not establish a wire connection. Findings are review items, not a validated Electrical audit.

Revision comparisons match qualified equipment identities and compare semantic fields, PLC I/O and documented connection content. Source hashes changing alone do not generate equipment changes. Duplicate identities are reported as ambiguous. A renamed tag is reported as removed plus added. A changed geometric route can produce changed segments even when endpoint connectivity stays the same. Historical snapshots remain readable with explicit current-source freshness.

Network extraction reports documented addresses and peers only. It does not ping, browse a controller, contact a device or scan a network.

## Highlighting

`cad_highlight_source_object` takes a project ID, device ID, source index and optional `enabled=false` to clear highlighting. It uses Windows ActiveX `GetActiveObject` on an already-running AutoCAD instance. The source hash, extracted top-level handle, exact open document path, Saved/DBMOD state and object type are checked before UI changes. It never launches AutoCAD, opens a drawing, saves, or sends command strings. Nested placement highlighting is rejected because ActiveX cannot select one nested occurrence by its definition handle.

COM runs in a 30-second worker. A timeout reports unknown outcome and requires inspection before retrying. A completed call confirms the API returned, not independent visual verification. Local receipts are stored under app state. Full AutoCAD and pywin32 on Windows are required; TrueView and ODA alone cannot provide this operation.

## Autodesk references

- [PLC component connection fields](https://help.autodesk.com/cloudhelp/2024/ENU/AutoCAD-Electrical/files/GUID-69BC0FA3-B416-4D23-94BD-BC1082286CBA.htm)
- [Wire From/To fields](https://help.autodesk.com/cloudhelp/2016/ENU/AutoCAD-Electrical/files/GUID-7D10A9DF-F5AD-4071-8F68-4BAE7FB021F4.htm)
- [Component report fields](https://help.autodesk.com/cloudhelp/2024/ENU/AutoCAD-Electrical/files/GUID-D90536AC-6035-4B87-B138-1069F8728251.htm)
- [WDP project file format](https://help.autodesk.com/cloudhelp/2016/ENU/AutoCAD-Electrical/files/GUID-FD3F36A0-01B7-44D2-8B73-81721934A6BD.htm)
- [Schematic attribute conventions](https://help.autodesk.com/cloudhelp/2016/ENU/AutoCAD-Electrical/files/GUID-A42DA038-B1AB-4401-BD71-BC7A683D8DF7.htm)
- [HandleToObject](https://help.autodesk.com/cloudhelp/2018/DEU/AutoCAD-ActiveX-Reference/files/GUID-E03AFFD7-B473-45F9-9FF1-CE4D09C94CF3.htm) and [Highlight](https://help.autodesk.com/cloudhelp/2025/ENU/AutoCAD-LT-ActiveX-Reference/files/GUID-0A923D53-9C04-48F1-AF3A-BAD27CECCABC.htm)

- [Wire layer setup](https://help.autodesk.com/cloudhelp/2023/ENU/AutoCAD-Electrical/files/GUID-2343FAB6-7D7F-439E-A45F-CB1E9DE8719D.htm) and [WD_M drawing settings](https://help.autodesk.com/cloudhelp/2022/ENU/AutoCAD-Electrical/files/GUID-75AEBC13-2F09-4B9E-B349-C7B202D52119.htm)
