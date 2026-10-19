"""Read-only corpus acceptance, with private extraction evidence and before/after source hashes."""

import argparse
import collections
import json
import time
from pathlib import Path

from autocad_mcp.config import Config
from autocad_mcp.service import DrawingService, sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=".local/config.json")
    parser.add_argument("--output", default=".local/validation/corpus.json")
    parser.add_argument("--query", default="PART", help="Literal query for the search coverage check")
    args = parser.parse_args()
    service = DrawingService(Config.load(args.config))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    sources = {root: service.config.files(root) for root in service.config.roots}
    before = {
        root: {
            row["relative_path"]: sha256(service.config.resolve(root, row["relative_path"]))
            for row in rows
            if row["size_bytes"] <= service.config.max_file_bytes
        }
        for root, rows in sources.items()
    }
    report = {"started_at_unix": start, "extraction_signature": service.signature, "projects": {}}
    for root, rows in sources.items():
        supported = [row for row in rows if row["supported"]]
        project = {
            "inventory_files": len(rows),
            "inventory_bytes": sum(row["size_bytes"] for row in rows),
            "extensions": dict(collections.Counter(row["extension"] for row in rows)),
            "supported_files": len(supported),
            "files": [],
        }
        report["projects"][root] = project
        for offset, file in enumerate(supported):
            begin = time.time()
            result = service.index(root, offset, 1)["results"][0]
            if result["status"] == "indexed":
                result["inspection"] = service.inspect(root, file["relative_path"])
            result["seconds"] = round(time.time() - begin, 3)
            project["files"].append(result)
            print(
                f"{root} {offset + 1}/{len(supported)} {result['status']}: {file['relative_path']}",
                flush=True,
            )
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        project["search_check"] = service.search(root, args.query, limit=5)
    changed, checked = [], 0
    for root, paths in before.items():
        for relative, digest in paths.items():
            checked += 1
            if sha256(service.config.resolve(root, relative)) != digest:
                changed.append({"root": root, "path": relative})
    report["source_preservation"] = {
        "hashed_files": checked,
        "changed_files": changed,
        "before_sha256": before,
        "excluded_oversize_files": sum(len(sources[r]) - len(before[r]) for r in sources),
    }
    report["seconds"] = round(time.time() - start, 3)
    report["passed"] = not changed and all(
        file["status"] == "indexed" for project in report["projects"].values() for file in project["files"]
    )
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "seconds": report["seconds"],
                "source_files_hashed": checked,
                "changed_files": len(changed),
                "report": str(output),
            }
        )
    )
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
