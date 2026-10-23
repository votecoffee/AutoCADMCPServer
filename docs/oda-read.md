# Contained ODA drawing reader

`oda-read` is an explicit Windows configuration for structural DWG/DWT/DWS extraction
and approximate previews. The default remains `offline`. AutoCAD's standalone plugin
uses the selected configuration directly; no broker, universal plugin or shared host is
required. Preparing a candidate does not upgrade an existing installed runtime.

## Configuration

Install ODA File Converter separately under its applicable license. Review its executable
and dependencies, then obtain the executable SHA-256 with PowerShell `Get-FileHash`.
Copy [the example](../examples/oda-read.config.example.json) to private configuration,
replace the paths/hash, and use a state directory separate from every drawing root and
accepted offline installation. The placeholder hash is deliberately invalid.

Use an absolute regular `.exe` path without links/junctions, a lowercase 64-character
`oda_sha256`, and `execution_profile: "oda-read"`. If `AUTOCAD_MCP_EXECUTION_PROFILE` is
set, it must match. No environment or MCP request flag selects a different profile or
binary. The app never searches for or downloads a converter. `cad_status` and
`cad_capabilities` report the effective configuration.

```powershell
python -m autocad_mcp --config C:\Private\oda-read.json status
python -m autocad_mcp --config C:\Private\oda-read.json inspect drawings 'Assembly.dwg'
python scripts/install_plugin.py --config C:\Private\oda-read.json --prepare-only
```

Use the reviewed candidate runtime for assessment. Preparing a plugin only writes
private bindings; it does not activate it. Generated standalone bindings fix the
environment to the selected profile. Existing bindings require explicit installation.

## Conversion and readback

The service hashes the source, makes a verified private snapshot and launches its owned
extraction/render helper. The adapter stages that snapshot alone in a temporary input
folder. DWT/DWS copies receive a `.dwg` name because they share the DWG container. ODA
receives fixed input/output folders, `ACAD2018`, `DXF`, recursion `0`, audit `0`, and the
exact filename. See the [ODA interface description](https://www.opendesign.com/guestfiles/oda_file_converter?language=en).

Before state initialization and each conversion, the executable hash is checked. A read
handle denies executable writes/deletion throughout conversion and DXF readback. This
pins the main executable, not its DLL dependencies. The operator must trust the complete
installation: process containment is not a filesystem/network sandbox. No companion
references are staged, but ODA may interpret paths embedded in a drawing. Do not infer
that references were resolved or that all converter I/O was restricted to staging.

The existing durable supervisor and Windows jobs contain converter descendants. A helper
checks its inherited supervisor record and actual named-job membership before launching.
Eight processes per tree, worker/ODA quotas, disconnected stdin, bounded diagnostics,
the 60-second converter deadline and outer worker deadline remain in force. Closing or
losing the supervisor closes its private tree. Attached/shared applications are protected.
Temporary files may remain after abrupt death; they are app-generated, not source edits.
No automatic native retry, source repair or ownership adoption occurs.

Nonzero exit, timeout, absent/extra output, directories, links/hardlinks, oversized output,
corrupt DXF and changed source/readback fail without publishing an extraction cache.
Exactly one bounded regular DXF is parsed with ezdxf. Results retain input, converter and
DXF hashes and output size. Cache identities include profile, converter pin and adapter
implementation. The original is rehashed before atomic publication.

Structural evidence does not establish native AutoCAD validation. Electrical reports,
ordinary attributes and geometry interpretations retain separate provenance. Proxies,
ACIS, native tables, unresolved references and dynamic blocks can remain incomplete.
AutoCAD COM extraction/attachment/highlighting is separately unavailable.

## Candidate acceptance

Synthetic tests and harmless Python stand-ins cover policy, parse readback, cache
publication, refusals, executable sharing and durable cleanup. They do not establish
native ODA acceptance. A pilot needs a reviewed executable/dependency inventory and one
disposable synthetic DWG, separate candidate runtime/config/state/registry, exact captured
supervisor/child identities, bounded process/memory observations and source/DXF/result
hashes. Verify cold extraction/preview, timeout/close/EOF cleanup, empty owned jobs and
genuine terminal ledger receipts. Preserve failures/uncertainty. Complete this pilot
before replacing an accepted offline deployment; no customer drawing or user AutoCAD
session is needed.
