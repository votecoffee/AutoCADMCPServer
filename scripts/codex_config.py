"""Render reviewed UTF-8 TOML bytes; no configuration discovery or file writes."""

from __future__ import annotations

import math
import tomllib
from collections.abc import Mapping


def _same_settings(actual, expected):
    if isinstance(actual, dict) and isinstance(expected, Mapping):
        return actual.keys() == expected.keys() and all(
            _same_settings(value, expected[key]) for key, value in actual.items()
        )
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(map(_same_settings, actual, expected))
    return type(actual) is type(expected) and (
        actual == expected or (isinstance(actual, float) and math.isnan(actual) and math.isnan(expected))
    )


def render_toml(text: str, *, expected: Mapping, newline: str = "\r\n") -> bytes:
    """Normalize once, validate settings, then encode without text-mode translation.

    The caller supplies the complete expected parsed settings, including unrelated
    settings. Windows publication uses the default explicit CRLF; LF is available
    for other consumers. Reject malformed carriage returns instead of guessing a
    repair. This function does not select or modify a user's config.toml.
    """
    if newline not in {"\n", "\r\n"}:
        raise ValueError("Select LF or CRLF explicitly")
    normalized = text.removeprefix("\ufeff").replace("\r\n", "\n")
    if "\r" in normalized:
        raise ValueError("TOML contains a lone CR or CRCRLF; preserve it for review")
    data = normalized.replace("\n", newline).encode("utf-8")
    if not _same_settings(tomllib.loads(data.decode("utf-8")), expected):
        raise ValueError("Rendered TOML differs from the complete expected settings")
    return data
