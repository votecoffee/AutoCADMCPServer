"""Explicit source allowlist, byte manifest and ZIP verification; never traverses private state."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT_FILES = (
    ".gitattributes",
    "README.md",
    "VERIFICATION.md",
    "AGENTS.md",
    ".gitignore",
    "LICENSE",
    "pyproject.toml",
    "requirements-lock.txt",
    "requirements-dev-lock.txt",
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def selected_files(repo):
    files = [repo / name for name in ROOT_FILES]
    for folder in ("src", "scripts", "tests"):
        files.extend((repo / folder).rglob("*.py"))
    files.append(repo / "examples/config.example.json")
    return sorted(files, key=lambda path: path.relative_to(repo).as_posix())


def verify(repo):
    manifest = json.loads((repo / "manifest.json").read_text(encoding="utf-8"))
    expected = set(manifest["files"])
    actual = {path.relative_to(repo).as_posix() for path in selected_files(repo)}
    if actual != expected:
        raise ValueError("Manifest file set differs from source allowlist")
    for name, info in manifest["files"].items():
        data = (repo / name).read_bytes()
        if digest(data) != info["sha256"] or len(data) != info["bytes"]:
            raise ValueError(f"Manifest byte mismatch: {name}")
    return {"verified_files": len(expected), "passed": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    if args.verify:
        print(json.dumps(verify(repo)))
        return
    if not args.output:
        parser.error("--output is required when packaging")
    files = selected_files(repo)
    manifest = {
        "schema_version": 1,
        "version": "0.1.0",
        "files": {
            path.relative_to(repo).as_posix(): {
                "sha256": digest(path.read_bytes()),
                "bytes": path.stat().st_size,
            }
            for path in files
        },
    }
    manifest_path = repo / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files + [manifest_path]:
            archive.write(path, "AutoCADMCPServer/" + path.relative_to(repo).as_posix())
    with zipfile.ZipFile(target) as archive:
        expected = {"AutoCADMCPServer/" + p.relative_to(repo).as_posix() for p in files + [manifest_path]}
        if set(archive.namelist()) != expected or archive.testzip():
            raise ValueError("ZIP contents failed verification")
        for path in files + [manifest_path]:
            name = "AutoCADMCPServer/" + path.relative_to(repo).as_posix()
            if archive.read(name) != path.read_bytes():
                raise ValueError(f"ZIP byte mismatch: {name}")
    print(
        json.dumps(
            {
                "zip": str(target),
                "sha256": digest(target.read_bytes()),
                "files": len(files) + 1,
                **verify(repo),
            }
        )
    )


if __name__ == "__main__":
    main()
