"""Exercise the Windows launcher without a preinstalled source package."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name != "nt", reason="The .bat launcher is Windows-specific")
def test_launcher_installs_own_package_before_opening_menu(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    checkout = tmp_path / "fresh checkout"
    checkout.mkdir()
    for name in ("run.bat", "pyproject.toml", "requirements.txt", "README.md", "LICENSE",
                 "main.py", "parser.py", "utils.py", "fetch_ids.py", "show_seller.py"):
        shutil.copy2(repo / name, checkout / name)
    shutil.copytree(repo / "src", checkout / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))

    # Reuse installed third-party dependencies while hiding the original editable checkout.
    # The launcher's own package installation must still happen in the fresh venv.
    created = subprocess.run(
        [sys.executable, "-u", "-m", "venv", "--system-site-packages", str(checkout / ".venv")],
        capture_output=True, text=True, timeout=45,
    )
    assert created.returncode == 0, created.stdout + created.stderr
    hook_dir = tmp_path / "import_hooks"
    hook_dir.mkdir()
    (hook_dir / "sitecustomize.py").write_text(
        "from pathlib import Path\nimport os, sys\n"
        "hidden = Path(os.environ['HIDDEN_CHECKOUT_SOURCE']).resolve()\n"
        "sys.path[:] = [p for p in sys.path if Path(p).resolve() != hidden]\n",
        encoding="utf-8",
    )
    env = {
        **os.environ, "PYTHONPATH": str(hook_dir), "PYTHONUTF8": "1",
        "HIDDEN_CHECKOUT_SOURCE": str(repo / "src"), "PIP_NO_INDEX": "1",
        "PIP_NO_BUILD_ISOLATION": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    }
    result = subprocess.run(
        ["cmd", "/d", "/c", str(checkout / "run.bat")], cwd=tmp_path,
        env=env, input="0\n\n", capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    installed = subprocess.run(
        [str(checkout / ".venv" / "Scripts" / "python.exe"), "-u", "-c",
         "from pathlib import Path; import funpay_analytics; print(Path(funpay_analytics.__file__).resolve())"],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert str(checkout / "src") in installed.stdout
    assert "═══" in result.stdout
