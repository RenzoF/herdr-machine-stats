"""fleet: the multi-machine dashboard (crewlib/fleet.py, bin/fleet)."""

import importlib.machinery
import importlib.util
import os
import platform
import pty
import re
import select
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from fleetlib import collect as fleet, herdr

# `herdr machine list`: id, label, ssh target, session, state. The two
# omarchy-lenovo rows share a target, as happened on agent-desk.
MACHINE_LIST = (
    "24725ac0\tMBP\trenzo@10.99.0.10\tdefault\tenabled\n"
    "0c744f2f\tomarchy\trfp@10.99.0.14\tdefault\tenabled\n"
    "4db71a7a\tomarchy-lenovo\trenzo@10.99.0.50\tdefault\tenabled\n"
    "48d072fe\tomarchy-lenovo\trenzo@10.99.0.50\tdefault\tenabled\n"
    "c9ed3706\tmacmini\tmini\tdefault\tdisabled\n"
)


def test_parse_machines_merges_a_shared_target_and_keeps_disabled():
    got = fleet.parse_machines(MACHINE_LIST)
    assert [(m.label, m.target, m.enabled) for m in got] == [
        ("MBP", "renzo@10.99.0.10", True),
        ("omarchy", "rfp@10.99.0.14", True),
        ("omarchy-lenovo", "renzo@10.99.0.50", True),
        ("macmini", "mini", False),
    ]


def test_parse_machines_skips_blank_and_short_lines():
    assert fleet.parse_machines("\nonly-one-field\nid\tlabel\n") == []


# What the collector prints: key=value facts, then the raw output of
# `herdr agent list` after the --agents-- marker.
SNAPSHOT = (
    "os=Linux\n"
    "ncpu=12\n"
    "load=7.63\n"
    "mem_total_kb=24000000\n"
    "mem_avail_kb=6000000\n"
    "disk_pct=64\n"
    "--agents--\n"
    '{"id":"cli:agent:list","result":{"agents":['
    '{"agent":"claude","agent_status":"idle","pane_id":"w1:p1"},'
    '{"agent":"claude","agent_status":"idle","pane_id":"w1:p2"},'
    '{"agent":"codex","agent_status":"blocked","pane_id":"w2:p1"},'
    '{"agent":"claude","agent_status":"working","pane_id":"w3:p1"}]}}\n'
)


def test_parse_snapshot_derives_memory_percent_and_counts_agents():
    snap = fleet.parse_snapshot(SNAPSHOT)
    # (24000000 - 6000000) / 24000000 of memory is in use.
    assert (snap.os, snap.ncpu, snap.load) == ("Linux", 12, 7.63)
    assert (snap.mem_pct, snap.disk_pct) == (75, 64)
    assert snap.agents == {"idle": 2, "blocked": 1, "working": 1}


def test_parse_snapshot_has_no_agent_counts_without_usable_herdr_output():
    facts = SNAPSHOT.split("--agents--")[0]
    # Herdr missing on the host: the marker is followed by nothing.
    assert fleet.parse_snapshot(facts + "--agents--\n").agents is None
    # Herdr answering with something that is not the agent list.
    assert fleet.parse_snapshot(
        facts + "--agents--\nserver not running\n").agents is None


def test_parse_snapshot_names_the_missing_fact():
    broken = SNAPSHOT.replace("load=7.63\n", "")
    with pytest.raises(ValueError, match="load"):
        fleet.parse_snapshot(broken)


AGENT_LIST = (
    '{"id":"cli:agent:list","result":{"agents":['
    '{"agent_status":"idle"},{"agent_status":"blocked"}]}}'
)


def run_collector(path_dirs):
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([*map(str, path_dirs), env["PATH"]])
    return subprocess.run(
        ["sh", "-c", fleet.COLLECT_SCRIPT], env=env,
        capture_output=True, text=True, timeout=30,
    )


def test_collector_output_parses_on_this_host_and_asks_herdr_for_agents(
        fake_herdr):
    shim, calls, canned = fake_herdr
    (canned / "agent-list").write_text(AGENT_LIST)
    done = run_collector([shim.parent])
    assert done.returncode == 0, done.stderr
    snap = fleet.parse_snapshot(done.stdout)
    assert snap.os == platform.system()
    assert snap.ncpu >= 1 and snap.load >= 0
    assert 0 <= snap.mem_pct <= 100 and 0 <= snap.disk_pct <= 100
    assert snap.agents == {"idle": 1, "blocked": 1}
    assert calls.read_text() == "agent list\n"


def write_shim(directory, name, body):
    path = directory / name
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_collector_reads_macos_memory_and_load_from_sysctl_and_vm_stat(
        tmp_path):
    write_shim(tmp_path, "uname", "echo Darwin\n")
    write_shim(tmp_path, "sysctl", (
        'case "$2" in\n'
        "  hw.ncpu) echo 10;;\n"
        '  vm.loadavg) echo "{ 3.71 3.57 3.38 }";;\n'
        "  hw.memsize) echo 25769803776;;\n"
        "esac\n"))
    write_shim(tmp_path, "vm_stat", (
        "cat <<'EOF'\n"
        "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
        "Pages free:                               100000.\n"
        "Pages active:                             123456.\n"
        "Pages inactive:                           200000.\n"
        "Pages speculative:                         50000.\n"
        "EOF\n"))
    done = run_collector([tmp_path])
    assert done.returncode == 0, done.stderr
    snap = fleet.parse_snapshot(done.stdout)
    # 24 GiB total, (100000 + 200000 + 50000) pages of 16 KiB available.
    assert (snap.os, snap.ncpu, snap.load) == ("Darwin", 10, 3.71)
    assert snap.mem_pct == 78


def machine(label="lab", target="me@10.0.0.9", enabled=True):
    return fleet.Machine(label, target, enabled)


class Runner:
    """A stand-in for fleet.run_host that records what it was asked."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, target, script):
        self.calls.append((target, script))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_collect_polls_the_machines_target_with_the_collector_script():
    run = Runner(SNAPSHOT)
    row = fleet.collect(machine(), run)
    assert run.calls == [("me@10.0.0.9", fleet.COLLECT_SCRIPT)]
    assert (row.label, row.error) == ("lab", None)
    assert row.snapshot.agents == {"idle": 2, "blocked": 1, "working": 1}


def test_collect_reports_why_a_host_could_not_be_read():
    down = fleet.collect(machine(), Runner(fleet.HostError("timeout")))
    assert (down.snapshot, down.error) == (None, "timeout")
    garbled = fleet.collect(machine(), Runner("Welcome to a login banner\n"))
    assert garbled.snapshot is None
    assert garbled.error == (
        "unreadable output: collector output lacks mem_total_kb")


def test_collect_does_not_poll_a_disabled_machine():
    run = Runner(SNAPSHOT)
    row = fleet.collect(machine(enabled=False), run)
    assert (row.snapshot, row.error) == (None, "disabled")
    assert run.calls == []


@pytest.fixture
def fake_ssh(tmp_path, monkeypatch):
    """An `ssh` that logs its argv, skips -o options, and runs the command
    through a local shell, as the remote login shell would after joining
    the arguments with spaces."""
    log = tmp_path / "ssh.log"
    write_shim(tmp_path, "ssh", (
        f'echo "$@" >> "{log}"\n'
        'while [ "$1" = -o ]; do shift 2; done\n'
        "shift\n"
        'exec sh -c "$*"\n'))
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    return log


def test_run_host_runs_the_script_remotely_without_prompting(
        fake_ssh, fake_herdr, monkeypatch):
    shim, _calls, canned = fake_herdr
    (canned / "agent-list").write_text(AGENT_LIST)
    monkeypatch.setenv(
        "PATH", f"{shim.parent}{os.pathsep}{os.environ['PATH']}")
    out = fleet.run_host("me@10.0.0.9", fleet.COLLECT_SCRIPT)
    assert fleet.parse_snapshot(out).agents == {"idle": 1, "blocked": 1}
    logged = fake_ssh.read_text()
    assert "BatchMode=yes" in logged and "me@10.0.0.9" in logged


def test_run_host_with_no_target_runs_on_this_machine(
        fake_herdr, monkeypatch):
    shim, _calls, canned = fake_herdr
    (canned / "agent-list").write_text(AGENT_LIST)
    monkeypatch.setenv(
        "PATH", f"{shim.parent}{os.pathsep}{os.environ['PATH']}")
    out = fleet.run_host(None, fleet.COLLECT_SCRIPT)
    assert fleet.parse_snapshot(out).os == platform.system()


def test_run_host_turns_an_ssh_failure_into_its_first_error_line(
        tmp_path, monkeypatch):
    write_shim(tmp_path, "ssh", (
        'echo "me@10.0.0.9: Permission denied (publickey)." >&2\n'
        "echo more detail >&2\n"
        "exit 255\n"))
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(fleet.HostError) as err:
        fleet.run_host("me@10.0.0.9", "true")
    assert str(err.value) == "me@10.0.0.9: Permission denied (publickey)."


def test_run_host_gives_up_on_a_hung_host(tmp_path, monkeypatch):
    write_shim(tmp_path, "ssh", "exec sleep 5\n")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(fleet.HostError, match="timeout"):
        fleet.run_host("me@10.0.0.9", "true", timeout=0.3)


def snap(**changes):
    base = dict(os="Linux", ncpu=12, load=7.63, mem_pct=75, disk_pct=64,
                agents={"idle": 2, "blocked": 1, "working": 1})
    base.update(changes)
    return fleet.Snapshot(**base)


def cells(line):
    return re.split(r"\s{2,}", line.strip())


def test_format_table_lists_every_machine_under_a_header():
    rows = [
        fleet.Row("agent-desk", snap(), None),
        fleet.Row("omarchy", snap(load=0.05, ncpu=8, mem_pct=9,
                                  disk_pct=5, agents=None), None),
        fleet.Row("lenovo", snap(agents={}), None),
        fleet.Row("mini", None, "Permission denied (publickey)."),
        fleet.Row("macmini", None, "disabled"),
    ]
    got = [cells(line) for line in fleet.format_table(rows)]
    assert got == [
        ["MACHINE", "LOAD", "MEM", "DISK", "AGENTS"],
        ["agent-desk", "7.6/12", "75%", "64%",
         "blocked 1, working 1, idle 2"],
        ["omarchy", "0.1/8", "9%", "5%", "-"],
        ["lenovo", "7.6/12", "75%", "64%", "none"],
        ["mini", "down: Permission denied (publickey)."],
        ["macmini", "disabled"],
    ]


@pytest.mark.parametrize("row, level", [
    (fleet.Row("a", snap(), None), "alert"),  # one agent is blocked
    (fleet.Row("a", snap(agents={"idle": 3, "done": 1}), None), "ok"),
    (fleet.Row("a", snap(agents=None), None), "ok"),
    (fleet.Row("a", snap(agents={}, mem_pct=90), None), "ok"),
    (fleet.Row("a", snap(agents={}, mem_pct=91), None), "alert"),
    (fleet.Row("a", snap(agents={}, disk_pct=90), None), "ok"),
    (fleet.Row("a", snap(agents={}, disk_pct=91), None), "alert"),
    (fleet.Row("a", None, "timeout"), "down"),
    (fleet.Row("a", None, "disabled"), "dim"),
])
def test_row_level_marks_what_needs_attention(row, level):
    assert fleet.row_level(row) == level


def test_a_long_error_does_not_stretch_the_columns_of_the_other_rows():
    rows = [fleet.Row("a", snap(), None), fleet.Row("b", None, "x" * 60)]
    header = fleet.format_table(rows)[0]
    # "7.6/12" is the widest LOAD value; the 60-character reason is not one.
    assert header.index("MEM") - header.index("LOAD") < 12


def test_machine_list_text_reads_herdr_outside_a_herdr_pane(fake_herdr,
                                                            monkeypatch):
    shim, calls, canned = fake_herdr
    (canned / "machine-list").write_text(MACHINE_LIST)
    monkeypatch.setenv("HERDR_BIN", str(shim))
    # conftest removes HERDR_ENV: fleet must also work from a plain terminal.
    assert herdr.machine_list_text() == MACHINE_LIST
    assert calls.read_text() == "machine list\n"


def test_machine_list_text_raises_unavailable_without_herdr(monkeypatch):
    monkeypatch.setenv("HERDR_BIN", "/nonexistent/herdr")
    with pytest.raises(herdr.HerdrUnavailable):
        herdr.machine_list_text()


def test_poll_puts_this_machine_first_and_keeps_the_saved_order():
    seen = []

    def run(target, script):
        seen.append(target)
        if target == "rfp@10.99.0.14":
            raise fleet.HostError("timeout")
        return SNAPSHOT

    machines = [machine("MBP", "renzo@10.99.0.10"),
                machine("omarchy", "rfp@10.99.0.14")]
    rows = fleet.poll("agent-desk", machines, run)
    assert [(r.label, r.error) for r in rows] == [
        ("agent-desk", None), ("MBP", None), ("omarchy", "timeout")]
    assert sorted(seen, key=str) == sorted(
        [None, "renzo@10.99.0.10", "rfp@10.99.0.14"], key=str)


def test_drill_runs_the_monitor_when_the_host_has_it(tmp_path, monkeypatch):
    write_shim(tmp_path, "fake-monitor", "echo monitor ran\n")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    done = subprocess.run(fleet.drill_argv(None, "fake-monitor"),
                          capture_output=True, text=True, timeout=10)
    assert done.stdout == "monitor ran\n"


def test_drill_says_so_when_the_host_lacks_the_monitor():
    done = subprocess.run(fleet.drill_argv(None, "no-such-monitor-xyz", 0),
                          capture_output=True, text=True, timeout=10)
    assert "no-such-monitor-xyz is not installed on" in done.stdout


def test_drill_on_a_remote_host_asks_ssh_for_a_terminal():
    argv = fleet.drill_argv("me@10.0.0.9")
    assert argv[:3] == ["ssh", "-t", "me@10.0.0.9"]


REPO = Path(__file__).resolve().parent.parent


def load_fleet_command():
    loader = importlib.machinery.SourceFileLoader(
        "fleet_cmd", str(REPO / "bin" / "fleet"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def fleet_env(fake_herdr, fake_ssh, monkeypatch):
    """Herdr knows two machines; ssh runs the collector locally."""
    shim, _calls, canned = fake_herdr
    (canned / "machine-list").write_text(
        "a1\tMBP\trenzo@10.99.0.10\tdefault\tenabled\n"
        "b2\tmacmini\tmini\tdefault\tdisabled\n")
    (canned / "agent-list").write_text(AGENT_LIST)
    monkeypatch.setenv("HERDR_BIN", str(shim))
    monkeypatch.setenv(
        "PATH", f"{shim.parent}{os.pathsep}{os.environ['PATH']}")
    return shim


def test_once_prints_this_machine_and_every_saved_one(fleet_env, capsys):
    cmd = load_fleet_command()
    assert cmd.main(["--once"]) == 0
    rows = [cells(line) for line in capsys.readouterr().out.splitlines()]
    assert rows[0] == ["MACHINE", "LOAD", "MEM", "DISK", "AGENTS"]
    assert rows[1][0] == socket.gethostname()
    assert rows[1][4] == rows[2][4] == "blocked 1, idle 1"
    assert rows[2][0] == "MBP"
    assert rows[3] == ["macmini", "disabled"]


def test_once_still_shows_this_machine_when_herdr_is_missing(
        monkeypatch, capsys):
    monkeypatch.setenv("HERDR_BIN", "/nonexistent/herdr")
    cmd = load_fleet_command()
    assert cmd.main(["--once"]) == 0
    out, err = capsys.readouterr()
    rows = [cells(line) for line in out.splitlines()]
    assert [r[0] for r in rows] == ["MACHINE", socket.gethostname()]
    assert "herdr" in err


def test_dashboard_draws_the_table_and_quits_on_q(fleet_env):
    env = dict(os.environ, TERM="xterm", COLUMNS="100", LINES="20")
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(sys.executable,
                   [sys.executable, str(REPO / "bin" / "fleet")], env)
    seen = b""
    deadline = time.monotonic() + 20
    while b"MBP" not in seen and time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.5)
        if ready:
            try:
                seen += os.read(fd, 65536)
            except OSError:  # the child exited and closed the terminal
                break
    try:
        os.write(fd, b"q")
    except OSError:
        pass
    _, status = os.waitpid(pid, 0)
    os.close(fd)
    assert b"MACHINE" in seen and b"MBP" in seen
    assert os.waitstatus_to_exitcode(status) == 0


@pytest.mark.parametrize("lang, want", [
    (None, "C.UTF-8"),  # ssh forwarded no locale: btop refuses to start
    ("POSIX", "C.UTF-8"),
    ("en_US.UTF-8", "en_US.UTF-8"),  # a UTF-8 locale is kept as it is
])
def test_drill_gives_the_monitor_a_utf8_locale(tmp_path, monkeypatch,
                                               lang, want):
    write_shim(tmp_path, "fake-monitor", 'echo "$LANG"\n')
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    for name in ("LANG", "LC_ALL", "LC_CTYPE"):
        monkeypatch.delenv(name, raising=False)
    if lang:
        monkeypatch.setenv("LANG", lang)
    done = subprocess.run(fleet.drill_argv(None, "fake-monitor"),
                          capture_output=True, text=True, timeout=10)
    assert done.stdout == f"{want}\n"
