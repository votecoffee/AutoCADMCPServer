"""Keep nested workers on the selected immutable app backend publication."""

import sys
from pathlib import Path

_deployment: tuple[Path, str, bool] | None = None


def bind_deployment(root: Path, digest: str, *, stable=False):
    global _deployment
    _deployment = (root, digest, stable)


def worker_command(operation: str, *arguments: str) -> list[str]:
    if operation not in {"_extract", "_render", "_tables", "_highlight"}:
        raise ValueError("Unknown app worker operation")
    if _deployment is not None:
        root, digest, stable = _deployment
        flags = ["-I", "-S", "-B", "-X", "utf8"] if stable else ["-I"]
        return [sys.executable, *flags, str(root / "worker.py"), digest, operation, *arguments]
    return [sys.executable, "-m", "autocad_mcp", operation, *arguments]
