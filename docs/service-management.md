# Service management

AutoCAD 0.5 uses the shared framework 0.18 management interface. It reports to the existing Windows MCP Service Manager; AutoCAD setup does not install or launch another manager. The standalone plugin, native tool schemas and selected extraction route remain independent.

## Owning processes

Each direct `serve` process registers for its lifetime with a random instance ID and the canonical installed plugin ID `autocad@autocad-local`. The optional `framework-serve` host registers its own lifetime and counts backend submissions. Its proxy and short-lived `--workflow` extraction backends do not create additional rows. Multiple direct client processes have separate rows; status does not assert ownership of another process's drawing work.

The default private registry uses the Windows Local AppData known folder without package redirection, followed by `CodexMCPManager/Registry`. The framework supplies authenticated literal-loopback endpoints, private registry ACLs, bounded JSON and a durable restart journal. Tokens and runtime files remain outside public source and logs. `--management-registry ABSOLUTE_PRIVATE_DIRECTORY` on an owning serve command, or `AUTOCAD_MCP_MANAGEMENT_REGISTRY`, selects a separate registry for isolated testing. Neither changes an MCP endpoint or configures an external broker.

The management callback reads only cached component metadata and synchronized in-memory request counters. Pending and active requests, including control requests, count as work. A separate bounded background refresh reads installed distribution metadata, local publisher version metadata and the fixed read-only Codex plugin inventory. It does not read drawing content, attach AutoCAD, contact controllers or poll package feeds. Inventory failures mark cached data stale. Unknown availability remains unknown; update-pending flags use explicit numeric local-version comparisons. Installed and running versions remain distinct.

Generated plugin bindings identify their package version through `AUTOCAD_MCP_PLUGIN_VERSION`. A manually started process leaves that value unknown. Framework and SDK availability remain unknown without a configured release source. Updating native plugin bytes still needs installation and host reload.

## Restart boundary

Restart remains disabled. AutoCAD has no surviving supervisor and no atomic cross-chat quiescence fence covering other processes' leases, queued work, prepared actions and unresolved native effects. Status includes this specific reason. No management request saves or closes AutoCAD, kills a process, guesses a launch command, retries an operation or clears a receipt.

The framework commits restart intent before admission and preserves duplicate-ID receipts and app-wide uncertain barriers across process lifetimes. AutoCAD supplies only a blocked `RestartResult`; no native restart effect is enabled. App-only `pending_restarts()` and `reconcile_restart()` are inherited framework APIs for a future independently verified operator workflow, not exposed MCP or tray actions. Restart acceptance and replacement health are separate facts; no real restart acceptance is claimed here.

## Observation and checks

When the plugin starts its stdio service, its live management row reports running or busy after metadata refresh. Closing that owner leaves a stopped registration; an interrupted process becomes offline. Installing an enabled plugin does not start a service. The manager can show an installed plugin as not reporting until an owner runs. AutoCAD does not start a background drawing service solely to populate the tray.

Use synthetic input and a dedicated registry for `tests/test_management.py`, protocol and framework checks. Verify cached versions, unknown availability, source updates, active requests, stale and concurrent restart refusals, zero native effects, uncertain intent survival and clean owner shutdown. Run the upstream pinned `tests/test_management.py` separately for synthetic accepted restart counts, authentication and durable journal contracts. Real native restart, multi-chat supervisor fencing and host UI rendering remain acceptance work. See the [upstream contract](https://github.com/votecoffee/CodexMCPBroker/blob/7d8a0ccdc06598313061147ee8774837118a8861/docs/service-management.md).
