"""The released standalone profile has no native engineering execution route."""

import os

PROFILE = "offline"
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


def validate_profile(profile="offline", oda_executable=None):
    if profile != PROFILE or os.environ.get("AUTOCAD_MCP_EXECUTION_PROFILE", PROFILE) != PROFILE:
        raise ValueError("Only execution_profile='offline' is supported by this release")
    if oda_executable not in (None, ""):
        raise ValueError(NATIVE_BLOCKER + "; oda_executable must be unset")


def require_native(operation):
    # Deliberately no config, environment, CLI or request flag can open this gate.
    raise ValueError(NATIVE_BLOCKER + ": " + operation)
