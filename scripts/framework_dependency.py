"""Verify the pinned local framework wheel before normal dependency installation."""

import base64
import csv
import hashlib
import io
import shutil
import zipfile
from email.parser import Parser
from pathlib import Path

VERSION = "0.14.0"
FILENAME = "universal_codex_tools-0.14.0-py3-none-any.whl"
SHA256 = "3063dac969222d54d5babf316c1da61c46cb9443a0a7f202694bbe5b1acaea1d"


def verify(wheel: Path) -> dict:
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != SHA256:
        raise ValueError("Framework wheel SHA-256 differs from the tested artifact")
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        record = next(n for n in names if n.endswith(".dist-info/RECORD"))
        rows = list(csv.reader(io.StringIO(archive.read(record).decode())))
        if archive.testzip() or {n for n, _, _ in rows} != set(names):
            raise ValueError("Invalid framework wheel inventory")
        for name, digest, size in rows:
            if not digest:
                if name != record:
                    raise ValueError("Unhashed framework wheel member")
                continue
            algorithm, expected = digest.split("=", 1)
            data = archive.read(name)
            actual = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
            if algorithm != "sha256" or actual != expected or len(data) != int(size):
                raise ValueError("Framework wheel RECORD verification failed")
        metadata = Parser().parsestr(
            archive.read(next(n for n in names if n.endswith(".dist-info/METADATA"))).decode()
        )
        if metadata["Name"].replace("_", "-") != "universal-codex-tools" or metadata["Version"] != VERSION:
            raise ValueError("Unexpected framework package identity")
        if "mcp==2.3.0" not in (metadata.get_all("Requires-Dist") or []):
            raise ValueError(
                "A verified MCP SDK 2.3.0 framework build is required; SDK downgrade is prohibited"
            )
        if "universal_tools/framework.py" not in names or not any("LICENSE" in n for n in names):
            raise ValueError("Framework API or license is missing")
    return {"version": VERSION, "sha256": SHA256, "record_verified": True}


def stage(repo: Path, supplied: str | None = None) -> Path:
    target = repo / ".local/wheels" / FILENAME
    candidate = Path(supplied).resolve(strict=True) if supplied else target
    if not candidate.is_file():
        raise ValueError(
            "No public framework feed is shipped. Supply --framework-wheel PATH to the verified SDK 2.3 framework wheel"
        )
    verify(candidate)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        verify(target)
    if candidate != target.resolve():
        shutil.copyfile(candidate, target)
    return target.parent


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    print(json.dumps(verify(parser.parse_args().wheel)))
