"""AutoCAD MCP Server: local drawing intelligence."""

from .profile import configure_runtime
from .version import DISPLAY_VERSION as __display_version__
from .version import PACKAGE_VERSION as __version__

__all__ = ["EXTRACTION_VERSION", "__display_version__", "__version__"]

configure_runtime()
EXTRACTION_VERSION = "1"
