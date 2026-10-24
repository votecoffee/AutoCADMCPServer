import os
from pathlib import Path

import pytest

from autocad_mcp import process_identity
from autocad_mcp.owned_process import StreamProcessDriver
from scripts.stable_install import default_home


def test_alias_equivalence_requires_the_complete_generation(monkeypatch):
    observed = {"host_id": "a" * 64, "pid": 100, "created": "123", "executable": "physical"}
    alias = {**observed, "executable": "logical-msix"}
    monkeypatch.setattr(
        process_identity,
        "canonical_image_path",
        lambda path: "same-file" if path in {"physical", "logical-msix"} else "other-file",
    )
    assert process_identity.same_generation(observed, alias)
    assert not process_identity.same_generation(observed, {**alias, "created": "124"})
    assert not process_identity.same_generation(observed, {**alias, "pid": 101})
    assert not process_identity.same_generation(observed, {**alias, "host_id": "b" * 64})
    assert not process_identity.same_generation(observed, {**alias, "executable": "foreign"})


@pytest.mark.skipif(os.name != "nt", reason="Windows physical image/known-folder APIs")
def test_actual_serving_image_and_unredirected_install_root():
    driver = StreamProcessDriver()
    captured = driver.capture(os.getpid())
    assert driver.state(captured) == "alive"
    assert captured["executable"] == process_identity.canonical_image_path(captured["executable"])
    assert default_home() == Path.home() / "Applications" / "AutoCADMCPServer"
