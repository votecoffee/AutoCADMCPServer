# Release versions

Application releases use one fixed `YY.MMDD.HHmmss` timestamp in `America/New_York`, including daylight saving time. Choose it once for a source/release checkpoint. Runtime startup, installation and verification reuse that identity and never read a clock to create another version. `src/autocad_mcp/version.py` holds the padded display stamp and derives the canonical package version.

Python PEP 440 normalizes numeric components, and strict SemVer prohibits leading zeros in them. Package, plugin loader, MCP server-info and manager component identities therefore use three unpadded integers. For example, display `26.0101.010203` maps to canonical `26.101.10203`; midnight `26.0101.000000` maps to `26.101.0`. The conversion is reversible for the years 2000 through 2099. Compare numeric components or parsed package versions, never version strings lexically. Date/time validation rejects invalid stamps.

The `autocad-mcp --version` command, app status and capability records, workflow and deployment metadata, source archive manifest, installer output and manager message also expose the padded display version. Both plugin manifests use the canonical version. Generated plugin packages include it in their immutable cache directory name alongside the content digest, and bindings identify both canonical and display versions. The shared framework and MCP SDK retain their own independently reviewed versions and pins.

For an explicitly chosen release timestamp, run:

```powershell
python scripts/release_version.py --set YY.MMDD.HHmmss
python scripts/release_version.py
```

The setter accepts a padded timestamp supplied by the maintainer; it never generates one. It updates the app stamp, Python project version and both plugin manifests. Update current release documentation, regenerate source packages and verify built wheel metadata/imports. `scripts/package.py` and the installer reject identity drift. Keep historical evidence/artifacts intact and any installation-specific old-to-new mapping outside public Git.

Run `tests/test_version.py` for early-morning, midnight, January, leap-date, year-boundary, ordering and loader-manifest checks. Build a wheel and inspect its distribution metadata and isolated import before release. Plugin preparation tests check the exact generated files without registering or starting a plugin. Actual MCP initialization, installed plugin activation and native engineering acceptance remain separate checks subject to the operator's runtime authorization. This application has no .NET assembly version.
