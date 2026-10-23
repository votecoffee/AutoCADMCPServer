# Developer guide

Read [AGENTS.md](../AGENTS.md), the [implementation guide](implementation.md) and
[VERIFICATION.md](../VERIFICATION.md) before changing extraction or publication.
Preserve drawings and existing installed runtimes; routine documentation and fixture
work does not require installation, plugin reload, service restart or native activation.

## Isolated setup

Use Python 3.11+; the hash locks target Windows Python 3.13. Obtain the reviewed
framework wheel described in [dependency packaging](shared-app-framework.md#dependency-and-packaging).
The dependency comes from [CodexMCPBroker](https://github.com/votecoffee/CodexMCPBroker),
which also supplies a separate Windows management app. AutoCAD retains its own MCP
server/plugin/skills. Do not vendor framework code or introduce a universal plugin.

```powershell
py -3.13 -m venv .local\dev-runtime
.local\dev-runtime\Scripts\python.exe -m pip install --require-hashes --find-links "C:\Package files" -r requirements-dev-lock.txt
.local\dev-runtime\Scripts\python.exe -m pip install --no-deps -e .
.local\dev-runtime\Scripts\python.exe -m pytest tests/test_codex_config.py tests/test_launcher.py tests/test_plugin.py -q
.local\dev-runtime\Scripts\ruff.exe check .
.local\dev-runtime\Scripts\ruff.exe format --check .
```

Full protocol/lifecycle checks start processes and need their documented isolated
configuration/registry. Keep framework 0.20.0 and MCP SDK/types 2.3.0 at reviewed
hashes; a source checkout or a matching version number alone does not identify
accepted package bytes. See [framework integration](shared-app-framework.md).

## Root CMD and installation checks

`InstallAndRun.cmd` forwards arguments to `scripts/launcher.py`, prefers this
checkout's `.venv`, then tries the Python launcher/Python. The launcher creates its
environment inside the checkout, verifies locked dependencies, preserves existing
roots and starts loopback HTTP unless `--stdio` or `--install-only` is selected.
Default setup may refresh AutoCAD's standalone plugin; `--codex-integration none`
skips registration. `--stdio` does not implicitly install a plugin.

`tests/test_launcher.py` copies the real CMD into a disposable directory containing
spaces and `&`, creates a disposable Python environment, and checks real help,
invalid-port failure, quoted argument/cwd forwarding and child failure propagation.
A tiny stand-in launcher exercises forwarding without installing anything. These
fixtures do not validate dependency installation or alter live Codex settings.
Run any full install separately in an extracted disposable checkout; never use an
accepted installation as a setup fixture.

## TOML publication bytes

Public AutoCAD setup delegates Codex registration to its CLI; it has no direct
`config.toml` rewrite. Private reusable publication helpers must follow the same
review discipline as public code. Never rewrite live settings as part of testing.

`scripts/codex_config.py::render_toml` is a pure renderer for reviewed candidate
content. It requires the complete expected parsed settings, normalizes LF/CRLF once,
validates TOML and encodes UTF-8 bytes. Windows output explicitly uses CRLF. Publish
those bytes with binary I/O, after reviewing the target, backup, current bytes and
authority; passing already-expanded CRLF through default Windows text I/O can create
CRCRLF. The renderer has no target discovery, file writes or installation action.
It rejects lone CR/CRCRLF rather than silently repairing uncertain input.

`tests/test_codex_config.py` covers LF/CRLF input, UTF-8 with/without BOM, Unicode,
multiline values containing apparent table headers, complete parsed settings,
unrelated settings, byte-exact line endings and rejected malformed input. Fixture
outputs remain disposable. A reproduced hazardous byte pattern does not establish
which historical tool changed a user's settings; preserve evidence before attributing
cause. Frozen historical acceptance scripts stay frozen, rather than being reused as
current publication utilities.

## Changes and source packages

Keep extraction in shared services and provenance in every exported record. Update
the README, implementation docs and repeatable checks with public behavior. Keep
customer data, machine paths, runtime state and acceptance evidence ignored.

Use `scripts/release_version.py` for an explicit chosen release timestamp and
`scripts/generate_skill.py --check` for the skill bootstrap. Build with
`scripts/package.py --output ABSOLUTE_PRIVATE_ZIP_PATH`; its allowlist includes the
license and byte manifest and excludes `.local/` and dependencies. Verify the ZIP,
extract it into a fresh directory and run `scripts/package.py --verify`. Source and
package passes leave installed/native acceptance separate.
