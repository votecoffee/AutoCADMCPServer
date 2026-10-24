# App-owned stable launcher

Published standalone connections use a dedicated installed root outside the checkout,
build outputs and Codex plugin caches. The Windows adoption installer currently requires
reviewed CPython 3.13.9 and `uv` for a fresh dependency install/build. A retained reviewed
wheel and runtime seed support offline adoption. The general source package still supports
Python 3.11 and later. Framework 0.20.0 and MCP/MCP-types 2.3.0 remain independently pinned.

```text
Installation root/
  Python/                         actual interpreter, DLLs and standard library
  python-manifest.json            exact bootstrap inventory
  StartMcp.py                     stable in-process entry
  libraries/<sha256>/             immutable locked dependencies and inventory
  configurations/<sha256>.json    exact reviewed offline configuration
  launcher/current.json           atomic selection, no directory discovery
  launcher/snapshots/<sha256>/    app wheel payload, pinned worker, launch inventory
  launcher/backups/               exact previous selection bytes
  codex-marketplace/              standalone package and native skill
```

The installed command invokes `Python/python.exe -I -S -B -u -X utf8 StartMcp.py`
with the installation root as cwd. It verifies the selected inventories, configuration,
dependency identities and app version before serving in the same process. Launch never
downloads packages, updates itself, selects the newest directory or falls back to another
profile. Missing, malformed, reparse, hard-linked records and changed payloads refuse startup.
The initial interpreter/entry are trusted installed bootstrap bytes; this is local integrity
checking, not a cryptographic secure-boot claim.

Each process retains its selected generation. Nested extraction workers use that generation's
immutable `worker.py`, even after an atomic pointer update. Updates compare the expected
selection hash, preflight with the actual installed interpreter, retain the old selection
bytes, publish by atomic replace and verify readback. They never delete old generations.
Source `scripts/stable_install.py` exposes explicit staging/publication for administrators;
the root CMD provides ordinary install/run handling. `--check` verifies the selected runtime
without starting MCP or native software.

The actual serving supervisor owns worker Job Objects and durable resource claims. The
existing original-input-pipe duplication and independent parent watcher remain in effect.
Startup verification retains the original parent and pipe before SDK descriptor diversion.
Numerical pools remain limited to one thread. Admission limits are unchanged; a new process
can refuse while older live peers hold the configured slots. Installation does not terminate
those peers or raise limits.

Startup reconciles only recognizable private worker claims with exact dead owner/root/member
identities and an absent or empty private named job. Reconciliation changes metadata only;
it never stops a process, replays work, resets journals or clears uncertainty. Unknown, live,
attached/shared, incomplete, recovery-barrier and uncertain records remain protected.
Windows executable identity resolves the physical image through a file handle, allowing
logical MSIX aliases only when host, PID and creation time also match.

Management reports running and selected versions separately. A selected pointer is not
runtime health. Native activation, current-chat tool discovery and a new installed connection
are separate acceptance layers. This stable adoption is offline only; ODA/native acceptance
is not implied.

## Registration and legacy migration

The standalone plugin and skill remain app-owned. Published bindings use the stable command
and cwd. Development-only `install_plugin.py --prepare-only` output is explicitly unpublished
unless `--stable-home` is supplied; registration requires it. A legacy saved route must be
migrated before plugin registration can prune a referenced cache. The installer retains
exact settings and positively identified AutoCAD cache payloads and defers registration.
It never edits immutable cached files.

`--prepare-plugin --codex-integration none` prepares a stable package without host writes.
`scripts/stable_binding.py::propose` creates an exact settings backup, expected configuration
hash, existing route and proposed route for a serialized publisher. It does not write live
settings. The publisher must preserve BOM, comments, Unicode, newline convention and unrelated
settings, detect intervening edits and atomically write validated binary TOML bytes. Never
restore an old whole-file backup over another application's settings.

Actual acceptance uses synthetic drawings, real initialization/catalog/guidance/read calls,
authenticated management snapshots and EOF receipts, plus disposable cache removal,
tamper/missing refusal, active-peer updates, admission and owner/parent loss. Preserve
the previous installation and journals until the replacement route and host discovery are
verified. Direct SDK evidence does not prove activation inside an already-open Codex chat.
