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
- **Plugin line**: the last line of a card says whether this plugin is
  installed on that machine (see "Deploying to your machines").
- **Keys**: arrows or h/j/k/l move, Enter opens btop on the selected
  machine (over `ssh -t`), d deploys this plugin to the selected machine
  (deploy mode "ask"), r refreshes, q quits.

Each machine is read with one non-interactive SSH call running a short
POSIX shell script (Linux and macOS); CPU is sampled over half a second.
Reads are read-only: nothing is written to the machines. The only thing
ever installed on another machine is this plugin, by an explicit deploy,
and deploy is off by default.

## Install

```bash
herdr plugin install RenzoF/herdr-machine-stats
```

Then run "Open machine stats" from Herdr's actions, or
`herdr plugin pane open --plugin renzof.herdr-machine-stats --entrypoint
dashboard --placement zoomed --focus`. Outside Herdr, run
`python3 bin/machine-stats` from a checkout; `--once` prints a plain table
and `--interval N` sets the poll interval (default 10 s).

## Deploying to your machines

Deploy installs this plugin on the other machines from the dashboard, so
the fleet runs the same version. It is off by default. Set the mode in
`config.toml` in the plugin's config directory:

```bash
herdr plugin config-dir renzof.herdr-machine-stats
```

```toml
deploy = "ask"   # off | ask | auto
```

- `off`: never deploys. Pressing `d` says how to turn it on.
- `ask`: `d` on the selected card asks `deploy <version> to <machine>?
  y/n`; `y` installs, anything else cancels.
- `auto`: deploys to each machine that lacks the plugin or runs an older
  version, once per machine per run of the dashboard, with no key.

To keep deploy away from some machines, list their card names:

```toml
deploy_exclude = ["lab-box"]   # never deployed to, in any mode
```

An excluded machine still gets a card; its plugin line ends in
`· excluded`, and `d` on it says so. The names must match the card names
exactly. If `deploy_exclude` is not a list of names, deploy is turned off
for the run (with a note in the footer); if a name matches no machine,
auto deploy is paused with a note, so a typo never deploys to the machine
you meant to protect.

`--deploy off|ask|auto` overrides the setting for one run. A missing
`config.toml` means `off`; an unreadable file or an unknown value also
falls back to `off`, with a note in the footer.

Each card ends with a plugin line:

- `plugin current`: same version as this machine.
- `plugin older`, `plugin missing`: deploy can install.
- `plugin newer`: the machine is ahead of this one; deploy leaves it alone.
- `plugin linked`: a local checkout is linked into that Herdr; deploy
  leaves it alone.
- `plugin unknown`: the machine gave no usable plugin list (for example
  Herdr is not installed there), or its version is not a plain number.
- `plugin deploying...`: a deploy is running in the background. Each
  install is given 120 seconds.
- `plugin deployed`: the install finished. The next poll that starts
  after it (up to one interval later) replaces this with the machine's
  real state, usually `plugin current`.
- `plugin failed: <reason>`: the install failed; the reason is the first
  line of its error. It stays until the next deploy to that machine.
- `plugin refused: <reason>`: nothing was sent, for one of the reasons
  below. It stays until the next deploy to that machine.

The command run on each machine, over non-interactive SSH, is:

```bash
herdr plugin install RenzoF/herdr-machine-stats --ref <commit> --yes
```

`<commit>` is the commit this machine runs: the commit recorded by a
GitHub install, or `HEAD` of a linked checkout. For a linked checkout,
looking the commit up includes a `git fetch`; like the install, it runs in
the background, and it never prompts, so an SSH key must be usable without
a passphrase prompt (loaded in `ssh-agent`, for example). Deploy refuses,
and says why on the card (`plugin refused: <reason>`), when this machine's
copy is a linked checkout with uncommitted changes or a `HEAD` that is not
on GitHub, because the other machines could not fetch it. It never
deploys to a machine that runs a newer version or has a linked checkout;
in ask mode `d` says so in the footer. Deploy installs nothing else: no
other plugin, file or setting is touched on the other machines.

## Pipeline card

An optional extra card shows an
job-dispatcher pipeline: what each
worker is doing, whether work is moving, and whether anything needs you.
It reads the dispatcher's `/status` (JSON over HTTP) and nothing else; no
key acts on the pipeline and no worker is contacted. It is off by default.
Set the URL in `config.toml` (or pass `--pipeline URL`; `--pipeline ''`
turns it off for one run):

```toml
pipeline_url = "http://dispatcher.example:8787/status"   # default "": no card
```

```
╭─ pipeline ───────────────────────── 2 workers ─╮
│ worker-1 implement shop#630     12m claude     │
│ worker-2 review    billing#194   4m codex      │
│                                                │
│ CI 2/2  waiting 13  failed 1  cards 0          │
│ ! 1 job failed  last lease 4m ago              │
╰────────────────────────────────────────────────╯
```

- **Workers**: stage, repository#issue, how long the lease has run and the
  harness (`claude`, `codex`); a free worker says `idle` and for how long.
- **Counters**: CI slots in use, issues waiting to start, jobs that failed
  in the last 24 hours and cards waiting on a person (all repositories).
  A job's failure time is its `updated_at` if `/status` gives one;
  otherwise it counts from when the dashboard first saw it fail.
- **Borders**: red is stuck (workers idle with work waiting, a repository's
  lane gave up, the dispatcher not ok), yellow needs a person (draining, a
  held repository, cards, a failed job, an account needing attention),
  grey is fine. A dim border with `unreachable: <reason>` means the
  dispatcher did not answer within 3 seconds (for example from a machine
  that cannot reach it); that is not an alert.
- The card is not selectable, and only `http://` and `https://` URLs are
  used. The request ignores `http_proxy` and `https_proxy`. It is polled in the background at the same interval as the
  machines.

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
