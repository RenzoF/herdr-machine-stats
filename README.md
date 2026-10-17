# herdr-machine-stats

A [Herdr](https://herdr.dev) plugin: live CPU, memory, disk and agent status
for this machine and every machine in `herdr machine list`, one card per
machine.

```
╭─ agent-desk ───────────────── Linux · 12c ─╮╭─ MBP ─────────────────────── Darwin · 11c ─╮
│ CPU  ███░░░░░░░░░░░░░░░░░░░░  14% ▂▂▂      ││ CPU  ████░░░░░░░░░░░░░░░░░░░  17% ▂▂▂      │
│ MEM  ███████████████░░░░░░░░  64% 15/23G   ││ MEM  ██████████████████░░░░░  79% 14/18G   │
│ DISK ███████████████░░░░░░░░  64% 73/118G  ││ DISK █████████████████████░░  92% 395/460G │
│ load 2.6  ◐ 1  ● 1  ○ 7  ✓ 5               ││ load 3.5  ○ 3                              │
╰────────────────────────────────────────────╯╰────────────────────────────────────────────╯
```

- **Gauges** shade cell by cell from green through yellow to red; the
  percentage takes the colour of its band.
- **Borders**: cyan marks the selected card, yellow an alert (a blocked
  agent, or memory or disk above 90%), red a machine that is down.
- **Agents**: ◐ blocked, ● working, ○ idle, ✓ done.
- **Keys**: arrows or h/j/k/l move, Enter opens btop on the selected
  machine (over `ssh -t`), r refreshes, q quits.

Each machine is read with one non-interactive SSH call running a short
POSIX shell script (Linux and macOS); CPU is sampled over half a second.
Nothing is installed on, written to, or sent to the machines.

## Install

```bash
herdr plugin install RenzoF/herdr-machine-stats
```

Then run "Open machine stats" from Herdr's actions, or
`herdr plugin pane open --plugin renzof.herdr-machine-stats --entrypoint
dashboard --placement zoomed --focus`. Outside Herdr, run
`python3 bin/machine-stats` from a checkout; `--once` prints a plain table
and `--interval N` sets the poll interval (default 10 s).

## Requirements

- Python 3.11+ on the machine that runs the dashboard (standard library
  only).
- Key-based, non-interactive SSH to each saved machine.
- POSIX `sh` on every machine.
- `herdr` on PATH, and optionally `btop` for the drill-down. On each
  machine they are found on PATH or in `/usr/local/bin`,
  `/opt/homebrew/bin` or `~/.local/bin`.

## Development

```bash
uv run --with pytest --with flake8 python -m pytest -q
```
