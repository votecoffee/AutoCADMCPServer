# Verification

Run from the checkout with its Python environment. No customer or native CAD files are needed for the synthetic suite.

```powershell
.venv\Scripts\python.exe -m pip install --require-hashes --find-links C:\Packages -r requirements-dev-lock.txt
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

Installer policy fixtures cover standalone installation and refresh, explicit skips and disabled plugins, unavailable CLI discovery, rejected removed modes and configuration without external registrations. Follow [standalone plugin installation](docs/codex-integrations.md). Test package refresh from the installed cache with separate clients, and retain native-highlighting and actual Codex UI acceptance as distinct checks.

The framework wheel is a required exact normal dependency built from the pushed baseline identified in [framework packaging](docs/shared-app-framework.md#dependency-and-packaging). Verify it with `python scripts/framework_dependency.py WHEEL_PATH`, then use its private/local wheel directory with the runtime or development lock. There is no public package feed. Verify both clean setup and explicit replacement of an earlier cached wheel: installation must use the new verified artifact, and copy/verification failure must preserve the previous cache. Seed an isolated environment with the previous same-version framework wheel, run setup through both uv and the pip fallback, then compare every installed framework module against the new wheel; metadata version checks alone are insufficient. Keep tests and package validation in a separate environment; update an installed app environment or plugin only when that installation is part of the requested task.

Run `python -m pytest tests/test_framework.py tests/test_framework_dependency.py tests/test_plugin.py -q -o junit_family=xunit1 --junitxml=PRIVATE_REPORT.xml` for focused framework checks, then the complete suite. Framework tests use actual drawing handlers, disposable sources, a private authenticated host and separate native clients/frontends. They verify fixed front-door schemas across backend/guide/parser updates, nested worker binding, result/schema parity, receipts, source preservation and deployment/config tampering. Latency samples are recorded as JUnit properties; keep reports private and state the selected transient lifecycle. See [framework acceptance limits](docs/shared-app-framework.md#validation-and-remaining-gaps). Native/Codex UI activation is not established by protocol fixtures.

For framework 0.18 alignment, verify the exact wheel metadata, license, RECORD and installed source bytes against its pinned commit, including extension, Tasks, skill-registry, authorization, deployment, protocol-relay, notification and shared-storage modules. Retain the default legacy/transient publication profile with watched discovery and caching disabled; assess `retained-modern` explicitly in dedicated state. Check that the catalog resource exposes only a generation, that explicit refresh updates it without changing front-door tool definitions, and that runtime aggregate counters contain numeric diagnostics. Deep and wide argument fixtures must reject before host/app write receipts exist, without source changes. The app host must reject replicated deployment while remaining usable by concurrent clients. These checks do not compose Tasks, relay sources, remote OAuth, Redis or UI extensions. Native operations must not be silently wrapped as durable jobs. Keep installed-plugin, live-pointer and native-project migration outside a source/package-only assessment.

Version 0.6 guidance, batch and artifact checks are in `tests/test_workflow_guidance.py` and `tests/test_batch_artifacts.py`. Run `python scripts/generate_skill.py --check` and validate the packaged skill's frontmatter separately. Real SDK protocol tests compare ordinary guide/reference results with `skills/list`, `skills/get` and resource hashes; exercise atomic update/removal/re-addition and failed publication; count cached discovery round trips; and verify independent clients plus reconnect. Test queued/running cancellation, duplicate start receipts, frozen paths/hashes, changed-source rejection, owner process loss and no redispatch. Check artifact bounds, current root authorization, completed receipt, tampering and tool/resource byte parity. The framework suite compares transient/retained results and records warm timings. Fixed stdio proxies do not forward native Skills/resources; verify ordinary readers there and native methods on the direct/app-owned HTTP profiles. Protocol success does not establish Codex skill activation or UI resource rendering.

When installation is requested, rerun the actual checkout's root installer using the verified wheel and the chosen standalone integration. Record installed versions and compare installed framework modules with the wheel. Preserve the drawing configuration bytes, verify the enabled plugin's cached files and launch its exact binding through two independent MCP clients. Run the app's `status`, protocol/parity and dependency checks, with private logs. Reconnecting the installed plugin is separate from native AutoCAD, host UI, remote identity-provider and Redis operational acceptance; optional profiles need their own app-owned implementation and validation before selection.

Management integration uses tests/test_management.py with dedicated registries. Verify cached app/plugin/framework/SDK versions, active work, stale and concurrent restart refusals, uncertain-intent barriers across lifetimes and clean shutdown. Run the pinned upstream management suite separately for accepted synthetic restart counts and durable lost-response behavior. Verify both direct stdio and the owning framework host register, while transient backends and proxies do not. No test should restart a real drawing process or install another manager. See docs/service-management.md.
