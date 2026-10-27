# Needs you

Date: 2026-10-27. Status: design, not built. Extends issue #2 ("Drill
from a machine card into its Herdr agents, blocked first") and its
comment of 22 Oct.

One list of everything, on every machine machine-stats polls, that is
waiting on you: agents that are blocked, agents that finished and you
have not looked at yet, and secret prompts that are waiting for you to
type a value. Enter jumps to the pane. The same list appears in two
places, drawn by the same code:

- a section at the top of the dashboard, and
- a popup opened by a Herdr action (bound to a key), for a quick look
  from anywhere.

Nothing new is pushed or alerted; this is a place to look, not a
notifier.

## What counts

Three groups, in this order:

| Group | Mark | Source |
|---|---|---|
| waiting on you | ◐ (red) | `herdr agent list`: `agent_status == "blocked"` |
| secret requested | 🔑 (yellow) | open secret-prompt requests (below) |
| finished, unseen | ✓ (blue) | `herdr agent list`: `agent_status == "done"` |

Within a group, the oldest wait comes first, across all machines. Ties
go by machine order (this machine first, then `herdr machine list`
order), then workspace number, then tab number.

`working`, `idle` and any other status are not listed. A blocked agent
that is itself a secret prompt (the prompt pane reports itself to Herdr
as a blocked agent) is listed once, under "secret requested", not twice.

## The status legend

One legend, used by the machine cards, this list, the popup and the
README, defined once in `render.py` (`AGENT_MARKS`, extended):

| Mark | Meaning | Style |
|---|---|---|
| ◐ | blocked: waiting on you | red |
| ● | working | green |
| ○ | idle | dim |
| ✓ | done: finished, not yet seen | blue |
| 🔑 | secret requested | yellow |
| ? | a status this plugin does not know | yellow |

These are the marks machine-stats already uses; only 🔑 is new. It is
the marker the secret prompt already puts in its tab name, so the same
request looks the same in the tab bar and here. Other plugins use other
glyphs (herdr-bar uses ◉ blocked, ◐ working, ● done); this plugin does
not follow them, because changing ◐ and ● would change the meaning of
cards people already read. The README gets a "Status marks" section
with this table, and the popup's footer shows the legend in one line.

## Layout

### One item

Wide (the list is 70 columns or more):

```
◐   12m  build-box  claude  api        workspace 5 api, tab 18 'review'
         │ Do you want to make this edit to settings.py?
         │ ❯ 1. Yes
         │   2. Yes, and don't ask again this session
```

Narrow (under 70 columns, for example a phone through herdr-web-ui):

```
◐ 12m claude · api
  build-box · ws 5 api › tab 18 'review'
  │ Do you want to make this edit to
  │ ❯ 1. Yes
```

- **Age**: how long it has waited (see "Waiting since"), `age_text`
  from `render.py` (45s, 12m, 3h05m, 2d), with a trailing `+` when it is
  a lower bound.
- **Machine**: the card's name.
- **Agent**: the agent's `name` if it has one, else `display_agent`,
  else `agent` (`claude`, `codex`).
- **Project**: the last component of the agent's `cwd`.
- **Where**: the workspace's `number` and `label` and the tab's
  `number` and `label`, exactly as Herdr's screen shows them, from
  `herdr workspace list` and `herdr tab list` joined on `workspace_id`
  and `tab_id`. Never bare ids. A tab without a label shows its number
  only.
- **Detail**: for blocked agents, the last three meaningful lines of
  the agent's screen (below); for finished agents, one line: the
  terminal title (`terminal_title_stripped`), which for Claude and
  Codex is the task they were on; for secret requests, the purpose the
  agent gave and `expires 11:42` (the host's local time).

Every piece of text that came from another program (names, labels,
titles, cwd, purposes, screen lines) is cleaned before it is drawn (see
"Cleaning text"), and cut to the room left, between words, with
`render.ellipsize`.

### The dashboard section

A section above the cards. Its height is at most a third of the screen
(at least 3 lines), so the cards keep most of the room:

```
 needs you  ◐ 2  🔑 1  ✓ 9                       ! for the full list
 ◐   12m  build-box  claude  api   workspace 5 api, tab 18 'review'
          │ ❯ 1. Yes
 🔑   3m  laptop     codex   site  workspace 2 site, tab 4 '🔑 secret…'
 ✓ 9 finished, unseen: 6 on build-box, 3 on laptop
```

- Blocked and secret items get their line and one detail line each, in
  order, while they fit; what does not fit becomes `+N more`.
- Finished items are one summary line by machine; they are listed in
  full only in the full list.
- Nothing waiting: one dim line, `nothing needs you`.
- A machine that is down or has no Herdr adds a dim line
  `? laptop: down, not counted`, so an empty list never hides a machine
  that could not be asked.

The section is not selectable. Arrows, Enter and `d` keep acting on the
cards, so the dashboard's existing keys do not change meaning.

### The full list (`!` on the dashboard, and the popup)

`!` toggles the dashboard between the cards and the full list (the idea
borrowed from herdr-bar's `!` filter). The popup always shows the full
list. In it:

- every item of the three groups, each group under a header with its
  count, and detail lines as above;
- up/down (or j/k) select an item, Enter jumps to it (below), PgUp/PgDn
  scroll, `r` refreshes, `!` goes back to the cards (dashboard), and
  `q` or Esc closes (popup) or goes back (dashboard);
- the footer shows the legend and, after a jump to another machine,
  where the pane is.

At the narrow layout, the header lines shorten to `◐ 2  🔑 1  ✓ 9` and
the footer to the keys.

## Waiting since

Herdr gives no time for a status change: `herdr agent list` has no
timestamp, and the status-change events carry none either. It does
give, per agent, `state_change_seq`, a counter that changes on every
state change. So:

- **Agents**: the age is measured from when this plugin first saw that
  pane in that status with that `state_change_seq`. If the status or the
  sequence number changes (the agent was answered and blocked again on a
  new question, or the server restarted), the clock starts again. The
  precision is one poll interval.
- **Secret requests**: exact. The request records its `created` time;
  the collector also prints the host's own clock (`now=$(date +%s)`), so
  the age is `now - created` on that host and clock skew between
  machines does not matter.

First-seen times are kept in a small local file, so the popup and the
dashboard agree and a restart does not reset every age:
`$HERDR_PLUGIN_STATE_DIR/needs.json` (outside Herdr:
`${XDG_STATE_HOME:-~/.local/state}/herdr-machine-stats/needs.json`),
mode 0600, replaced atomically under an `fcntl.flock` on a lock file
next to it. Per item, keyed by machine and pane id: status, sequence
number, first seen. Plus the time of the last update.

- Entries of a machine that answered and no longer lists them are
  dropped. Entries of a machine that did not answer are kept for an
  hour, so a network blip does not reset ages.
- When the file was last updated more than three intervals ago (or does
  not exist), nothing was watching, so items first seen in that poll
  are lower bounds and show `+` (`12m+`) for as long as they stay.
- The file holds no screen text, only ids, statuses, sequence numbers
  and times. It is never written to another machine.

Next to it, `needs-list.json` keeps the last list drawn (written by
whichever process polled last, under the same lock), so the popup can
show it at once while its own first poll runs. It holds each item's
group, machine, agent, project, where, pane id and first-seen time, and
no detail lines: no screen text and no purposes.

## "Finished, unseen" and when it becomes seen

Herdr decides. `done` is Herdr's own state: idle, but not yet seen. An
explicit `pane focus` / `agent focus` marks the agent seen, and reads do
not (Herdr's CLI reference). So:

- Enter on a finished item jumps to it, which marks it seen; on the next
  poll it is `idle` and leaves the list.
- Looking at the pane in Herdr yourself clears it the same way.
- The collector's reads (`agent list`, `agent read`) never mark
  anything seen.

machine-stats keeps no "seen" state of its own. Herdr has no call that
marks an agent seen without focusing it, so there is no "dismiss" key
(see Open decisions, D4).

## Secret requests

A secret-prompt plugin that runs in Herdr keeps one request directory
per waiting request. This view reads their metadata only, never a
secret value, and never anything but the files named here.

**Where.** The directory name is a setting, off by default, so the
public plugin looks for nothing unless you turn it on:

```toml
secret_request_dir = ""   # directory name; "" means no secret requests
```

With a name set, the collector looks for request directories in
`$XDG_RUNTIME_DIR/<name>`, `/run/user/<uid>/<name>` and
`~/.local/state/<name>`, on every host, because a non-interactive SSH
session may lack `XDG_RUNTIME_DIR`. A host without any of these simply
has no requests.

**Which directories.** A request directory is named `r-` and eight hex
digits, is a real directory (not a symlink), is less than 24 hours old
(`find <base> -mindepth 1 -maxdepth 1 -type d -name 'r-*' -mmin -1440`,
which does not follow symlinks), and is owned by the user with mode 0700
(`ls -ld`, compared with `id -un` and `drwx------`; it reads the same
on Linux and macOS). Anything else is skipped.

**What is read.** For each such directory the collector prints, after a
marker:

- `request.json`, at most 4 KB (`head -c 4096`);
- `pane.json` (the prompt pane's id) and `state.json` (the prompt's
  phase and current deadline), at most 1 KB each;
- whether `result.json` and `cancel.json` exist (`test -e`); their
  contents are not read.

Parsing happens on the dashboard side, in Python. From `request.json`
only `id`, `created`, `expires`, `pane_id`, `workspace_id` and `purpose`
are kept, and the rest is dropped at once: the secret's path and key
name are never shown, stored or logged. A file that is not a JSON object
of the expected types, or whose `id` differs from its directory name,
skips that request.

**Open or not.** A request is open when it has no `result.json` and no
`cancel.json`, and the host's `now` is before its deadline. The deadline
is `state.json`'s `deadline` while that file is fresh (its `at` is at
most 90 seconds old, or 210 seconds in the `writing` phase), else
`expires`. These are the rules the requesting side applies, so the list
and the request agree on when a request is over.

**Listed as.** Age `now - created`; agent, project and where from the
asking agent (`pane_id`, `workspace_id`, joined with the agent list);
detail: the purpose (cleaned) and `expires HH:MM`. Enter jumps to the
prompt pane (`pane.json`), whose tab sits next to the agent that asked.
The prompt pane's own blocked agent entry is matched by that pane id and
dropped from "waiting on you". Without `pane.json` (the prompt has not
opened yet), Enter jumps to the asking agent.

## Jumping to a pane

What Herdr offers, checked against Herdr 0.9.5 (`herdr --help`,
`herdr --skill`, `herdr api schema --json`, the docs linked from
herdr.dev/llms.txt):

- `herdr agent focus <target>` (`agent.focus`) focuses an agent by its
  pane id. The socket API also has `pane.focus`; the CLI's
  `herdr pane focus` only moves in a direction. `herdr tab focus` and
  `herdr workspace focus` exist too. Focusing marks a `done` agent seen.
- Focus is per server: `session.snapshot` has one focused workspace, tab
  and pane. With several clients attached "each can view its own
  workspace and tab", and no API call names a client. With one attached
  client, focusing a pane in another workspace switches that client's
  view (inferred; a popup of another plugin by the same author already
  jumps this way with `herdr tab focus`).
- Remote machines: the local Herdr window shows a saved machine's
  workspaces when you select that machine (sidebar or `prefix+w`).
  `herdr --machine <machine> agent focus <pane>` and the same command
  over SSH reach that machine's server, but "selecting a machine in the
  UI does not retarget CLI commands", and no API call changes which
  machine the local window shows. `herdr --remote <target>` opens a
  separate full client and cannot be told where to land.

So Enter does this:

- **This machine**: `herdr agent focus <pane_id>`. From the popup, the
  popup then exits, so you land on the pane. From the dashboard, the
  dashboard stays where it is, in its own pane, behind you. If the pane
  is gone, the footer says so and the list refreshes.
- **Another machine**: the same command on that machine, over the SSH
  target the stats came from (one channel, as for everything else). This
  focuses the pane on that machine's server and marks it seen there.
  Then the footer (popup: a box that stays until a key) says exactly
  where it is: `laptop: workspace 5 api, tab 18 'review'. Pick laptop
  with prefix+w`. If that machine is already selected in your window,
  you are likely already looking at it (to be checked, see Manual
  checks).

Opening a nested `herdr --remote` client in a tab was considered and
left out: it is a second full client inside the first, it cannot land
on the pane, and it leaves a tab behind to clean up.

## Getting the data

Everything rides on the existing poll: one non-interactive SSH call per
machine per interval, running the collector script. No second channel.

The collector script gains, after the agent list:

| Marker | Command | Why |
|---|---|---|
| `--workspaces--` | `herdr workspace list` | workspace numbers and labels |
| `--tabs--` | `herdr tab list` | tab numbers and labels |
| `--requests--` | the request scan above (only with `secret_request_dir` set) | secret requests |
| (fact) | `now=$(date +%s)` | the host's clock |

These are calls to the host's local Herdr socket and a directory
listing: tens of milliseconds and a few KB more per poll.

**Screen lines** are the one extra call. The collector cannot pick the
blocked panes out of the agent list in plain `sh`, so the dashboard
does: after a poll, for each blocked agent whose (machine, pane,
`state_change_seq`) it has no lines for yet, it reads them with
`herdr agent read <pane> --source visible --format text`, all panes of
one machine in one SSH call. The lines of a blocked agent do not change
while it waits on the same question, so they are read once per wait,
not once per poll. Lines are kept in memory only.

**The popup's poll** uses a light variant of the script: no CPU sample
(which sleeps half a second, a second on macOS), no plugin list; agents,
workspaces, tabs, requests and `now` only. It polls when it opens and
every 5 seconds while open. On open it first draws the last list from
`needs-list.json` (see "Waiting since"), marked `as of 12:03:10`, so it
is never empty while the first poll runs; detail lines follow with its
own poll.

**Cost.** Dashboard: unchanged number of SSH calls per interval (10 s
by default), slightly larger output, plus one SSH call per machine when
a new blocked wait appears there. Popup: one SSH call per machine on
open and every 5 seconds, each without the CPU sample.

## Cleaning text

machine-stats prints nothing from other programs today except machine
labels, so it has no cleaning yet. A new `clean(text)` in
`statslib/needs.py` is applied to every string that came from Herdr, a
request file or a screen:

- remove escape sequences: CSI (`ESC [ … final`), OSC (`ESC ] …` up to
  BEL or `ESC \`), DCS/APC/PM/SOS strings, and other two-character
  `ESC` sequences, plus their C1 forms (U+009B, U+009D and so on);
- replace tab with a space, then drop every character in Unicode
  categories Cc, Cf, Co, Cs and Cn (controls, format characters such as
  bidi overrides and zero-width joiners, private use, surrogates,
  unassigned);
- collapse runs of spaces and strip both ends.

Screen lines are read with `--format text` (Herdr already strips ANSI);
`clean` runs anyway, because the list must never pass a control
sequence to the terminal.

Width is counted in cells, not characters: East Asian wide and full
width characters (🔑 among them) count two, combining marks count zero.
The needs lines use a cell-aware variant of `render._fit`; the cards do
not change.

**Meaningful lines.** From the visible screen, drop blank lines and
lines made only of box-drawing characters, spaces and `│ ─ ╭ ╮ ╰ ╯`,
strip box-drawing borders at both ends, and keep the last three. Agent
UIs end with an input box and a status line, so the tests use real,
redacted screens of blocked Claude and Codex panes (see D5).

## Small screens

- Under 70 columns the narrow layout above is used (two header lines
  per item, detail indented two columns). Under 40 columns the detail
  lines are dropped from the dashboard section, and the full list keeps
  one.
- The dashboard section shrinks to its counts line when the screen is
  under 20 lines high.
- The popup is session-modal and has no pane id; herdr-web-ui attaches
  to pane terminals, so the popup is most likely not reachable from the
  phone. The dashboard pane is, and `!` gives the full list there.

## Code

| Where | What |
|---|---|
| `statslib/needs.py` (new) | `Item`; parsing workspaces, tabs and requests; building and ordering the list; the first-seen store; `clean`; meaningful lines |
| `statslib/collect.py` | the new markers in `COLLECT_SCRIPT`; the light script; `now`; `Snapshot.needs` (the parsed agents, workspaces, tabs, requests and host clock); `Machine` unchanged |
| `statslib/herdr.py` | shell fragments for `workspace list`, `tab list` and `agent read`, and the focus command (still the only module that names `herdr`) |
| `statslib/render.py` | the section and full-list lines; the legend in `AGENT_MARKS`; the cell-aware fit |
| `statslib/config.py` | `secret_request_dir` |
| `bin/machine-stats` | the section; `!`; the full list's keys; `--needs` (the popup); `--once --needs` (plain text, for scripts and tests) |
| `herdr-plugin.toml` | a `needs` pane (`placement = "popup"`, about 90% by 80%) and a `needs` action, "Show what needs you" |
| README | the legend, the section, the popup and its key binding, `secret_request_dir`, and the change below to "Reads are read-only" |

The README suggests a binding (`prefix+u` is free in Herdr's defaults;
see D1):

```toml
[[keys.command]]
key = "prefix+u"
type = "plugin_action"
command = "renzof.herdr-machine-stats.needs"
description = "needs you"
```

## Safety

- Reads stay read-only. The request scan reads only the files named
  above, size-capped, and keeps only the fields named above.
- One new action on other machines: Enter focuses the chosen pane there
  (and so marks it seen). AGENTS.md and the README change from "the only
  thing ever written to another machine is this plugin" to "the only
  changes made on another machine are this plugin, by an explicit
  deploy, and focusing a pane, when you press Enter on it".
- Nothing is written to another machine. The two local files hold no
  screen text and no secret metadata beyond the request id.

## Relation to other views

- **Issue #2** (drill from a card into its agents): this list covers the
  "blocked first" part across all machines. A per-machine drill-down of
  every agent remains for #2; when it is built it uses the same `Item`,
  legend and jump.
- **A coordinator attention view** (planned separately, in the owner's
  coordinator tooling): it lists coordinator-level things (crew steps,
  agent-to-agent questions, tracked sessions). This list is Herdr-level
  (panes, on every machine). They meet where a crew or question session
  is itself a blocked agent: here it is a pane to jump to, there a task
  to decide. `--once --needs` is the seam if that view wants this list
  (D3).
- **herdr-web-ui** already pushes `blocked` to the phone; this view adds
  no alerts.

## Not in scope

Alerts or push; acting on an agent (answering a prompt, typing into a
pane); a "seen" state of machine-stats' own; per-machine drill-down of
all agents (#2); a nested remote client.

## Tests

With the existing fakes (`fake_herdr`, the `hosts` fixtures, the pty
`Screen` in `test_cli.py`):

- **Parsing**: canned `agent-list`, `workspace-list` and `tab-list`
  outputs; items with and without names, labels and cwd; unknown
  statuses ignored; garbage and missing sections give no list and a
  `? machine` line, not a crash.
- **Order**: three machines, mixed groups and ages; oldest first within
  a group, groups in order, ties by machine, workspace, tab.
- **Waiting since**: same status and sequence keeps the first-seen time;
  a new sequence number restarts it; a gap of more than three intervals
  marks items `+`; a down machine keeps its entries for an hour; two
  processes updating the store at once (two threads with the lock) lose
  nothing; the file never contains screen text.
- **Secret requests**: request directories in a temp `HOME` and
  `XDG_RUNTIME_DIR`, run through the real collector script under `sh`
  (as `test_collector_output_parses_on_this_host…` does): open,
  answered (`result.json`), cancelled, expired, deadline extended by a
  fresh `state.json`, stale `state.json`, `writing` within 210 s,
  symlinked directory, wrong mode, a name that is not `r-` and eight
  hex digits, older than 24 hours, oversized
  and malformed `request.json`, `id` mismatch; the path and key never
  appear in the parsed item, the drawn lines or `needs.json`; the prompt
  pane's blocked entry is listed once; `secret_request_dir = ""` scans
  nothing (the script has no request section).
- **Cleaning**: CSI, OSC 8 links, OSC titles ended by BEL and by ST, C1
  controls, bidi overrides, zero-width joiners, tabs; cell widths of
  wide characters and combining marks; meaningful lines from redacted
  real screens of blocked Claude and Codex panes.
- **Layout**: every line exactly the width at 30, 40, 69, 70, 100 and
  160 columns; the section's height cap; `+N more`; the finished
  summary line; `nothing needs you`; the down-machine line.
- **Jump**: Enter on a local item runs `herdr agent focus <pane>` (the
  shim records argv) and the popup exits; on a remote item the focus
  command goes over SSH to that target and the location line names the
  workspace and tab by number and label; a failed focus shows the reason
  and refreshes.
- **Screen lines**: read once per (machine, pane, sequence), one SSH call
  per machine for several panes; a changed sequence reads again.
- **Keys**: in the pty, `!` toggles the full list, arrows select, Esc
  goes back; the cards' keys are unchanged in the cards view.
- **Config**: `secret_request_dir` parsing, with the same fall-back
  notes as the other settings.
- flake8 at 79 columns, as now.

## Manual checks on real Herdr

To run once at implementation, and record in the PR:

1. From the popup, `herdr agent focus` on a pane in another workspace
   switches the attached client to it and the popup closes.
2. `herdr agent focus` over SSH on another machine, with that machine
   selected in the local window: does the window show the pane? With
   another machine selected: what happens? The footer text is adjusted
   to what is seen.
3. A focused `done` agent turns `idle` on the next poll, locally and
   remotely.
4. A secret prompt waiting on another machine is listed once, with its
   expiry, and Enter lands on the prompt's tab.
5. The dashboard at phone width through herdr-web-ui: the narrow layout,
   `!`, Enter.

## Open decisions

Each has a recommendation; the design above follows it.

- **D1. Popup key.** A: suggest `prefix+u` in the README and bind
  nothing (a plugin cannot bind keys itself). B: suggest a
  shift-chord such as `prefix+shift+u`. **Rec A**: `prefix+u` is unbound
  in Herdr's defaults and in the owner's config, and one key is quicker
  for a quick look.
- **D2. Group order.** A: waiting on you, secret requested, finished.
  B: secret requested first, because a request expires and its agent is
  stuck either way. **Rec A**: both groups block an agent, and a
  request already shows its expiry; keeping blocked agents first matches
  the cards and the blocked-first idea of #2. Revisit if expired
  requests turn out to be common.
- **D3. Machine-readable output for the coordinator's attention view.**
  A: `--once --needs` prints plain text now; JSON when that view is
  built. B: add `--json` now. **Rec A** (nothing consumes JSON yet).
- **D4. A dismiss key for finished items.** Herdr has no "mark seen"
  without focus. A: none; Enter (or looking at the pane) clears them.
  B: a key that focuses the pane and comes straight back, which marks
  it seen without leaving the list. **Rec A**: B moves the server's
  focus behind your back, and on a remote machine it changes what an
  attached screen there shows.
- **D5. Where the "what it is asking" lines come from.** A: the visible
  screen, last three meaningful lines (above). B: the agent's
  `state_labels` and `title` only, no screen read. **Rec A**: labels
  rarely carry the question; keep B as the fallback when the read
  fails or yields nothing.
- **D6. Exact wait times across restarts.** A: first seen by the
  collector, persisted locally (above). B: a Herdr event hook in this
  plugin (`[[events]] on = "pane.agent_status_changed"`) on each machine
  that records the time of each change in that machine's plugin state
  directory; exact, but it needs the plugin installed everywhere and
  writes on each machine. **Rec A** for now; B later if the `+` lower
  bounds turn out to matter.
- **D7. Showing the secret's key name.** A: never; purpose and expiry
  only. B: show the key name (not the path). **Rec A**: the purpose
  says why, and the prompt itself shows the rest when you get there.
