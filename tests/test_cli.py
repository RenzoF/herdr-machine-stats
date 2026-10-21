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
import subprocess
import sys
import termios
import time
from pathlib import Path

import pytest

import statslib
from statslib import collect, deploy

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


def build_hosts(tmp_path, source, root="/x"):
    """This machine runs the plugin from ``source``; the remote has none."""
    here = {"result": {"plugins": [{
        "plugin_id": statslib.PLUGIN_ID,
        "version": statslib.local_version(), "plugin_root": str(root),
        "source": source}]}}
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


@pytest.fixture
def hosts(tmp_path):
    """This machine runs a GitHub install; the remote has no plugin."""
    return build_hosts(tmp_path, {"kind": "github", "resolved_commit": COMMIT})


@pytest.fixture
def dirty_hosts(tmp_path):
    """This machine runs a checkout with uncommitted changes."""
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    (checkout / "edited.txt").write_text("not committed\n")
    return build_hosts(tmp_path, {"kind": "local"}, checkout)


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


def test_a_refusal_shows_on_the_card_and_installs_nothing(dirty_hosts):
    env, _local, remote = dirty_hosts
    screen = Screen(env, "--deploy", "ask")
    assert screen.wait_for("plugin missing")
    screen.press("l")
    screen.press("d")
    assert screen.wait_for("y/n")
    screen.press("y")
    assert screen.wait_for("plugin refused: this copy has uncommitted")
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


def test_start_deploys_hands_each_machine_this_copys_entry():
    command, started = load_command(), []

    class Recorder:
        def start(self, label, target, entry):
            started.append((label, target, entry))
    here = {"source": {"kind": "github", "resolved_commit": COMMIT}}
    command.start_deploys(Recorder(), here, [("a", "ta"), ("b", "tb")])
    assert started == [("a", "ta", here), ("b", "tb", here)]


def test_a_card_shows_deployed_until_the_next_poll_then_the_real_state():
    command = load_command()
    deployer = deploy.Deployer(run=lambda *a, **k: subprocess.CompletedProcess(
        [], 0, "", ""), clock=lambda: 10.0)
    deployer.start("MBP", "ta", {"source": {
        "kind": "github", "resolved_commit": COMMIT}})
    deployer.threads["MBP"].join(5)
    row = remote_row({})  # the poll still sees no plugin
    version = statslib.local_version()
    assert command.notes_for(row, False, version, deployer, 9.0) == (
        "plugin deployed", "green")
    assert command.notes_for(row, False, version, deployer, 11.0) == (
        "plugin missing", "yellow")
    assert command.notes_for(
        remote_row(github(version)), False, version, deployer, 11.0) == (
        "plugin current", "green")


class Halt(Exception):
    """Ends Poller.loop after its first poll."""


def test_the_poller_reports_when_its_latest_poll_began(monkeypatch):
    command = load_command()
    monkeypatch.setattr(command, "load_machines", lambda: ([], None))
    monkeypatch.setattr(collect, "poll", lambda label, found: [])
    # No background thread (it would linger, and the pty tests fork).
    monkeypatch.setattr(command.threading, "Thread", lambda **kw: type(
        "NoThread", (), {"start": lambda self: None})())
    poller = command.Poller(60)
    assert poller.view()[4] is None

    def halt(timeout=None):
        raise Halt
    monkeypatch.setattr(poller.wake, "wait", halt)
    before = time.monotonic()
    with pytest.raises(Halt):
        poller.loop()
    assert before <= poller.view()[4] <= time.monotonic()


def test_pipeline_url_prefers_the_flag_then_the_config(monkeypatch, tmp_path):
    command = load_command()
    (tmp_path / "config.toml").write_text(
        'pipeline_url = "http://cfg/status"\n')
    monkeypatch.setattr(command.herdr, "config_dir", lambda _id: tmp_path)
    assert command.pipeline_url(None) == ("http://cfg/status", None)
    assert command.pipeline_url("http://flag/status") == (
        "http://flag/status", None)
    assert command.pipeline_url("") == ("", None)  # --pipeline '' turns it off
    url, note = command.pipeline_url("file:///etc/passwd")
    assert url == "" and "--pipeline" in note


def test_no_pipeline_is_configured_by_default(monkeypatch, tmp_path):
    command = load_command()
    monkeypatch.setattr(command.herdr, "config_dir", lambda _id: tmp_path)
    assert command.pipeline_url(None) == ("", None)


def test_the_poller_reads_the_pipeline_only_when_given_a_url(monkeypatch):
    command = load_command()
    monkeypatch.setattr(command.threading, "Thread", lambda **kw: type(
        "NoThread", (), {"start": lambda self: None})())
    monkeypatch.setattr(command.pipeline.threading, "Thread",
                        command.threading.Thread)
    assert command.Poller(60).pipeline() is None
    assert command.Poller(60).watcher is None
    poller = command.Poller(60, "http://x/status")
    assert poller.watcher is not None and poller.pipeline() is None
    poller.refresh()  # wakes both loops without error


@pytest.mark.filterwarnings("ignore:.*multi-threaded:DeprecationWarning")
def test_the_dashboard_draws_the_pipeline_card_next_to_the_machines(hosts):
    from tests.test_pipeline import Dispatcher, status
    env = hosts[0]
    server = Dispatcher(body=json.dumps(status()).encode())
    try:
        screen = Screen(env, "--pipeline", server.url)
        assert screen.wait_for("shop#630")
        assert screen.wait_for("last lease")
        assert b"MBP" in screen.seen  # the machine cards are still there
        assert screen.quit() == 0
    finally:
        server.close()


def test_the_dashboard_says_unreachable_when_the_dispatcher_is_down(hosts):
    screen = Screen(hosts[0], "--pipeline", "http://127.0.0.1:1/status")
    assert screen.wait_for("unreachable")
    assert screen.quit() == 0


def test_without_a_pipeline_url_there_is_no_pipeline_card(hosts, tmp_path):
    screen = Screen(hosts[0])
    assert screen.wait_for("MBP")
    assert b"pipeline" not in screen.seen
    assert screen.quit() == 0


def test_deploy_excluded_turns_deploy_off_when_the_value_is_broken(
        monkeypatch, tmp_path):
    command = load_command()
    monkeypatch.setattr(command.herdr, "config_dir", lambda _id: tmp_path)
    assert command.deploy_excluded() == ((), None, None)
    (tmp_path / "config.toml").write_text('deploy_exclude = ["lab"]\n')
    assert command.deploy_excluded() == (("lab",), None, None)
    (tmp_path / "config.toml").write_text('deploy_exclude = "lab"\n')
    names, forced, note = command.deploy_excluded()
    assert names == () and forced == "off" and "deploy_exclude" in note


def test_unknown_excluded_names_are_found_once_there_are_rows():
    command = load_command()
    rows = [remote_row({}, "here"), remote_row({}, "MBP")]
    assert command.unknown_excluded(("MBP", "mbp"), rows) == ["mbp"]
    assert command.unknown_excluded(("MBP",), rows) == []
    assert command.unknown_excluded(("MBP",), []) == []  # not polled yet


def test_an_excluded_machine_cannot_be_deployed_to_by_key():
    command = load_command()
    rows = [remote_row(github(statslib.local_version())),
            remote_row({}, "lab")]
    assert "lab is excluded" in command.ask_deploy(
        "ask", rows, 1, statslib.local_version(), ("lab",))
    assert command.ask_deploy(
        "ask", rows, 1, statslib.local_version(), ("other",)) is None


def test_an_excluded_machine_says_so_on_its_plugin_line():
    command = load_command()
    deployer = deploy.Deployer(run=lambda *a, **k: subprocess.CompletedProcess(
        [], 0, "", ""))
    version = statslib.local_version()
    assert command.notes_for(remote_row({}, "lab"), False, version,
                             deployer, None, ("lab",)) == (
        "plugin missing · excluded", "dim")
    assert command.notes_for(remote_row({}, "lab"), False, version,
                             deployer, None) == ("plugin missing", "yellow")


def test_auto_mode_leaves_an_excluded_machine_alone(hosts, tmp_path):
    env, _local, remote = hosts
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('deploy_exclude = ["MBP"]\n')
    local_shim = tmp_path / "local" / "herdr"
    local_shim.write_text(local_shim.read_text().replace(
        'case "$1 $2" in', 'case "$1 $2" in\n  "plugin config-dir") echo '
        f'"{config_dir}";;', 1))
    screen = Screen(env, "--deploy", "auto")
    assert screen.wait_for("excluded")
    time.sleep(2)
    assert installs(remote) == []
    assert screen.quit() == 0


def test_a_misspelt_exclusion_pauses_auto_deploy_instead_of_deploying(
        hosts, tmp_path):
    env, _local, remote = hosts
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text('deploy_exclude = ["mbp"]\n')
    local_shim = tmp_path / "local" / "herdr"
    local_shim.write_text(local_shim.read_text().replace(
        'case "$1 $2" in', 'case "$1 $2" in\n  "plugin config-dir") echo '
        f'"{config_dir}";;', 1))
    screen = Screen(env, "--deploy", "auto")
    assert screen.wait_for("names no machine")
    time.sleep(2)
    assert installs(remote) == []
    assert screen.quit() == 0
