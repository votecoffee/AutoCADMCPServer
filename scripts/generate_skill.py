"""Generate/check the stable packaged entrypoint from app-owned bootstrap instructions."""

import argparse
from pathlib import Path

from autocad_mcp.workflow_guidance import bootstrap_bytes

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--check", action="store_true")
args = parser.parse_args()
target = Path(__file__).resolve().parents[1] / "plugins/autocad/skills/drawing-analysis/SKILL.md"
if args.check:
    if target.read_bytes() != bootstrap_bytes():
        raise SystemExit("Regenerate the packaged skill with scripts/generate_skill.py")
else:
    target.write_bytes(bootstrap_bytes())
