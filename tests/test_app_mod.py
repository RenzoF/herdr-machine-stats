"""The Herdr app mod in app-mod/: its Node tests and ``herdr-app check``.

The Node suite (tests/js) tests the mod's logic with fake exec and hc.
``herdr-app check`` loads the mod and renders it once in a hidden window;
a seeded copy also renders full cards, a down card and the btop title bar,
which the real mod only draws after its first reads. Checks run with a
scratch app home and HC_SESSION, so they never reach the live core.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / "app-mod"
SESSION = "machine-stats-test"

SEEDED = """\
import MachineStats from "./real-main.js";

const SNAP = {
  os: "Linux", host: "omarchy", ncpu: 4, load: 7.1, cpuPct: 79,
  memPct: 91, memUsedKb: 14000000, memTotalKb: 16000000,
  diskPct: 38, diskUsedKb: 115552376, diskTotalKb: 312458220,
};

export default class Seeded extends MachineStats {
  init(props, cx) {
    super.init(props, cx);
    this.width = 900;
    this.reads.set("", { snapshot: SNAP, history: [5, 40, 70, 95],
      at: Date.now() });
    this.reads.set("agent-desk", { snapshot: null, error: "timeout",
      at: Date.now(), history: [] });
  }
  // No reads: exec on another machine would start a core for HC_SESSION.
  poll() {}
  list() {
    return [{ name: null, layout: "ready" },
      { name: "agent-desk", layout: "ready" },
      { name: "lenovo", layout: "unavailable" }];
  }
  agentData() {
    const blocked = [1, 2, 3, 4].map((i) => (
      { address: `t${i}`, label: `space ${i} · tab` }));
    return new Map([["", { counts: { blocked: 4, working: 2, idle: 1 },
      blocked }]]);
  }
}
"""

TITLE_BAR = """\
import MachineStats from "./real-main.js";

export default class Bar extends MachineStats {
  init() {
    this.btop = "test/t0";
  }
  async close() {}
}
"""


def check_env(tmp_path):
    env = dict(os.environ)
    env.update({
        "HERDR_APP_HOME": str(tmp_path / "app-home"),
        "HC_SESSION": SESSION,
        "XDG_STATE_HOME": str(tmp_path / "state"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
    })
    return env


needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node is not installed")
needs_app = pytest.mark.skipif(
    shutil.which("herdr-app") is None
    or not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")),
    reason="herdr-app check needs herdr-app and a display")


@needs_node
def test_node_suite():
    done = subprocess.run(["node", "--test", "tests/js/"], cwd=ROOT,
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr


def core_socket():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "herdr-core" / f"{SESSION}.sock"


def run_check(folder, tmp_path):
    done = subprocess.run(["herdr-app", "check", str(folder)],
                          env=check_env(tmp_path), capture_output=True,
                          text=True, timeout=120)
    # A check must not need a core: one started here would be left running.
    assert not core_socket().exists(), "the check started a herdr-core"
    return done


@needs_app
def test_check_passes(tmp_path):
    done = run_check(MOD, tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr


@needs_app
@pytest.mark.parametrize("main", [SEEDED, TITLE_BAR],
                         ids=["seeded", "title-bar"])
def test_check_passes_seeded(tmp_path, main):
    copy = tmp_path / "machine-stats"
    shutil.copytree(MOD, copy, ignore=shutil.ignore_patterns(
        "gpui-kit.d.ts", "jsconfig.json"))
    (copy / "main.js").rename(copy / "real-main.js")
    (copy / "main.js").write_text(main)
    done = run_check(copy, tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
