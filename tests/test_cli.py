"""bin/machine-stats end to end in a pseudo-terminal, with fake hosts."""

import fcntl
import importlib.machinery
import importlib.util
import json
import os
import pty
import select
import stat
import struct
import sys
import termios
import time
from pathlib import Path

import pytest

import statslib
from statslib import collect

ROOT = Path(__file__).resolve().parent.parent
COMMIT = "c0ffee" * 6 + "ab"


def shim(directory, name, body):
    path = directory / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def fake_herdr(directory, plugin_list):
    """A herdr that logs its argv and answers the reads fleet makes."""
    directory.mkdir()
    (directory / "plugin-list").write_text(json.dumps(plugin_list))
    shim(directory, "herdr", (
        f'echo "$@" >> "{directory}/calls.log"\n'
        'case "$1 $2" in\n'
        '  "machine list") printf "a1\\tMBP\\tme@10.0.0.9\\tdefault'
        '\\tenabled\\n";;\n'
        '  "agent list") echo \'{"result":{"agents":[]}}\';;\n'
        f'  "plugin list") cat "{directory}/plugin-list";;\n'
        "esac\n"))
    return directory / "calls.log"


@pytest.fixture
def hosts(tmp_path):
    """This machine runs a GitHub install; the remote has no plugin."""
    here = {"result": {"plugins": [{
        "plugin_id": statslib.PLUGIN_ID,
        "version": statslib.local_version(), "plugin_root": "/x",
        "source": {"kind": "github", "resolved_commit": COMMIT}}]}}
    local_log = fake_herdr(tmp_path / "local", here)
    remote_log = fake_herdr(tmp_path / "remote", {"result": {"plugins": []}})
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # ssh: drop options and the target, run the command with the remote
    # herdr first on PATH, as a login shell on the other machine would.
    shim(bin_dir, "ssh", (
        'while [ "$1" = -o ] || [ "$1" = -t ]; do\n'
        '  if [ "$1" = -t ]; then shift; else shift 2; fi\n'
        "done\n"
        "shift\n"
        f'PATH="{tmp_path / "remote"}:$PATH" exec sh -c "$*"\n'))
    env = dict(os.environ, TERM="xterm-256color",
               HERDR_BIN=str(tmp_path / "local" / "herdr"),
               PATH=f"{tmp_path / 'local'}:{bin_dir}:{os.environ['PATH']}")
    return env, local_log, remote_log


class Screen:
    def __init__(self, env, *args):
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.execvpe(sys.executable, [
                sys.executable, str(ROOT / "bin" / "machine-stats"),
                "--interval", "60", *args], env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ,
                    struct.pack("HHHH", 30, 120, 0, 0))
        self.seen = b""

    def wait_for(self, token, secs=20):
        end = time.monotonic() + secs
        while token.encode() not in self.seen and time.monotonic() < end:
            ready, _, _ = select.select([self.fd], [], [], 0.3)
            if ready:
                try:
                    self.seen += os.read(self.fd, 65536)
                except OSError:
                    break
        return token.encode() in self.seen

    def press(self, keys):
        os.write(self.fd, keys.encode())

    def quit(self):
        self.press("q")
        _, status = os.waitpid(self.pid, 0)
        os.close(self.fd)
        return os.waitstatus_to_exitcode(status)


def installs(log):
    lines = log.read_text().splitlines() if log.exists() else []
    return [line for line in lines if line.startswith("plugin install")]


def wait_until(check, secs=10):
    end = time.monotonic() + secs
    while not check() and time.monotonic() < end:
        time.sleep(0.2)
    return check()


def test_ask_mode_deploys_the_selected_machine_after_yes(hosts):
    env, _local, remote = hosts
    screen = Screen(env, "--deploy", "ask")
    assert screen.wait_for("plugin missing")
    screen.press("l")  # select MBP, the second card
    screen.press("d")
    version = statslib.local_version()
    assert screen.wait_for(f"deploy {version} to MBP? y/n")
    screen.press("y")
    assert wait_until(lambda: installs(remote))
    assert installs(remote) == [
        f"plugin install RenzoF/herdr-machine-stats --ref {COMMIT} --yes"]
    assert screen.quit() == 0


def test_ask_mode_installs_nothing_after_no(hosts):
    env, _local, remote = hosts
    screen = Screen(env, "--deploy", "ask")
    assert screen.wait_for("plugin missing")
    screen.press("l")
    screen.press("d")
    assert screen.wait_for("y/n")
    screen.press("n")
    time.sleep(1)
    assert installs(remote) == []
    assert screen.quit() == 0


def test_off_mode_says_how_to_turn_deploy_on(hosts):
    env, _local, remote = hosts
    screen = Screen(env, "--deploy", "off")
    assert screen.wait_for("plugin missing")
    screen.press("l")
    screen.press("d")
    assert screen.wait_for("deploy is off")
    assert installs(remote) == []
    assert screen.quit() == 0


def test_auto_mode_deploys_once_without_a_key(hosts):
    env, _local, remote = hosts
    screen = Screen(env, "--deploy", "auto")
    assert wait_until(lambda: installs(remote), 20)
    time.sleep(1)
    assert len(installs(remote)) == 1
    assert screen.quit() == 0


def load_command():
    loader = importlib.machinery.SourceFileLoader(
        "stats_cmd", str(ROOT / "bin" / "machine-stats"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def remote_row(plugin, label="MBP"):
    snap = collect.Snapshot(
        os="Linux", ncpu=4, load=0.5, cpu_pct=5, mem_pct=10,
        mem_used_kb=1, mem_total_kb=10, disk_pct=10, disk_used_kb=1,
        disk_total_kb=10, agents={}, plugin=plugin)
    return collect.Row(label, snap, None)


def github(version):
    return {"version": version, "source": {"kind": "github"}}


@pytest.mark.parametrize("mode, row, selected, want", [
    ("off", remote_row({}), 1, "deploy is off"),
    ("auto", remote_row({}), 1, "automatic"),
    ("ask", remote_row({}), 0, "runs the plugin already"),
    ("ask", collect.Row("MBP", None, "timeout"), 1, "MBP is down"),
    ("ask", remote_row(github("99.0.0")), 1, "plugin newer"),
    ("ask", remote_row(github("0.0.1")), 1, None),
    ("ask", remote_row({}), 1, None),
    ("ask", remote_row({"version": "0.0.1", "source": {"kind": "local"}}),
     1, "plugin older (linked checkout)"),
])
def test_ask_deploy_names_the_reason_not_to_deploy(mode, row, selected, want):
    rows = [remote_row(github(statslib.local_version())), row]
    reason = load_command().ask_deploy(
        mode, rows, selected, statslib.local_version())
    if want is None:
        assert reason is None
    else:
        assert want in reason


def test_start_deploys_looks_the_commit_up_once_and_installs_each():
    command, started = load_command(), []

    class Recorder:
        def start(self, label, target, commit):
            started.append((label, target, commit))
    here = {"source": {"kind": "github", "resolved_commit": COMMIT}}
    assert command.start_deploys(
        Recorder(), here, [("a", "ta"), ("b", "tb")]) is None
    assert started == [("a", "ta", COMMIT), ("b", "tb", COMMIT)]


def test_start_deploys_reports_a_refusal_and_installs_nothing():
    command, started = load_command(), []

    class Recorder:
        def start(self, *args):
            started.append(args)
    message = command.start_deploys(Recorder(), None, [("a", "ta")])
    assert message.startswith("deploy refused: ")
    assert started == []
