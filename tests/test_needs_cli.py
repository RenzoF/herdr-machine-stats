"""bin/machine-stats with the needs-you list, end to end in a pty."""

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from statslib import collect, jump, seen
from statslib.needs import Item, Where
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
            "agent": "claude", "name": "builder", "cwd": "/src/api",
            "workspace_id": "w1", "tab_id": "w1:t3",
            "state_change_seq": 4}),
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


def item(target=None, machine="build-box"):
    return Item("blocked", 0, machine, target, "w1:p2", 4, "builder",
                "api", Where(5, "api", 18, "review"), (), None, 0, False,
                (machine, "w1:p2"))


def test_a_local_jump_focuses_the_pane_here_and_lands(fake_herdr,
                                                      monkeypatch):
    herdr_shim, calls, _canned = fake_herdr
    monkeypatch.setenv("HERDR_BIN", str(herdr_shim))
    assert jump.jump(item()) == (True, None)
    assert calls.read_text().splitlines() == ["agent focus w1:p2"]


def test_a_remote_jump_focuses_it_there_and_says_where():
    runs = []
    landed, message = jump.jump(
        item("me@laptop.example", "laptop"),
        run=lambda target, script: runs.append((target, script)) or "")
    assert not landed
    assert message == ("laptop: workspace 5 api, tab 18 'review'. "
                       "Pick laptop with prefix+w")
    [(target, script)] = runs
    assert target == "me@laptop.example"
    assert script.startswith(collect.PATH_LINE)
    assert script.endswith("herdr agent focus w1:p2")


def test_a_failed_jump_says_why(monkeypatch):
    def down(target, script):
        raise collect.HostError("timeout")
    assert jump.jump(item("me@laptop.example", "laptop"), run=down) == (
        False, "laptop: could not focus: timeout")
    monkeypatch.setenv("HERDR_BIN", "/nonexistent/herdr")
    landed, message = jump.jump(item())
    assert not landed and message.startswith("build-box: could not focus")


def test_bang_opens_the_full_list_and_enter_focuses_a_local_pane(fleet):
    env, local, _remote = fleet
    screen = Screen(env)
    try:
        assert screen.wait_for("builder")
        screen.press("!")
        assert screen.wait_for("waiting on you (2)")
        screen.press("\r")
        assert wait_until(lambda: "agent focus w1:p2" in local.read_text())
        screen.seen = b""
        screen.press("!")  # back to the cards
        assert screen.wait_for("CPU")
    finally:
        assert screen.quit() == 0


def test_enter_on_a_remote_item_focuses_it_there_and_says_where(fleet):
    env, _local, remote = fleet
    screen = Screen(env)
    try:
        assert screen.wait_for("codex")
        screen.press("!")
        assert screen.wait_for("waiting on you (2)")
        screen.press("j")
        screen.press("\r")
        assert wait_until(lambda: "agent focus w9:p1" in remote.read_text())
        assert screen.wait_for("Pick laptop with prefix+w")
        screen.press("!")
    finally:
        assert screen.quit() == 0


def test_the_popup_jumps_to_a_local_pane_and_closes(fleet):
    env, local, _remote = fleet
    screen = Screen(env, "--needs")
    assert screen.wait_for("builder")
    screen.press("\r")
    _, status = os.waitpid(screen.pid, 0)
    os.close(screen.fd)
    assert os.waitstatus_to_exitcode(status) == 0
    assert "agent focus w1:p2" in local.read_text()


def test_the_popup_says_where_a_remote_pane_is_and_stays_open(fleet):
    env, _local, remote = fleet
    screen = Screen(env, "--needs")
    try:
        assert screen.wait_for("codex")
        screen.press("j")
        screen.press("\r")
        assert screen.wait_for("Pick laptop with prefix+w")
        assert "agent focus w9:p1" in remote.read_text()
    finally:
        assert screen.quit() == 0


def test_the_popup_shows_the_last_list_at_once(tmp_path):
    env, _local, _remote = make_fleet(tmp_path, delay=3)
    seen.Store(Path(env["HERDR_PLUGIN_STATE_DIR"])).save_list([Item(
        "done", 0, "laptop", "me@laptop.example", "w9:p7", 1,
        "old-agent", "old", None, (), None, 1000.0, False,
        ("laptop", "w9:p7"))], 1000.0)
    screen = Screen(env, "--needs")
    try:
        # At most 12 cells: the wide layout caps the agent column.
        assert screen.wait_for("old-agent", secs=2)
        assert screen.wait_for("as of")
    finally:
        assert screen.quit() == 0


def test_once_needs_prints_the_list_as_plain_text(fleet):
    env, _local, _remote = fleet
    done = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "machine-stats"), "--once",
         "--needs"], env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[0] == "waiting on you (2)"
    assert "builder" in lines[1]
    assert "workspace 5 api, tab 18 'review'" in lines[1]
    assert "    │ Do you want to proceed?" in lines
    assert any("codex" in line and "laptop" in line for line in lines)
    assert "cpu" not in done.stdout.lower()


def test_the_manifest_opens_the_list_as_a_popup():
    with open(ROOT / "herdr-plugin.toml", "rb") as f:
        manifest = tomllib.load(f)
    [pane] = [p for p in manifest["panes"] if p["id"] == "needs"]
    assert pane["placement"] == "popup"
    assert pane["command"] == ["python3", "bin/machine-stats", "--needs"]
    [action] = [a for a in manifest["actions"] if a["id"] == "needs"]
    command = action["command"]
    assert command[command.index("--entrypoint") + 1] == "needs"
    assert command[command.index("--placement") + 1] == "popup"


def test_a_host_whose_agent_list_failed_keeps_its_first_seen_times(
        tmp_path):
    from test_cli import load_command
    from statslib import collect, needs
    command = load_command()
    store = seen.Store(tmp_path / "state")
    screens = needs.Screens(lambda target, panes: {})

    def row(agents):
        data = needs.Raw(1000, agents, {}, {}, [])
        return collect.Row("laptop", None, None, data)
    blocked = [{"pane_id": "w1:p1", "agent_status": "blocked",
                "agent": "claude", "state_change_seq": 1}]
    command.gather_needs([row(blocked)], [None], store, screens, 10)
    first = json.loads(store.ages.read_text())["items"]
    # Herdr answered, but its agent list was unusable: not an answer.
    command.gather_needs([row(None)], [None], store, screens, 10)
    assert json.loads(store.ages.read_text())["items"] == first
