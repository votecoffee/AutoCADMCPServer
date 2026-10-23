import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows root CMD contract")


@pytest.fixture
def cmd_fixture(tmp_path):
    source = Path(__file__).resolve().parents[1]
    app = tmp_path / "application & files with spaces"
    (app / "scripts").mkdir(parents=True)
    shutil.copyfile(source / "InstallAndRun.cmd", app / "InstallAndRun.cmd")
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(app / ".venv")], check=True)
    return source, app


def invoke(app, arguments):
    # A complete CMD command string avoids subprocess's MSVCRT quoting rules for /c.
    # Values below are fixed fixtures; deliberately include quoted spaces and '&'.
    comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
    command = f'"{comspec}" /d /s /c ""{app / "InstallAndRun.cmd"}" {arguments}"'
    return subprocess.run(command, cwd=app.parent, text=True, capture_output=True, timeout=30)


def test_root_cmd_help_and_argument_error_do_not_install(cmd_fixture):
    source, app = cmd_fixture
    shutil.copyfile(source / "scripts/launcher.py", app / "scripts/launcher.py")
    help_result = invoke(app, "--help")
    assert help_result.returncode == 0, help_result.stderr
    assert "--install-only" in help_result.stdout and "--codex-integration" in help_result.stdout
    invalid = invoke(app, "--port 0")
    assert invalid.returncode == 2, invalid.stderr
    assert "--port must be 1..65535" in invalid.stderr
    assert not (app / ".local").exists()


def test_root_cmd_forwards_quoted_paths_cwd_and_failure_code(cmd_fixture):
    _, app = cmd_fixture
    (app / "scripts/launcher.py").write_text(
        "import json,os,sys\nprint(json.dumps({'args':sys.argv[1:],'cwd':os.getcwd()}))\nsys.exit(23)\n",
        encoding="utf-8",
        newline="\n",
    )
    result = invoke(
        app,
        '--root "drawings=C:\\Drawing & reference files" --framework-wheel "C:\\Package files\\verified.whl" --install-only',
    )
    assert result.returncode == 23, result.stderr
    value = json.loads(result.stdout)
    assert value == {
        "args": [
            "--root",
            r"drawings=C:\Drawing & reference files",
            "--framework-wheel",
            r"C:\Package files\verified.whl",
            "--install-only",
        ],
        "cwd": str(app),
    }
    assert not (app / ".local").exists()
