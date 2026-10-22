"""The released standalone profile has no native engineering execution route."""

import os

PROFILE = "offline"
NATIVE_BLOCKER = "Native engineering operations are unavailable in the standalone offline profile"


def validate_profile(profile="offline", oda_executable=None):
    if profile != PROFILE or os.environ.get("AUTOCAD_MCP_EXECUTION_PROFILE", PROFILE) != PROFILE:
        raise ValueError("Only execution_profile='offline' is supported by this release")
    if oda_executable not in (None, ""):
        raise ValueError(NATIVE_BLOCKER + "; oda_executable must be unset")


def require_native(operation):
    # Deliberately no config, environment, CLI or request flag can open this gate.
    raise ValueError(NATIVE_BLOCKER + ": " + operation)
