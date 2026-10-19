# Verification

Run from the checkout with its Python environment. No customer or native CAD files are needed for the synthetic suite.

```powershell
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev-lock.txt
.venv\Scripts\python.exe -m pip install --no-deps -e .
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check .
.venv\Scripts\ruff.exe format --check .
```

The tests construct their own DXF and PDF fixtures. They verify geometry and dimensions, inserted attributes, text locations, source preservation, corrupt-input failure, root boundaries, cache/index freshness, coverage, comparison multiplicities, payload pagination, table cells, CAD/PDF previews, tool annotations and structured output schemas. Electrical tests cover nested transforms, split tags, ordinary aliases, WDP membership, native report fields/FILETIME mapping, unresolved provenance, same-pin terminal tracing, nonconductive associations, T joins, crossing/dot rules, signal ambiguity, domain/budget bounds, historical comparison and export readback. AutoCAD tests use mock COM objects to verify preconditions and rejection before UI changes; they do not establish live AutoCAD acceptance. A real stdio test exercises uncached PDF/DXF extraction, electrical endpoints and table workers to detect Windows worker startup failures that cached calls would miss.

For the Windows launcher, run `InstallAndRun.cmd --install-only`, then check a real MCP handshake over its default HTTP transport and `--stdio`. First-install checks should use a separate extracted checkout and source folder, including paths with spaces; verify that `.venv` is created inside that checkout and that existing configuration remains unchanged. Installation output must stay on stderr in stdio mode. `--port 0` must return a nonzero exit code.

For a configured local corpus, exercise the real stdio protocol, initialization, discovery and extraction:

```powershell
.venv\Scripts\python.exe scripts\protocol_smoke.py --root drawings
.venv\Scripts\python.exe scripts\protocol_smoke.py --root drawings --project-id PROJECT_ID
```

For deliberate acceptance against every configured drawing root:

```powershell
.venv\Scripts\python.exe scripts\validate_corpus.py
```

This indexes supported files, records per-file metadata and errors, verifies project search coverage and hashes source files before and after. Files over the configured input limit are counted as excluded from preservation hashing. Failed extractions are recorded explicitly and produce a nonzero exit code. The private report is `.local/validation/corpus.json`; do not commit or redistribute it. Inspect representative PDF and CAD previews visually. Hash equality establishes byte preservation for the captured sources, not native CAD acceptance or semantic completeness.

Use `scripts/package.py --output ABSOLUTE_ZIP_PATH` to build a source-only archive with SHA-256 manifest. Packaging uses an explicit file allowlist. Extract that archive into a fresh work directory, verify its manifest with `scripts/package.py --verify`, install it into an isolated environment and rerun the synthetic and protocol checks. A source ZIP excludes runtime dependencies; a working ODA installation is a separate prerequisite for DWG extraction.

For private electrical acceptance, build snapshots for each selected scope, export their JSON, validate against `schemas/electrical-project.schema.json`, inspect representative inventory and trace records, and verify all input hashes. Native report import tests use synthetic CSV/JSON fixtures. Test live highlighting separately in full AutoCAD with an unchanged already-open drawing, verify the visible object and clear its highlighting. ODA/TrueView and mock tests do not establish that live behavior. Never commit private reports or drawing-derived fixtures.

Concurrency and operation receipt checks are documented in [docs/concurrency.md](docs/concurrency.md). Test the standalone plugin by preparing a local package, installing it with the Codex CLI, checking that it is enabled, and launching the installed cache MCP binding through real independent clients. Verify that the public source package excludes generated runtime bindings and private state.
