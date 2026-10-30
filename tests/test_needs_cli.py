"""bin/machine-stats with the needs-you list, end to end in a pty."""

import json
import os
from pathlib import Path

import pytest

from test_cli import Screen, shim, wait_until  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


def listing(key, *entries):
    return json.dumps({"result": {key: list(entries)}})


def host(directory, agents, workspace, tab, screen, delay=0):
    """A fake herdr for one host: canned lists, a screen, and a log."""
    directory.mkdir()
    canned = {"agent-list": agents,
              "workspace-list": listing("workspaces", workspace),
              "tab-list": listing("tabs", tab), "agent-read": screen}
    for name, body in canned.items():
        (directory / name).write_text(body)
    pause = f'  "agent list") sleep {delay}; cat "{directory}/agent-list";;\n'
    shim(directory, "herdr", (
        f'echo "$@" >> "{directory}/calls.log"\n'
        'case "$1 $2" in\n'
        '  "machine list") printf "a1\\tlaptop\\tme@laptop.example'
        '\\tdefault\\tenabled\\n";;\n'
        + (pause if delay else "") +
        '  "plugin list") echo \'{"result":{"plugins":[]}}\';;\n'
        f'  *) f="{directory}/$1-$2"; [ -f "$f" ] && cat "$f";;\n'
        "esac\n"
        "exit 0\n"))
    return directory / "calls.log"


def make_fleet(tmp_path, delay=0):
    """This machine has a blocked "builder"; the laptop a blocked codex."""
    local = host(
        tmp_path / "local",
        listing("agents", {
            "pane_id": "w1:p2", "agent_status": "blocked",
            "name": "builder", "cwd": "/src/api", "workspace_id": "w1",
            "tab_id": "w1:t3", "state_change_seq": 4}),
        {"workspace_id": "w1", "number": 5, "label": "api"},
        {"tab_id": "w1:t3", "workspace_id": "w1", "number": 18,
         "label": "review"},
        "Do you want to proceed?\n❯ 1. Yes\n")
    remote = host(
        tmp_path / "remote",
        listing("agents", {
            "pane_id": "w9:p1", "agent_status": "blocked",
            "agent": "codex", "cwd": "/src/site", "workspace_id": "w9",
            "tab_id": "w9:t4", "state_change_seq": 2}),
        {"workspace_id": "w9", "number": 2, "label": "site"},
        {"tab_id": "w9:t4", "workspace_id": "w9", "number": 4,
         "label": "deploy"},
        "Allow this command?\n", delay)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # ssh: drop options and the target, run the command with the remote
    # herdr first on PATH, as in test_cli.
    shim(bin_dir, "ssh", (
        'while [ "$1" = -o ] || [ "$1" = -t ]; do\n'
        '  if [ "$1" = -t ]; then shift; else shift 2; fi\n'
        "done\n"
        "shift\n"
        f'PATH="{tmp_path / "remote"}:$PATH" exec sh -c "$*"\n'))
    env = dict(os.environ, TERM="xterm-256color",
               HERDR_BIN=str(tmp_path / "local" / "herdr"),
               HERDR_PLUGIN_STATE_DIR=str(tmp_path / "state"),
               PATH=f"{tmp_path / 'local'}:{bin_dir}:{os.environ['PATH']}")
    env.pop("HERDR_ENV", None)
    return env, local, remote


@pytest.fixture
def fleet(tmp_path):
    return make_fleet(tmp_path)


def test_the_dashboard_shows_what_needs_you_above_the_cards(fleet):
    env, _local, _remote = fleet
    screen = Screen(env)
    try:
        assert screen.wait_for("needs you")
        assert screen.wait_for("builder")
        assert screen.wait_for("review")
        assert screen.wait_for("proceed")  # its screen's question
        assert screen.wait_for("codex")
        assert screen.wait_for("CPU")  # the cards are still there
    finally:
        assert screen.quit() == 0


def test_the_dashboard_keeps_first_seen_times_in_its_state_dir(fleet):
    env, _local, _remote = fleet
    screen = Screen(env)
    try:
        ages = Path(env["HERDR_PLUGIN_STATE_DIR"]) / "needs.json"
        assert wait_until(ages.exists)
        assert "proceed" not in ages.read_text()
    finally:
        assert screen.quit() == 0
