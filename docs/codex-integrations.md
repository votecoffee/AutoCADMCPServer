# Codex integrations

AutoCAD MCP Server is an independent application with a shared Python service, CLI, MCP server and standalone Codex plugin. Universal Tools provides an additional discovery and routing path. Both paths use the same app services, source checks, authorization, request journal and state-directory locks. The broker is optional; it does not own the drawings or replace app validation.

## Installation selection

`InstallAndRun.cmd` accepts `--codex-integration auto|standalone|broker|none`. `--install-plugin` is an explicit standalone alias. Direct invocation of `scripts/install_plugin.py` retains its standalone default and accepts the same `--mode` values. `--config` binds either integration to the selected app configuration. `--prepare-only` generates private standalone bindings without registration.

| Selection | Behavior |
| --- | --- |
| `auto` | Preserve the saved route first, then any existing app plugin, including a disabled one. For a fresh integration prefer a current accepted broker route; otherwise install standalone. Defer when CLI discovery is unavailable. |
| `standalone` | Explicitly install/refresh and enable the app plugin, even if Universal Tools is present. |
| `broker` | Require an enabled Universal Tools plugin and current local acceptance evidence for this exact app/configuration/registration. Record the route without changing plugin settings or registrations. Missing prerequisites fail without a direct fallback. |
| `none` | Record that optional Codex integration is skipped. Keep all existing plugin settings intact. |

Saved selection lives in ignored `.local/codex-integration.json`. Automatic reinstall preserves it even if the broker, CLI or an app plugin later disappears. This is an installation preference, not a runtime router or permission grant. No automatic failover, uninstall, disable, broker restart, registration replacement or native attachment is performed. Ordinary `--stdio` startup does not run integration setup unless explicitly requested.

Plugin detection uses `codex plugin list --json` in the installing profile. A folder name, package availability or daemon process is insufficient. The shipped standalone plugin remains available through `--install-plugin`, regardless of which integration is preferred. Application installation and ordinary CLI/MCP operation do not require Codex.

## Broker registration and assessment

Use `scripts/register_broker.py --broker-python ABSOLUTE_PYTHON --broker-state ABSOLUTE_STATE` only for an explicitly selected broker installation. The command validates the installed schema and descriptor without invoking native tools. It never upgrades or restarts the broker. Existing `autocad` registrations require explicit `--replace`. `--prepare-only` leaves the broker registration untouched.

The descriptor uses a transient stdio adapter, a stable identity derived from app state and an exact allowlist for four app-state writes. Add `--include-highlighting` only when authorizing the guarded native display operation. A broker lacking scoped allowlists, transient modes or resource IDs is rejected. Do not infer installed runtime compatibility from its source checkout or plugin version.

Run the isolated compatibility fixture before a migration:

```powershell
.venv\Scripts\python.exe scripts\broker_smoke.py --broker-python 'C:\Tools\BrokerTest\Scripts\python.exe'
```

The selected Python must contain the broker version being assessed. The fixture starts a separate authenticated loopback broker and two stdio frontends, creates synthetic drawings, compares all app schemas/guidance and inventory results, exercises permitted writes, verifies cross-route app idempotency and separate broker receipts, and confirms that a blocked highlight never reaches the app. Its temporary state stays under `.local/validation/`; its report is `.local/validation/broker-compatibility.json`. It does not use normal broker settings, customer roots, active projects or native AutoCAD. It never records migration acceptance.

After an authorized app registration exists, prepare a passive assessment candidate:

```powershell
.venv\Scripts\python.exe scripts\assess_broker.py `
  --broker-python 'C:\Tools\CodexMCPBroker\.local\runtime\Scripts\python.exe' `
  --broker-state 'C:\Tools\CodexMCPBroker\.local'
```

This writes `.local/broker-assessment-candidate.json` with every acceptance gate false. It reads only the plugin inventory, app configuration, selected registration and broker package metadata; it does not initialize an app or read broker credentials. Evidence is pinned to the app version/code, workflow guidance, configuration, Codex profile, broker plugin/version, installed broker code/version and registration bytes.

Complete and retain local evidence for `metadata`, `adapter_workflows`, `host_guidance`, `recovery` and `coexistence`. Include fresh-chat selection and app guidance through the actual intended Codex host, explicit IDs, app/broker receipt reconciliation and no automatic writes after route loss. If highlighting is allowed, the separate `native_highlighting` gate also applies. A fixture pass does not satisfy host/native acceptance. Finish or reconcile pending operations and recovery barriers before selecting a different route.

Only after operator review, copy the candidate to `.local/broker-acceptance.json`, mark the supported checks true and set `status` to `accepted`. Retain evidence references there or alongside it. This is local installation policy, not cryptographic proof or authority to write. Setup does not generate acceptance. Changed fingerprints invalidate it. Do not copy acceptance between profiles or edit its fingerprints to bypass a failed assessment.

The accepted broker path can then be selected explicitly with `InstallAndRun.cmd --install-only --codex-integration broker`. Existing standalone plugins remain installed. Fresh integrations without an existing choice can skip standalone installation when the same accepted prerequisites are present. Until acceptance is complete, automatic setup retains or installs the standalone route.

## Guidance, concurrency and recovery

The standalone plugin bundles the route-aware `drawing-analysis` skill. The broker does not distribute skills. Equivalent app-owned workflow guidance is included in every MCP initialization response and available through Universal Tools `describe_service`. Assess its retrieval and use in the intended host before skipping the plugin. Catalog descriptions remain untrusted app data, not authority to perform unrelated work.

Read app tools through the broker's read channel. For writes, retain both a unique outer broker `request_id` and an app `request_id` inside `arguments`. Broker duplicate IDs are rejected; app IDs can return a recorded result for identical arguments. After a lost reply, inspect both journals and actual app state. Do not automatically resubmit a write through another route, recreate a lost broker context or clear its recovery barrier. Native UI effects are not rollback transactions.

Broker calls to one app are serialized even though the direct server supports concurrent requests. Transient adapters retain no private per-chat selection or in-memory project state; durable snapshots and receipts live in app state. Both routes must use the same app configuration/state and consistent worker settings to share locks. Deliberate coexistence does not fence an external GUI or authorize changing a currently selected native drawing. Highlighting retains its exact hash/document/handle checks.
