"""Create private application configuration while preserving existing roots."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", required=True, help="name=absolute directory (repeatable)")
    parser.add_argument("--oda", help="Unavailable in the standalone offline profile")
    args = parser.parse_args()
    if args.oda:
        parser.error("ODA configuration is unavailable in the standalone offline profile")
    repo = Path(__file__).resolve().parents[1]
    local = repo / ".local"
    local.mkdir(exist_ok=True)
    config_path = local / "config.json"
    if config_path.exists():
        raise SystemExit("Existing configuration preserved; edit .local/config.json explicitly")
    roots = {}
    for value in args.root:
        key, directory = value.split("=", 1)
        if key in roots:
            raise ValueError("Duplicate root name")
        roots[key] = str(Path(directory).resolve(strict=True))
    config = {"roots": roots, "state_dir": str(local / "state"), "execution_profile": "offline"}
    from autocad_mcp.config import Config

    temporary = local / "config.pending.json"
    temporary.write_text(json.dumps(config, indent=2), encoding="utf-8")
    Config.load(temporary)
    temporary.replace(config_path)
    print(json.dumps({"config": str(config_path)}))


if __name__ == "__main__":
    main()
