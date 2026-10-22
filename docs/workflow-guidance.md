# Current guidance and Skills-over-MCP

AutoCAD 0.6 keeps its own focused `drawing-analysis` packaged skill as a stable bootstrap. Its name, description and scope belong to AutoCAD's independent Codex plugin. There is no universal plugin or aggregate Codex connection. `guidance.py` is the canonical detailed source. `workflow_guidance.py` renders that source into an overview, topic references, metadata and a complete MCP skill manifest; no separately maintained procedural copy is shipped.

## Ordinary readers

Every direct server and `drawing-engine` backend exposes `cad_get_workflow` and `cad_get_workflow_reference`. The guide returns app/workflow identity, app version, workflow revision, overview SHA-256 and a reference catalog. Reference reads require the exact reference ID, guide revision and SHA-256. Unknown references, stale revisions and changed bytes are rejected. Recovery, Electrical interpretation and operational details remain in references derived from the same canonical text. These reads do not authorize writes or open drawings.

Through the fixed app front door, search and describe `drawing-engine`, describe the guide/reference tools and invoke them through `call_read_tool` with the current tool catalog revision. Direct clients call the native readers. Keep the selected route and separate app/host operation IDs. The bootstrap requires these reads before detailed work; it does not depend on native host loading of MCP skills.

## Protocol profiles

| Profile | Native skill/resource methods | Ordinary readers |
| --- | --- | --- |
| Direct standalone stdio or loopback server | `io.modelcontextprotocol/skills`, real list/get and resource reads | Native `cad_*` readers |
| App-owned authenticated HTTP host | Generated local skill catalog plus scoped artifacts | Fixed fourteen tools route to `drawing-engine` |
| Fixed app-owned stdio proxy | Not advertised: the generic proxy does not forward skill/resource methods | Guide/reference and bounded artifact reads remain available through the selected front door |

Each real catalog serves `SKILL.md`, `workflow.json` and three supporting references under `skill://drawing-analysis/`. Manifest byte sizes and SHA-256 values match the ordinary readers. Directory reads and downstream skill federation are not enabled. Resources are immutable snapshots, never arbitrary contributed Python or scripts. Loading instructions does not execute code or grant approval.

## Publication and reload

The app-local `Guidance.publish(text, expected_revision=catalog.revision)` API stages and validates a complete candidate before `SkillCatalog.publish`. It is not an MCP mutation tool. A malformed candidate or stale publication revision preserves the prior catalog; removal/re-addition keeps the extension identity fixed. Readers derive their data from the published immutable resource map, so ordinary and protocol views advance together. Existing native tool definitions and initialization bootstrap stay unchanged across a successful guide-only publication. Resource-list notifications are hints; reconnecting clients refetch the current manifest and verify its hashes.

Editing a source file does not update a running worker. For app-owned backend changes, quiesce and reconcile receipts/jobs, run `framework-prepare`, then use the same connected frontend's `refresh_services`. Preparation includes generated guidance data in the complete immutable deployment inventory. Successful backend selection publishes the matching data to the host catalog; rejected/deferred replacement keeps the previous guidance. Retained adapters also require explicit guarded app-admin retirement before replacement. No automatic retirement, replay, route switching or uncertainty acknowledgment is added.

The packaged bootstrap is generated with `python scripts/generate_skill.py`; `--check` verifies its bytes. Packaged skill/plugin metadata, native tool schemas, runtime and startup instruction changes still require installation/reconnection. OpenAI currently imports MCP skills as plugin-submission snapshots and does not fetch them through the native ChatGPT/Codex skill loader at runtime. Protocol publication therefore does not establish live native skill activation or eliminate metadata reloads. See [official OpenAI documentation](https://developers.openai.com/plugins/build/skills#import-a-skill-from-mcp) and the [SDK skills contract](https://py.sdk.modelcontextprotocol.io/advanced/skills/).

## Verification

`tests/test_workflow_guidance.py` checks connected list/get/resource manifests, reference parity, stale pins, failed publication, removal/re-addition and fixed tool definitions. It also checks private discovery cache hits, resource-event invalidation and independent clients/reconnection. Framework fixtures compare the host's published resource data against its current worker readers after an explicit refresh. Protocol evidence remains separate from Codex selection, host UI and native AutoCAD acceptance.
