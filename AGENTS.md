# Repository guidance

- Preserve source drawings. Extraction and rendering operate on isolated copies; never save into source roots.
- Keep customer drawings, paths, extracted content, evidence and runtime state under ignored `.local/` or outside the checkout. Never package them in source distributions.
- Keep extraction in the shared Python service layer used by CLI and MCP. Tool inputs cannot supply executables, shell commands or arbitrary output paths.
- Distinguish ODA-converted structural extraction from native AutoCAD validation. Surface unsupported objects, unresolved references, scan-only pages and incomplete indexes.
- Run synthetic tests plus the MCP protocol smoke test for changes to extraction or transport. Do not push without explicit authorization.
- Work on `main` and make focused local commits after relevant checks pass. The repository owner handles pushes.
- Keep the root README current using the Standard Readme structure. Include repeatable checks in `VERIFICATION.md`; put installation-specific notes and acceptance evidence under ignored `.local/private-docs/` or outside the checkout.
- Include the repository license and byte manifest in source packages. Preserve LF line endings so Git, checkout and packaged hashes agree.
