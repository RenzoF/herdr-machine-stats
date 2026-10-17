"""The plugin stays flake8-clean at 79 columns.

flake8 on a directory skips extensionless files, so bin/machine-stats is named
explicitly. Without flake8 for this interpreter the guard skips loudly.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("path", ["bin/machine-stats", "statslib", "tests"])
def test_flake8_clean(path):
    if not importlib.util.find_spec("flake8"):
        pytest.skip("flake8 is not installed for this interpreter")
    done = subprocess.run(
        [sys.executable, "-m", "flake8", str(PLUGIN / path)],
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stdout + done.stderr
