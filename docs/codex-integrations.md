# Standalone Codex plugin

AutoCAD MCP Server supplies its own Codex plugin. The plugin uses the app's shared services, source checks, authorization, durable request journal and state-directory locks. Setup has no external broker route or registration option.

The architecture is a shared app framework plus an independent Windows manager, with each application retaining its own plugin and native skills. AutoCAD installation is independent of any unrelated or retired plugin inventory entry. The historical framework distribution/import names remain `universal-codex-tools` / `universal_tools`; they are Python package identities, not a universal Codex plugin or connection.

## Installation

Run `InstallAndRun.cmd --install-only` after supplying the verified framework wheel on first setup. Normal setup installs or refreshes the standalone plugin. Use `--install-plugin` to explicitly refresh and enable it, or `--codex-integration none` to skip optional Codex installation. Drawing roots, caches and journals remain app-owned.

`--codex-integration auto|standalone|none` and `scripts/install_plugin.py --mode auto|standalone|none` are supported. Automatic setup preserves an explicit saved skip and a disabled plugin. Otherwise it refreshes the standalone package, including when a previous standalone version is installed. Missing Codex CLI or unreadable plugin inventory defers optional integration while the application remains usable. Explicit standalone installation requires the CLI. A saved unsupported integration must be replaced explicitly with `--install-plugin`; it cannot silently reactivate a removed route.

Selection is saved under ignored `.local/codex-integration.json`. Ordinary `--stdio` startup does not change plugin installation unless explicitly requested. Setup never removes another application's plugin or resets an operation journal.

Registration requires an installed `--stable-home`; checkout/cache bindings cannot be
published. [Stable launcher migration](stable-launcher.md) retains legacy route pins and
defers plugin registration until the serialized host publisher migrates that route.
`InstallAndRun.cmd --install-only --prepare-plugin --codex-integration none` prepares
the stable standalone package without writing host settings. Old caches, runtimes and
active peers remain available throughout publication.

## Frontends

The default native stdio endpoint exposes the 38 `cad_*` tools and starts its own app process. Use `cad_status` and the app's initialization guidance to select explicit drawing/project IDs.

The experimental framework frontend is source-assessment code with fourteen fixed tools and versioned drawing backends. Host/proxy CLI startup is blocked until SDK stdio ownership integration; no route switch occurs. See [framework lifecycle](shared-app-framework.md) and [resource coverage](resource-ownership.md). Shared framework code remains a pinned Python dependency, without an external registration or universal Codex connection.

`python scripts/install_plugin.py --prepare-only` generates private bindings without registering them. `--frontend framework --host-state PATH` explicitly prepares the app-owned frontend; native stdio remains the default. Generated bindings live under ignored `.local/codex-marketplace/`. Reload the plugin connection or use a new chat after native package updates.

Bindings fix `AUTOCAD_MCP_EXECUTION_PROFILE` to the explicitly selected configuration.
The default remains offline; [oda-read](oda-read.md) requires a reviewed converter pin
and separate candidate acceptance. Preparation does not change an installed plugin.

## Concurrency and recovery

Native calls can overlap within [app limits](concurrency.md); calls through one framework backend serialize. Durable drawing snapshots and request receipts are shared app state, with explicit targets rather than private per-chat selections.

Keep an app `request_id` for every intended write. Framework calls also need a separate outer host ID; the host and app journals describe different outcomes. After a lost response inspect the app receipt with `cad_get_transaction` and, when applicable, the host receipt with `get_request_status`. Never create another request to discover whether an uncertain write took effect. Source highlighting retains its exact hash/document/handle checks and separate native acceptance requirements.
