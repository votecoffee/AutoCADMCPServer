"""Explicit operator profiles; environment or request flags cannot enable native work."""

import os
import re

PROFILE = "offline"
ODA_PROFILE = "oda-read"
NATIVE_BLOCKER = "Native engineering operations are unavailable in the standalone offline profile"
NUMERICAL_ENVIRONMENT = {
    name: "1"
    for name in (
        "OPENBLAS_NUM_THREADS",
        "GOTO_NUM_THREADS",
        "OMP_NUM_THREADS",
        "OMP_THREAD_LIMIT",
        "MKL_NUM_THREADS",
        "BLIS_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )
}


def configure_runtime():
    """Bound native numerical pools before ezdxf/NumPy imports in every app entrypoint."""
    os.environ.update(NUMERICAL_ENVIRONMENT)


def validate_profile(profile=PROFILE, oda_executable=None, oda_sha256=None):
    if profile not in (PROFILE, ODA_PROFILE):
        raise ValueError("Only execution_profile='offline' or 'oda-read' is supported")
    if os.environ.get("AUTOCAD_MCP_EXECUTION_PROFILE", profile) != profile:
        raise ValueError("Execution profile differs from AUTOCAD_MCP_EXECUTION_PROFILE")
    if profile == PROFILE:
        if oda_executable not in (None, "") or oda_sha256 not in (None, ""):
            raise ValueError(NATIVE_BLOCKER + "; oda_executable must be unset")
    elif (
        not oda_executable or not isinstance(oda_sha256, str) or not re.fullmatch("[0-9a-f]{64}", oda_sha256)
    ):
        raise ValueError("oda-read requires an absolute oda_executable and lowercase oda_sha256 pin")


def require_native(operation):
    # AutoCAD COM remains separate from the contained, read-only ODA adapter.
    raise ValueError(NATIVE_BLOCKER + ": " + operation)
