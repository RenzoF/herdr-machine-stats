import stat
import sys
from pathlib import Path

import pytest

# The fleet plugin root, so tests import fleetlib as bin/fleet does.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def outside_herdr(monkeypatch):
    """Keep the suite away from any Herdr session that may be running it."""
    monkeypatch.delenv("HERDR_ENV", raising=False)
    monkeypatch.setenv("HERDR_BIN", "/nonexistent/herdr")


@pytest.fixture
def fake_herdr(tmp_path_factory):
    """A herdr shim that records argv lines and replays canned output.

    Returns (bin_path, calls_file, canned_dir). A `<canned_dir>/<cmd>-<sub>`
    file (for example `agent-list`) is printed for that subcommand pair;
    anything else prints `{"result":{}}`.
    """
    d = tmp_path_factory.mktemp("fakeherdr")
    calls = d / "calls.log"
    canned = d / "canned"
    canned.mkdir()
    shim = d / "herdr"
    shim.write_text(
        "#!/bin/bash\n"
        f'echo "$@" >> "{calls}"\n'
        f'f="{canned}/$1-$2"\n'
        'if [ -f "$f" ]; then cat "$f"; else echo \'{"result":{}}\'; fi\n'
        "exit 0\n"
    )
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    return shim, calls, canned
