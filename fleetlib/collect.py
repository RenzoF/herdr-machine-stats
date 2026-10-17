"""Fleet dashboard: one row of live stats per machine Herdr knows about.

Everything here is read-only. A machine is polled with one SSH call that
prints a few facts about the host and the output of ``herdr agent list``;
nothing is installed on, written to, or sent to the machines.
"""

import shlex
import subprocess
import threading
from collections import namedtuple

from fleetlib import herdr

Machine = namedtuple("Machine", "label target enabled")
Snapshot = namedtuple(
    "Snapshot",
    "os ncpu load cpu_pct mem_pct mem_used_kb mem_total_kb"
    " disk_pct disk_used_kb disk_total_kb agents",
)
# One dashboard row: a snapshot, or the reason there is none.
Row = namedtuple("Row", "label snapshot error")

AGENTS_MARKER = "--agents--"

# POSIX sh, run on every host (Linux and macOS) through ``sh -c``. Prints
# the facts parse_snapshot reads, then Herdr's agent list after the marker.
COLLECT_SCRIPT = f"""\
PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin
os=$(uname -s)
echo "os=$os"
if [ "$os" = Darwin ]; then
  echo "ncpu=$(sysctl -n hw.ncpu)"
  echo "load=$(sysctl -n vm.loadavg | awk '{{print $2}}')"
  top -l 2 -n 0 -s 1 | awk '/CPU usage/ {{idle=$7}} \
END {{printf "cpu_pct=%d\\n", 100 - idle + 0.5}}'
  echo "mem_total_kb=$(( $(sysctl -n hw.memsize) / 1024 ))"
  vm_stat | awk '/page size of/ {{ps=$8}} /Pages free/ {{n+=$3}} \
/Pages inactive/ {{n+=$3}} /Pages speculative/ {{n+=$3}} \
END {{printf "mem_avail_kb=%d\\n", n*ps/1024}}'
else
  echo "ncpu=$(nproc)"
  echo "load=$(cut -d' ' -f1 /proc/loadavg)"
  # printf, not print: mawk writes large counters as 9.67e+09.
  cpu() {{
    awk '/^cpu / {{printf "%.0f %.0f\\n", $2+$3+$4+$5+$6+$7+$8+$9, $5+$6}}' \\
      /proc/stat
  }}
  set -- $(cpu); total=$1 idle=$2; sleep 0.5; set -- $(cpu)
  busy=$(( ($1 - total) - ($2 - idle) )); span=$(( $1 - total ))
  [ "$span" -gt 0 ] || span=1
  echo "cpu_pct=$(( (100 * busy + span / 2) / span ))"
  awk '/^MemTotal:/ {{print "mem_total_kb=" $2}} \
/^MemAvailable:/ {{print "mem_avail_kb=" $2}}' /proc/meminfo
fi
df -Pk "$HOME" | awk 'NR==2 {{print "disk_total_kb=" $2; \
print "disk_used_kb=" $3; gsub("%", "", $5); print "disk_pct=" $5}}'
echo {AGENTS_MARKER}
{herdr.AGENT_LIST_SHELL}
"""


def parse_machines(text):
    """Machines from ``herdr machine list`` (tab-separated, one per line).

    Columns are id, label, ssh target, session, state. Lines with fewer than
    three fields are skipped, and a repeated target keeps its first label.
    """
    machines = []
    seen = set()
    for line in text.splitlines():
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        label, target = fields[1], fields[2]
        if target in seen:
            continue
        seen.add(target)
        enabled = len(fields) < 5 or fields[4] == "enabled"
        machines.append(Machine(label, target, enabled))
    return machines


def parse_snapshot(text):
    """Facts about one host from the collector's output.

    ``key=value`` lines come first, then the marker line, then whatever
    ``herdr agent list`` printed. A missing fact raises ValueError naming
    it, and a non-numeric one raises ValueError; the agent counts are None
    when Herdr gave no usable list.
    """
    facts_text, _, agents_text = text.partition(AGENTS_MARKER)
    facts = dict(
        line.split("=", 1) for line in facts_text.splitlines() if "=" in line
    )
    try:
        total = int(facts["mem_total_kb"])
        avail = int(facts["mem_avail_kb"])
        snap = Snapshot(
            os=facts["os"],
            ncpu=int(facts["ncpu"]),
            load=float(facts["load"]),
            cpu_pct=int(facts["cpu_pct"]),
            mem_pct=0,
            mem_used_kb=total - avail,
            mem_total_kb=total,
            disk_pct=int(facts["disk_pct"]),
            disk_used_kb=int(facts["disk_used_kb"]),
            disk_total_kb=int(facts["disk_total_kb"]),
            agents=herdr.status_counts(agents_text),
        )
    except KeyError as exc:
        raise ValueError(f"collector output lacks {exc.args[0]}") from exc
    if total <= 0:
        raise ValueError("collector reported no memory")
    return snap._replace(mem_pct=round(100 * (total - avail) / total))


class HostError(RuntimeError):
    """A host could not be read. The message is the reason to show."""


def run_host(target, script, timeout=15):
    """Run ``script`` under sh on ``target`` and return its stdout.

    ``target=None`` means this machine. Remote hosts are reached with
    non-interactive SSH, so a missing key fails fast instead of prompting.
    """
    if target is None:
        argv = ["sh", "-c", script]
    else:
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                target, "sh -c " + shlex.quote(script)]
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise HostError("timeout") from exc
    except OSError as exc:
        raise HostError(str(exc)) from exc
    if done.returncode:
        lines = done.stderr.strip().splitlines()
        raise HostError(lines[0] if lines else f"exit {done.returncode}")
    return done.stdout


def collect(machine, run=None):
    """One row for ``machine``; a failure becomes the row's error."""
    run = run or run_host
    if not machine.enabled:
        return Row(machine.label, None, "disabled")
    try:
        snap = parse_snapshot(run(machine.target, COLLECT_SCRIPT))
    except HostError as exc:
        return Row(machine.label, None, str(exc))
    except ValueError as exc:
        return Row(machine.label, None, f"unreadable output: {exc}")
    return Row(machine.label, snap, None)


def poll(local_label, machines, run=None):
    """Rows for this machine (first) and every saved machine, in order.

    All hosts are read at once, so one slow host costs its own timeout
    rather than delaying the others.
    """
    every = [Machine(local_label, None, True), *machines]
    rows = [None] * len(every)

    def read(i, machine):
        rows[i] = collect(machine, run)

    # Daemon threads, so quitting never waits for a hung host's timeout.
    threads = [threading.Thread(target=read, args=(i, m), daemon=True)
               for i, m in enumerate(every)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return rows


def drill_argv(target, program="btop", pause=2):
    """The command that opens ``program`` on ``target`` (None: here).

    A host without it prints a note and waits ``pause`` seconds, so the
    note is readable before the dashboard comes back. SSH may forward no
    locale, and btop refuses to start without a UTF-8 one, so C.UTF-8 is
    set when the current locale is not UTF-8.
    """
    script = (
        "PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin; "
        'case "${LC_ALL:-${LC_CTYPE:-$LANG}}" in '
        "*[Uu][Tt][Ff]-8*|*[Uu][Tt][Ff]8*) ;; "
        "*) export LANG=C.UTF-8; unset LC_ALL LC_CTYPE;; esac; "
        f"command -v {program} >/dev/null && exec {program}; "
        f'echo "{program} is not installed on $(hostname)"; sleep {pause}'
    )
    if target is None:
        return ["sh", "-c", script]
    return ["ssh", "-t", target, "sh -c " + shlex.quote(script)]


HEADER = ("MACHINE", "CPU", "LOAD", "MEM", "DISK", "AGENTS")
# Statuses in the order that matters to a person watching: stuck first.
STATUS_ORDER = ("blocked", "working", "idle", "done", "unknown")
LIMIT_PCT = 90  # memory or disk above this is flagged


def row_level(row):
    """How a row should be drawn: down, dim, alert or ok."""
    if row.snapshot is None:
        return "dim" if row.error == "disabled" else "down"
    snap = row.snapshot
    if (snap.agents or {}).get("blocked") or (
            max(snap.mem_pct, snap.disk_pct) > LIMIT_PCT):
        return "alert"
    return "ok"


def _agents_cell(counts):
    if counts is None:
        return "-"
    if not counts:
        return "none"
    known = [s for s in STATUS_ORDER if s in counts]
    others = sorted(set(counts) - set(STATUS_ORDER))
    return ", ".join(f"{s} {counts[s]}" for s in (*known, *others))


def row_cells(row):
    """The text cells of one row; a row with no snapshot has two."""
    snap = row.snapshot
    if snap is None:
        if row.error == "disabled":
            return [row.label, "disabled"]
        return [row.label, f"down: {row.error}"]
    return [row.label, f"{snap.cpu_pct}%", f"{snap.load:.1f}/{snap.ncpu}",
            f"{snap.mem_pct}%", f"{snap.disk_pct}%",
            _agents_cell(snap.agents)]


def format_table(rows):
    """Lines of an aligned table, header first."""
    table = [HEADER, *(row_cells(r) for r in rows)]
    # Names size the first column; only full rows size the others, so a
    # long error message cannot stretch LOAD, MEM or DISK.
    full = [r for r in table if len(r) == len(HEADER)]
    widths = [max(len(r[0]) for r in table)] + [
        max(len(r[i]) for r in full) for i in range(1, len(HEADER) - 1)
    ]
    lines = []
    for cells in table:
        padded = [c.ljust(widths[i]) if i < len(widths) else c
                  for i, c in enumerate(cells)]
        lines.append("  ".join(padded).rstrip())
    return lines
