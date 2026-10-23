import copy
import tomllib

import pytest

from scripts.codex_config import render_toml

FIXTURE = '''# Keep unrelated preferences and Unicode.
model = "fixture-model"
instructions = """Inspection 線
[mcp_servers.this_is_multiline_text]
Keep this line and its café label.
"""
[features]
example = true
[projects.'C:\\Engineering Drawings\\線']
trust_level = "trusted"
[mcp_servers.other]
command = 'C:\\Other App\\server.exe'
args = ["--label", "électricité"]
[plugins."autocad@autocad-local"]
enabled = true
'''


@pytest.mark.parametrize("input_newline", ["\n", "\r\n"])
@pytest.mark.parametrize("output_newline", ["\n", "\r\n"])
@pytest.mark.parametrize("bom", [False, True])
def test_reviewed_toml_bytes_preserve_unrelated_settings(tmp_path, input_newline, output_newline, bom):
    source = tmp_path / "config.toml"
    original = ("\ufeff" if bom else "") + FIXTURE.replace("\n", input_newline)
    source.write_bytes(original.encode("utf-8"))
    before = tomllib.loads(source.read_bytes().decode("utf-8-sig"))
    expected = copy.deepcopy(before)
    expected["mcp_servers"]["autocad"] = {"command": "C:\\App & Files\\python.exe", "enabled": True}
    # Match private publication's raw UTF-8 decode plus appended LF text.
    changed = source.read_bytes().decode("utf-8-sig") + (
        '\n[mcp_servers.autocad]\ncommand = "C:\\\\App & Files\\\\python.exe"\nenabled = true\n'
    )
    rendered = render_toml(changed, expected=expected, newline=output_newline)
    candidate = tmp_path / "reviewed-candidate.toml"
    candidate.write_bytes(rendered)
    assert source.read_bytes() == original.encode("utf-8")
    assert candidate.read_bytes() == changed.removeprefix("\ufeff").replace("\r\n", "\n").replace(
        "\n", output_newline
    ).encode("utf-8")
    assert b"\r\r\n" not in rendered
    assert b"\r" not in rendered.replace(b"\r\n", b"")
    if output_newline == "\r\n":
        assert b"\n" not in rendered.replace(b"\r\n", b"")
    after = tomllib.loads(candidate.read_bytes().decode("utf-8"))
    assert after == expected
    after["mcp_servers"].pop("autocad")
    assert after == before


@pytest.mark.parametrize("bad", ["\r", "\r\r\n"])
def test_malformed_carriage_returns_are_rejected_without_a_write(tmp_path, bad):
    path = tmp_path / "config.toml"
    raw = f'model = "unchanged"{bad}'.encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="lone CR or CRCRLF"):
        render_toml(raw.decode(), expected={"model": "unchanged"})
    assert path.read_bytes() == raw


def test_unexpected_settings_change_or_invalid_toml_is_rejected():
    with pytest.raises(ValueError, match="complete expected settings"):
        render_toml('model = "changed"\n', expected={"model": "original"})
    with pytest.raises(tomllib.TOMLDecodeError):
        render_toml('model = "unterminated', expected={})
    with pytest.raises(ValueError, match="Select LF or CRLF"):
        render_toml("", expected={}, newline="\r")


def test_setting_types_and_nan_are_preserved():
    with pytest.raises(ValueError, match="complete expected settings"):
        render_toml("enabled = 1\n", expected={"enabled": True})
    text = "unchanged = nan\n"
    assert render_toml(text, expected=tomllib.loads(text)) == b"unchanged = nan\r\n"
