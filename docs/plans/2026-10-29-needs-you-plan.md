# Needs-you list: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One list, on the dashboard and in a Herdr popup, of every agent
on every machine that waits on you (blocked, secret requested, finished
and unseen), oldest first, with Enter jumping to the pane.

**Architecture:** The existing collector script gains workspace, tab and
secret-request sections and the host's clock; a light variant (no CPU
sample, no plugin list) feeds the popup. New pure modules turn a poll's
rows into ordered items (`needs.py`), keep first-seen times in a local
file (`seen.py`), clean and measure text (`text.py`), parse secret
requests (`prompts.py`), draw the list (`needsview.py`) and jump
(`jump.py`). `bin/machine-stats` draws the section above the cards, a
full list on `!`, and the popup with `--needs`.

**Tech Stack:** Python 3.11+, standard library only (curses, json,
fcntl, tomllib, unicodedata), POSIX `sh` on every host, pytest + flake8.

**Spec:** `docs/specs/2026-10-27-needs-you-design.md` (decisions D1 to
D7 all taken as option A). Read it before starting; this plan argues
from it.

**Checked:** on 29 Oct 2026 every task was applied as written to a
throwaway clone; with the corrections now folded in, the full suite
passed (444 tests, flake8 clean) and the end-to-end needs tests passed
three runs out of three.

## Global Constraints

- Python 3.11+, standard library only.
- Tests: `uv run --with pytest --with flake8 python -m pytest -q`; flake8
  at 79 columns is enforced by `tests/test_lint.py`, so every task's
  code must pass it.
- Only `statslib/herdr.py` names the `herdr` CLI (shell fragments and
  argv included).
- Hosts run POSIX `sh` only: no Python, jq or GNU-only flags in anything
  that runs on a host. `find -mindepth/-maxdepth/-mmin`, `head -c`,
  `ls -ld`, `id -u`, `id -un`, `date +%s` are fine on Linux and macOS.
- Reads stay read-only. The only new action on another machine is
  `herdr agent focus <pane>` when you press Enter. Nothing is written to
  another machine.
- From a request directory, only `request.json` (4096 bytes max),
  `pane.json` and `state.json` (1024 bytes max) are read, and only the
  existence of `result.json` and `cancel.json` is tested. Only `id`,
  `created`, `expires`, `pane_id`, `workspace_id` and `purpose` are kept
  from `request.json`; the secret's path and key name are never kept,
  shown, stored or logged (D7).
- The local state files (`needs.json`, `needs-list.json`) hold no screen
  text and no purposes.
- The repository is public: no internal IP addresses, real host names,
  Vault paths or private repository names in code, tests, fixtures,
  docs or commit messages. Use `laptop`, `build-box`,
  `me@laptop.example`, `secret-prompt`, `example/app`.
- Commits follow the repo's style (`✨ feat(needs): …`, `📝 docs: …`,
  `🔖 chore: …`) and carry no AI attribution trailer or line.
- No deploy, no push of implementation without review, and never touch
  an installed or linked copy of the plugin elsewhere.
- Status legend (spec "The status legend"): ◐ blocked red, ● working
  green, ○ idle dim, ✓ done blue, 🔑 secret requested yellow, ? unknown
  yellow.
- Popup key suggested in the README: `prefix+u` (D1). Group order:
  blocked, secret, done (D2). `--once --needs` is plain text, no JSON
  (D3). No dismiss key (D4). Detail = last three meaningful lines of the
  visible screen, labels/title as fallback (D5). Ages = first seen by the
  collector, persisted locally (D6).

## Deviation from the spec

The spec's code table puts the parsed needs data on `Snapshot.needs`.
This plan puts it on `Row.needs` instead (a fourth field defaulting to
`None`), because the popup's light poll has no stats and so no
`Snapshot`. Task 12 updates the spec's table to match.

## File map

| File | Status | Responsibility |
|---|---|---|
| `statslib/text.py` | new | `clean`, `cells`, `cut`, `pad`, `meaningful` |
| `statslib/config.py` | modify | `load_secret_request_dir` |
| `statslib/herdr.py` | modify | `agents`, `workspaces`, `tabs`, list shells, `read_shell`, `screens`, `focus`, `focus_shell` |
| `statslib/collect.py` | modify | `PATH_LINE`, markers, `script()`, `sections()`, `Row.needs`, `collect`/`poll` options, `read_screens` |
| `statslib/prompts.py` | new | secret-request scan shell, parse, open rules, `finite` |
| `statslib/needs.py` | new | `Raw`, `parse_raw`, `Where`, `Item`, `Note`, `build`, `order`, `Screens` |
| `statslib/seen.py` | new | `state_dir`, `Store` (first-seen stamps, cached list) |
| `statslib/render.py` | modify | `SECRET_MARK`, `LEGEND` |
| `statslib/needsview.py` | new | item lines, dashboard section, full list, legend, plain text |
| `statslib/jump.py` | new | Enter: focus here or on the item's machine |
| `bin/machine-stats` | modify | section, `!` full list, Enter, `--needs` popup, `--once --needs` |
| `herdr-plugin.toml` | modify | `needs` pane and action; version 0.5.0 |
| `README.md`, `AGENTS.md` | modify | legend, list, popup, setting, safety wording |
| `tests/test_text.py`, `tests/test_prompts.py`, `tests/test_needs.py`, `tests/test_seen.py`, `tests/test_needsview.py`, `tests/test_herdr_reads.py`, `tests/test_needs_cli.py` | new | tests per module, and end to end |

---

### Task 1: Cleaning and measuring text

**Files:**
- Create: `statslib/text.py`
- Test: `tests/test_text.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `clean(value) -> str` (any value; non-strings give `""`),
  `cells(value: str) -> int`, `cut(value: str, room: int) -> str`,
  `pad(value: str, width: int) -> str` (exactly `width` cells),
  `meaningful(lines: list[str], keep=3) -> list[str]`, `BOX: str`.

- [ ] **Step 1: Write the failing tests**

```python
"""statslib.text: cleaning and measuring text from other programs."""

import pytest

from statslib import text


@pytest.mark.parametrize("raw, want", [
    ("\x1b[1;31mred\x1b[0m", "red"),
    ("\x1b]8;;https://example.com\x1b\\link\x1b]8;;\x1b\\", "link"),
    ("\x1b]0;a title\x07after", "after"),
    ("\x9b31mc1\x9bm", "c1"),
    ("\x1bPdcs payload\x1b\\kept", "kept"),
    ("\x1b(Bplain", "plain"),
    ("a‮b‍c", "abc"),
    ("tab\there", "tab here"),
    ("bell\x07 and nul\x00", "bell and nul"),
    ("  many   spaces  ", "many spaces"),
    ("line\nbreak", "linebreak"),
])
def test_clean_removes_escape_sequences_and_control_characters(raw, want):
    assert text.clean(raw) == want


@pytest.mark.parametrize("value", [None, 3, ["x"], {"a": 1}])
def test_clean_turns_anything_but_a_string_into_nothing(value):
    assert text.clean(value) == ""


@pytest.mark.parametrize("value, width", [
    ("abc", 3), ("🔑 key", 6), ("é", 1), ("日本", 4), ("◐ ● ✓", 5),
])
def test_cells_counts_terminal_columns(value, width):
    assert text.cells(value) == width


def test_cut_keeps_what_fits():
    assert text.cut("short", 10) == "short"


def test_cut_breaks_between_words_and_ends_with_one_ellipsis():
    assert text.cut("one two three", 9) == "one two…"


def test_cut_splits_a_word_when_no_whole_word_fits():
    assert text.cut("abcdefghij", 5) == "abcd…"


def test_cut_counts_wide_characters():
    assert text.cut("🔑🔑🔑", 5) == "🔑🔑…"


def test_cut_with_no_room_is_empty():
    assert text.cut("abc", 0) == ""


def test_pad_fills_or_cuts_to_exactly_the_width():
    assert text.pad("🔑", 4) == "🔑  "
    assert text.pad("toolong", 4) == "too…"
    assert text.cells(text.pad("🔑 secret wanted", 7)) == 7


def test_meaningful_keeps_the_last_three_lines_that_say_something():
    screen = [
        "╭──────────────────────────────╮",
        "│ Do you want to edit app.py?  │",
        "│ ❯ 1. Yes                     │",
        "│   2. No                      │",
        "",
        "╰──────────────────────────────╯",
        "   ",
    ]
    assert text.meaningful(screen) == [
        "Do you want to edit app.py?", "❯ 1. Yes", "2. No"]


def test_meaningful_cleans_each_line_and_keeps_fewer_when_asked():
    assert text.meaningful(["\x1b[1mfirst\x1b[0m", "second"], keep=1) == [
        "second"]
    assert text.meaningful([]) == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_text.py`
Expected: FAIL, `ImportError: cannot import name 'text' from 'statslib'`.

- [ ] **Step 3: Write `statslib/text.py`**

```python
"""Text from other programs, made safe and measured for the terminal.

Everything the needs-you list shows came from Herdr, a request file or
an agent's screen. ``clean`` removes what a terminal would act on;
``cells``, ``cut`` and ``pad`` measure in terminal columns, so a wide
character such as 🔑 takes two.
"""

import re
import unicodedata

_SEQUENCES = re.compile(
    r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]"           # CSI
    r"|(?:\x1b[\]PX^_]|[\x90\x98\x9d\x9e\x9f])"   # OSC DCS SOS PM APC,
    r"[^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)?"      # up to BEL or ST
    r"|\x1b[ -/]*[0-~]"                           # other ESC sequences
)
# Controls, format characters (bidi overrides, zero-width joiners),
# private use, surrogates and unassigned code points.
_DROPPED = {"Cc", "Cf", "Co", "Cs", "Cn"}
# Box drawing that agent UIs put around their prompts.
BOX = "─━│┃┄┅┆┇┈┉┊┋┌┐└┘├┤┬┴┼╭╮╯╰═║╔╗╚╝╠╣╦╩╬▁▔"


def clean(value):
    """``value`` as one line of plain text; anything but a string is
    ``""``."""
    if not isinstance(value, str):
        return ""
    value = _SEQUENCES.sub("", value).replace("\t", " ")
    kept = "".join(c for c in value
                   if unicodedata.category(c) not in _DROPPED)
    return " ".join(kept.split())


def cells(value):
    """The terminal columns ``value`` takes."""
    total = 0
    for char in value:
        if unicodedata.category(char) in ("Mn", "Me", "Cf"):
            continue
        total += 2 if unicodedata.east_asian_width(char) in "WF" else 1
    return total


def _prefix(value, room):
    """The longest start of ``value`` within ``room`` cells."""
    used = 0
    for i, char in enumerate(value):
        used += cells(char)
        if used > room:
            return value[:i]
    return value


def cut(value, room):
    """``value`` within ``room`` cells: cut between words and ended with
    one ellipsis; a word is split only when no whole word fits."""
    if cells(value) <= room:
        return value
    if room < 1:
        return ""
    kept = ""
    for word in value.split(" "):
        longer = f"{kept} {word}" if kept else word
        if cells(longer) > room - 1:
            break
        kept = longer
    if not kept:
        kept = _prefix(value, room - 1)
    return kept.rstrip(" ,;:(") + "…"


def pad(value, width):
    """``value`` cut or padded with spaces to exactly ``width`` cells."""
    value = cut(value, width)
    return value + " " * (width - cells(value))


def meaningful(lines, keep=3):
    """The last ``keep`` lines of a screen that say something: cleaned,
    box-drawing borders stripped, blank and border-only lines dropped."""
    kept = []
    for line in lines:
        line = clean(line).strip(BOX + " ")
        if line:
            kept.append(line)
    return kept[-keep:] if keep > 0 else []
```

- [ ] **Step 4: Run the tests**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_text.py tests/test_lint.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add statslib/text.py tests/test_text.py
git commit -m "✨ feat(needs): clean and measure text from other programs"
```

---

### Task 2: The `secret_request_dir` setting

**Files:**
- Modify: `statslib/config.py` (module docstring; new function after
  `load_pipeline_url`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.load_secret_request_dir(directory) -> (str, str |
  None)`: the directory name (`""` = look for no requests) and a note
  when a bad value was ignored.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_config.py`)

```python
def test_no_secret_request_dir_by_default(tmp_path):
    assert config.load_secret_request_dir(tmp_path) == ("", None)
    (tmp_path / "config.toml").write_text('deploy = "ask"\n')
    assert config.load_secret_request_dir(tmp_path) == ("", None)


def test_the_secret_request_dir_name_is_read(tmp_path):
    (tmp_path / "config.toml").write_text(
        'secret_request_dir = "secret-prompt"\n')
    assert config.load_secret_request_dir(tmp_path) == (
        "secret-prompt", None)


@pytest.mark.parametrize("value", [
    '"../x"', '"a/b"', '".."', '"."', '"a b"', "3", '["x"]'])
def test_a_bad_secret_request_dir_is_reported_and_ignored(tmp_path,
                                                          value):
    (tmp_path / "config.toml").write_text(f"secret_request_dir = {value}\n")
    name, note = config.load_secret_request_dir(tmp_path)
    assert name == "" and "secret_request_dir" in note


def test_broken_toml_gives_no_secret_requests_quietly(tmp_path):
    (tmp_path / "config.toml").write_text("deploy = \n")
    # load() already reports the unreadable file.
    assert config.load_secret_request_dir(tmp_path) == ("", None)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_config.py`
Expected: FAIL, `AttributeError: module 'statslib.config' has no
attribute 'load_secret_request_dir'`.

- [ ] **Step 3: Implement**

Add the line `    secret_request_dir = ""   # secret prompt's request dir
name; "" none` (one line, 4-space indent, as the others) to the module
docstring's list, `import re` at the
top, and:

```python
DIR_NAME = re.compile(r"[A-Za-z0-9._-]+")


def load_secret_request_dir(directory):
    """(name, note): the directory name under which a secret-prompt
    plugin keeps its requests; "" means none are looked for."""
    path = Path(directory) / "config.toml"
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return "", None
    except (OSError, tomllib.TOMLDecodeError):
        return "", None  # load() already says the file is unreadable
    name = data.get("secret_request_dir", "")
    if name == "":
        return "", None
    if (not isinstance(name, str) or not DIR_NAME.fullmatch(name)
            or name in (".", "..")):
        return "", ("secret_request_dir must be a directory name; "
                    "no secret requests")
    return name, None
```

- [ ] **Step 4: Run the tests**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_config.py tests/test_lint.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add statslib/config.py tests/test_config.py
git commit -m "✨ feat(needs): secret_request_dir setting, off by default"
```

---

### Task 3: Workspaces, tabs and the host's clock in the poll

**Files:**
- Modify: `statslib/herdr.py` (after `status_counts`)
- Modify: `statslib/collect.py` (script, markers, `sections`, `Row`,
  `parse_snapshot`, `collect`, `poll`)
- Create: `statslib/needs.py` (only `Raw` and `parse_raw` in this task)
- Test: `tests/test_herdr_reads.py` (new), `tests/test_collect.py`

**Interfaces:**
- Produces in `herdr`: `WORKSPACE_LIST_SHELL`, `TAB_LIST_SHELL`,
  `agents(text) -> list[dict] | None`,
  `workspaces(text) -> dict[str, (int, str)] | None`,
  `tabs(text) -> dict[str, (int, str)] | None`.
- Produces in `collect`: `PATH_LINE`, `WORKSPACES_MARKER`,
  `TABS_MARKER`, `REQUESTS_MARKER`, `script(stats=True,
  request_dir="") -> str`, `COLLECT_SCRIPT == script()`,
  `sections(text) -> dict` with keys `facts`, `agents`, `workspaces`,
  `tabs`, `requests`, `plugin` (missing ones absent),
  `Row = namedtuple("Row", "label snapshot error needs",
  defaults=(None,))`, `collect(machine, run=None, stats=True,
  request_dir="")`, `poll(local_label, machines, run=None, stats=True,
  request_dir="")`.
- Produces in `needs`: `Raw = namedtuple("Raw", "now agents workspaces
  tabs requests")` (`now`: the host's epoch seconds or None;
  `requests`: list, empty until Task 4), `parse_raw(parts) -> Raw`.

- [ ] **Step 1: Write the failing tests**

`tests/test_herdr_reads.py`:

```python
"""statslib.herdr: the agent, workspace and tab reads the list needs."""

import json

import pytest

from statslib import herdr

WORKSPACES = json.dumps({"id": "x", "result": {"workspaces": [
    {"workspace_id": "w1", "number": 5, "label": "api"},
    {"workspace_id": "w2", "number": 2},
    {"workspace_id": "w3", "label": "no number"},
    "not a workspace",
]}})
TABS = json.dumps({"result": {"tabs": [
    {"tab_id": "w1:t3", "workspace_id": "w1", "number": 18,
     "label": "review"},
    {"tab_id": "w1:t4", "workspace_id": "w1", "number": True},
]}})


def test_workspaces_by_id_with_number_and_label():
    assert herdr.workspaces(WORKSPACES) == {"w1": (5, "api"), "w2": (2, "")}


def test_tabs_by_id_skip_entries_without_a_real_number():
    assert herdr.tabs(TABS) == {"w1:t3": (18, "review")}


@pytest.mark.parametrize("text", [
    "", "garbage", "{}", '{"result": {}}', '{"result": {"tabs": 3}}'])
def test_unusable_lists_are_none(text):
    assert herdr.workspaces(text) is None
    assert herdr.tabs(text) is None
    assert herdr.agents(text) is None


def test_agents_are_the_dicts_of_the_agent_list():
    text = json.dumps({"result": {"agents": [
        {"pane_id": "w1:p2", "agent_status": "blocked"}, 7]}})
    assert herdr.agents(text) == [
        {"pane_id": "w1:p2", "agent_status": "blocked"}]
```

Append to `tests/test_collect.py` (and change the expected calls in
`test_collector_output_parses_on_this_host_and_asks_herdr_for_agents`
to `["agent list", "workspace list", "tab list", "plugin list --plugin
renzof.herdr-machine-stats --json"]`):

```python
WORKSPACE_LIST = (
    '{"result":{"workspaces":[{"workspace_id":"w1","number":5,'
    '"label":"api"}]}}')
TAB_LIST = (
    '{"result":{"tabs":[{"tab_id":"w1:t3","workspace_id":"w1",'
    '"number":18,"label":"review"}]}}')


def test_the_light_script_reads_agents_and_places_without_stats(
        fake_herdr):
    shim, calls, canned = fake_herdr
    (canned / "agent-list").write_text(AGENT_LIST)
    (canned / "workspace-list").write_text(WORKSPACE_LIST)
    (canned / "tab-list").write_text(TAB_LIST)
    env = dict(os.environ, PATH=f"{shim.parent}{os.pathsep}"
               f"{os.environ['PATH']}")
    began = time.time()
    done = subprocess.run(["sh", "-c", collect.script(stats=False)],
                          env=env, capture_output=True, text=True,
                          timeout=30)
    assert done.returncode == 0, done.stderr
    assert "cpu_pct" not in done.stdout
    raw = needs.parse_raw(collect.sections(done.stdout))
    assert abs(raw.now - began) < 5
    assert [a["agent_status"] for a in raw.agents] == ["idle", "blocked"]
    assert raw.workspaces == {"w1": (5, "api")}
    assert raw.tabs == {"w1:t3": (18, "review")}
    assert raw.requests == []
    assert calls.read_text().splitlines() == [
        "agent list", "workspace list", "tab list"]


def test_sections_split_only_at_whole_marker_lines():
    parts = collect.sections(
        "now=5\nos=Linux\n--agents--\n{}\n--tabs--\nx --plugin-- y\n")
    assert parts == {"facts": "now=5\nos=Linux", "agents": "{}",
                     "tabs": "x --plugin-- y"}


def test_the_default_script_is_the_full_collector_script():
    assert collect.script() == collect.COLLECT_SCRIPT
    assert collect.WORKSPACES_MARKER in collect.COLLECT_SCRIPT
    assert collect.REQUESTS_MARKER not in collect.COLLECT_SCRIPT


def test_a_light_collect_gives_a_row_with_needs_and_no_snapshot():
    out = ("now=100\n--agents--\n" + AGENT_LIST + "\n--workspaces--\n"
           + WORKSPACE_LIST + "\n--tabs--\n" + TAB_LIST + "\n")
    run = Runner(out)
    row = collect.collect(machine(), run, stats=False)
    assert run.calls == [(machine().target, collect.script(stats=False))]
    assert row.snapshot is None and row.error is None
    assert row.needs.now == 100 and len(row.needs.agents) == 2


def test_a_full_collect_also_gives_needs():
    row = collect.collect(machine(), Runner(SNAPSHOT))
    assert row.snapshot is not None
    assert row.needs.agents is not None
```

Change the test module's `from statslib import collect, herdr` to
`from statslib import collect, herdr, needs` (`time` is already
imported).

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_herdr_reads.py tests/test_collect.py`
Expected: FAIL (missing `herdr.workspaces`, `collect.script`,
`statslib.needs`).

- [ ] **Step 3: Implement the herdr reads** (in `statslib/herdr.py`,
  after `status_counts`)

```python
WORKSPACE_LIST_SHELL = "herdr workspace list 2>/dev/null"
TAB_LIST_SHELL = "herdr tab list 2>/dev/null"


def _result_list(text, key):
    """The dicts in ``result[key]`` of a herdr JSON answer, or None."""
    try:
        items = json.loads(text)["result"][key]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(items, list):
        return None
    return [item for item in items if isinstance(item, dict)]


def _numbered(items, id_field):
    """{id: (number, label)}: the numbers and labels Herdr's screen
    shows. Entries without a string id or an integer number are
    skipped."""
    if items is None:
        return None
    found = {}
    for item in items:
        ident, number = item.get(id_field), item.get("number")
        if (isinstance(ident, str) and isinstance(number, int)
                and not isinstance(number, bool)):
            label = item.get("label")
            found[ident] = (number, label if isinstance(label, str) else "")
    return found


def agents(text):
    """The agents in ``herdr agent list`` output; None when unusable."""
    return _result_list(text, "agents")


def workspaces(text):
    """{workspace_id: (number, label)} from ``herdr workspace list``."""
    return _numbered(_result_list(text, "workspaces"), "workspace_id")


def tabs(text):
    """{tab_id: (number, label)} from ``herdr tab list``."""
    return _numbered(_result_list(text, "tabs"), "tab_id")
```

- [ ] **Step 4: Create `statslib/needs.py` with `Raw` and `parse_raw`**

```python
"""The needs-you list: what waits on you, on every machine.

``parse_raw`` reads one host's part of the collector output; later
functions turn rows into ordered items. What each group means is in
docs/specs/2026-10-27-needs-you-design.md.
"""

from collections import namedtuple

from statslib import herdr

# One host's needs data: its clock (epoch seconds, or None), the agent
# list, {workspace_id: (number, label)}, {tab_id: (number, label)} and
# its open secret requests.
Raw = namedtuple("Raw", "now agents workspaces tabs requests")


def parse_raw(parts):
    """A ``Raw`` from ``collect.sections`` of one host's output."""
    facts = dict(line.split("=", 1)
                 for line in parts.get("facts", "").splitlines()
                 if "=" in line)
    try:
        now = int(facts.get("now", ""))
    except ValueError:
        now = None
    return Raw(now, herdr.agents(parts.get("agents", "")),
               herdr.workspaces(parts.get("workspaces", "")),
               herdr.tabs(parts.get("tabs", "")), [])
```

- [ ] **Step 5: Rework `statslib/collect.py`**

1. Add, below the imports: `from statslib import PLUGIN_ID, herdr,
   needs` (replacing the existing `from statslib import PLUGIN_ID,
   herdr`).
2. Replace `Row = namedtuple("Row", "label snapshot error")` with:

```python
# One dashboard row: a snapshot (None in a light poll or when the host
# could not be read), the reason there is none, and the host's needs
# data (needs.Raw; None when it could not be read).
Row = namedtuple("Row", "label snapshot error needs", defaults=(None,))
```

3. Replace the single `COLLECT_SCRIPT` f-string with a plain string
   `STATS_SCRIPT` holding the lines from `os=$(uname -s)` through the
   `df -Pk "$HOME" | awk …` line, verbatim, except that the doubled
   braces of the f-string become single braces (`{{print $2}}` becomes
   `{print $2}`, `cpu() {{` becomes `cpu() {`, and so on), and add:

```python
PATH_LINE = "PATH=$PATH:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin"
WORKSPACES_MARKER = "--workspaces--"
TABS_MARKER = "--tabs--"
REQUESTS_MARKER = "--requests--"
MARKERS = {AGENTS_MARKER: "agents", WORKSPACES_MARKER: "workspaces",
           TABS_MARKER: "tabs", REQUESTS_MARKER: "requests",
           PLUGIN_MARKER: "plugin"}


def script(stats=True, request_dir=""):
    """The collector: the host's clock, then (with ``stats``) the facts
    parse_snapshot reads, Herdr's agent, workspace and tab lists, the
    open secret requests when ``request_dir`` names their directory,
    and (with ``stats``) this plugin's entry in the plugin list, each
    after its marker. POSIX sh, for Linux and macOS."""
    lines = [PATH_LINE, 'echo "now=$(date +%s)"']
    if stats:
        lines.append(STATS_SCRIPT)
    # "echo;" first: a herdr answer without a final newline must not
    # put the next marker on its line.
    lines += [f"echo; echo {AGENTS_MARKER}", herdr.AGENT_LIST_SHELL,
              f"echo; echo {WORKSPACES_MARKER}",
              herdr.WORKSPACE_LIST_SHELL,
              f"echo; echo {TABS_MARKER}", herdr.TAB_LIST_SHELL]
    if stats:
        lines += [f"echo; echo {PLUGIN_MARKER}",
                  herdr.plugin_list_shell(PLUGIN_ID)]
    return "\n".join(lines) + "\n"


COLLECT_SCRIPT = script()


def sections(text):
    """The parts of collector output: ``facts`` before the first marker,
    then one entry per marker line found (agents, workspaces, ...)."""
    parts, name, lines = {}, "facts", []
    for line in text.splitlines():
        if line.strip() in MARKERS:
            parts[name] = "\n".join(lines)
            name, lines = MARKERS[line.strip()], []
        else:
            lines.append(line)
    parts[name] = "\n".join(lines)
    return parts
```

   Task 4 inserts the request section into `script()`; leave
   `request_dir` unused here.

4. In `parse_snapshot`, replace the two `partition` lines with:

```python
    parts = sections(text)
    facts_text = parts.get("facts", "")
    agents_text = parts.get("agents", "")
    plugin_text = parts.get("plugin", "")
```

5. Replace `collect` and `poll` with:

```python
def collect(machine, run=None, stats=True, request_dir=""):
    """One row for ``machine``; a failure becomes the row's error.

    Without ``stats`` (the popup's light poll) the row has needs data
    and no snapshot.
    """
    run = run or run_host
    if not machine.enabled:
        return Row(machine.label, None, "disabled")
    try:
        text = run(machine.target, script(stats, request_dir))
        snap = parse_snapshot(text) if stats else None
    except HostError as exc:
        return Row(machine.label, None, str(exc))
    except ValueError as exc:
        return Row(machine.label, None, f"unreadable output: {exc}")
    return Row(machine.label, snap, None, needs.parse_raw(sections(text)))


def poll(local_label, machines, run=None, stats=True, request_dir=""):
    """Rows for this machine (first) and every saved machine, in order.

    All hosts are read at once, so one slow host costs its own timeout
    rather than delaying the others.
    """
    every = [Machine(local_label, None, True), *machines]
    rows = [None] * len(every)

    def read(i, machine):
        rows[i] = collect(machine, run, stats, request_dir)

    # Daemon threads, so quitting never waits for a hung host's timeout.
    threads = [threading.Thread(target=read, args=(i, m), daemon=True)
               for i, m in enumerate(every)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return rows
```

6. Update the module docstring: a poll also prints the host's clock and
   Herdr's workspace and tab lists.

- [ ] **Step 6: Run the whole suite**

Run: `uv run --with pytest --with flake8 python -m pytest -q`
Expected: PASS (the existing collector-on-this-host and macOS tests
prove `STATS_SCRIPT` still works).

- [ ] **Step 7: Commit**

```bash
git add statslib/herdr.py statslib/collect.py statslib/needs.py \
  tests/test_herdr_reads.py tests/test_collect.py
git commit -m "✨ feat(needs): poll workspaces, tabs and the host clock; a light script"
```

---

### Task 4: Secret requests, metadata only

**Files:**
- Create: `statslib/prompts.py`
- Modify: `statslib/collect.py` (`script()`), `statslib/needs.py`
  (`parse_raw`)
- Test: `tests/test_prompts.py`

**Interfaces:**
- Consumes: `collect.script`, `needs.parse_raw` (Task 3).
- Produces: `prompts.scan_shell(name) -> str`,
  `prompts.parse(text, now) -> list[Request]`,
  `prompts.Request = namedtuple("Request", "id created deadline pane_id
  workspace_id purpose prompt_pane")` (times are the host's epoch
  seconds; `prompt_pane` is None until the prompt opened),
  `prompts.finite(value) -> bool`. `script(request_dir=name)` includes
  the scan after `--requests--`; `Raw.requests` is filled.

- [ ] **Step 1: Write the failing tests**

```python
"""statslib.prompts: open secret requests, from their metadata only."""

import json
import os
import subprocess
import time

import pytest

from statslib import collect, needs, prompts

NAME = "secret-prompt"
RID = "r-0123abcd"


def make_request(base, rid=RID, **fields):
    """A request directory as a secret prompt writes it."""
    top = base / NAME
    top.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(top, 0o700)
    rdir = top / rid
    rdir.mkdir(mode=0o700)
    os.chmod(rdir, 0o700)
    now = time.time()
    request = {"id": rid, "path": "example/app", "key": "api_token",
               "purpose": "deploy the example app", "multiline": False,
               "host": "box", "pane_id": "w1:p2", "workspace_id": "w1",
               "created": now - 120, "expires": now + 600,
               "seen_version": 0}
    request.update(fields)
    (rdir / "request.json").write_text(json.dumps(request))
    return rdir


def scan(home, runtime=None):
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    if runtime is not None:
        env["XDG_RUNTIME_DIR"] = str(runtime)
    done = subprocess.run(["sh", "-c", prompts.scan_shell(NAME)],
                          env=env, capture_output=True, text=True,
                          timeout=20)
    assert done.returncode == 0, done.stderr
    return done.stdout


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "home"
    path.mkdir()
    return path


def state_base(home):
    return home / ".local" / "state"


def found(home, runtime=None):
    return prompts.parse(scan(home, runtime), time.time())


def test_an_open_request_is_found_with_only_its_metadata(home):
    make_request(state_base(home))
    [req] = found(home)
    assert req.id == RID and req.pane_id == "w1:p2"
    assert req.workspace_id == "w1"
    assert req.purpose == "deploy the example app"
    assert req.prompt_pane is None
    assert "example/app" not in repr(req) and "api_token" not in repr(req)


def test_the_prompt_pane_comes_from_pane_json(home):
    rdir = make_request(state_base(home))
    (rdir / "pane.json").write_text('{"pane_id": "w1:p9"}')
    assert found(home)[0].prompt_pane == "w1:p9"


@pytest.mark.parametrize("name", ["result.json", "cancel.json"])
def test_an_answered_or_cancelled_request_is_not_open(home, name):
    rdir = make_request(state_base(home))
    (rdir / name).write_text('{"status": "stored"}')
    assert found(home) == []


def test_the_scan_never_prints_a_result_file(home):
    rdir = make_request(state_base(home))
    (rdir / "result.json").write_text("NOT-FOR-THE-DASHBOARD")
    (rdir / "other.txt").write_text("NOT-FOR-THE-DASHBOARD")
    assert "NOT-FOR-THE-DASHBOARD" not in scan(home)


def test_an_expired_request_is_not_open(home):
    make_request(state_base(home), expires=time.time() - 1)
    assert found(home) == []


@pytest.mark.parametrize("phase, age, listed", [
    ("typing", 10, True),     # fresh: its deadline counts
    ("typing", 100, False),   # older than 90 s: expires counts
    ("writing", 150, True),   # writing stays fresh for 210 s
    ("writing", 220, False),
])
def test_a_fresh_state_file_moves_the_deadline(home, phase, age, listed):
    now = time.time()
    rdir = make_request(state_base(home), expires=now - 1)
    (rdir / "state.json").write_text(json.dumps(
        {"phase": phase, "deadline": now + 300, "at": now - age}))
    reqs = found(home)
    assert bool(reqs) is listed
    if listed:
        assert abs(reqs[0].deadline - (now + 300)) < 1


def test_runtime_and_state_directories_are_both_scanned_once_each(
        home, tmp_path):
    runtime = tmp_path / "run"
    runtime.mkdir(mode=0o700)
    make_request(runtime, rid="r-11111111")
    make_request(state_base(home), rid="r-22222222")
    make_request(state_base(home), rid="r-11111111")  # the same request
    assert sorted(r.id for r in found(home, runtime)) == [
        "r-11111111", "r-22222222"]


def test_a_symlinked_request_directory_is_skipped(home, tmp_path):
    real = make_request(tmp_path / "elsewhere")
    base = state_base(home) / NAME
    base.mkdir(parents=True, mode=0o700)
    (base / RID).symlink_to(real)
    assert found(home) == []


def test_a_directory_others_can_read_is_skipped(home):
    rdir = make_request(state_base(home))
    os.chmod(rdir, 0o750)
    assert found(home) == []


@pytest.mark.parametrize("rid", ["r-xyz", "r-0123abcd0", "x-0123abcd"])
def test_a_directory_not_named_like_a_request_is_skipped(home, rid):
    make_request(state_base(home), rid=rid, id=rid)
    assert found(home) == []


def test_a_request_older_than_a_day_is_skipped(home):
    rdir = make_request(state_base(home))
    old = time.time() - 25 * 3600
    os.utime(rdir, (old, old))
    assert found(home) == []


@pytest.mark.parametrize("fields", [
    {"created": "soon"}, {"expires": True}, {"pane_id": 7},
    {"id": "r-ffffffff"}, {"purpose": "x" * 5000},
])
def test_a_malformed_or_oversized_request_is_skipped(home, fields):
    make_request(state_base(home), **fields)
    assert found(home) == []


def test_text_that_is_not_json_is_skipped(home):
    rdir = make_request(state_base(home))
    (rdir / "request.json").write_text("not json")
    assert found(home) == []


def test_the_collector_reports_requests_only_when_asked(
        fake_herdr, home, monkeypatch):
    shim, _calls, _canned = fake_herdr
    make_request(state_base(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    env = dict(os.environ, PATH=f"{shim.parent}{os.pathsep}"
               f"{os.environ['PATH']}")

    def raw(request_dir):
        out = subprocess.run(
            ["sh", "-c", collect.script(False, request_dir)], env=env,
            capture_output=True, text=True, timeout=30).stdout
        return needs.parse_raw(collect.sections(out))

    assert [r.id for r in raw(NAME).requests] == [RID]
    assert raw("").requests == []
    assert collect.REQUESTS_MARKER not in collect.script(False, "")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_prompts.py`
Expected: FAIL, `ImportError: cannot import name 'prompts'`.

- [ ] **Step 3: Write `statslib/prompts.py`**

```python
"""Secret requests: which ones are open, from their metadata only.

A secret-prompt plugin keeps one directory per request. The scan prints
three small metadata files of each and tests whether two more exist; it
never reads anything else, and ``parse`` keeps only the fields of
``Request``: the secret's path and key name are dropped here. The rules
are the ones the requesting side applies (spec, "Secret requests").
"""

import json
import math
import re
import shlex
from collections import namedtuple

ID = re.compile(r"r-[0-9a-f]{8}")
STALE = 90          # a state.json older than this is ignored
WRITE_STALE = 210   # ... except while writing, which has no heartbeat
REQUEST_BYTES = 4096
OTHER_BYTES = 1024
REQUEST, FILE, FLAGS = "--request--", "--file--", "--flags--"

# Times are the host's epoch seconds. ``deadline`` is when the request
# stops being open; ``prompt_pane`` is the prompt's pane, None until it
# opened.
Request = namedtuple(
    "Request", "id created deadline pane_id workspace_id purpose"
    " prompt_pane")


def finite(value):
    """True for an int or float that is finite; a bool is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def scan_shell(name):
    """POSIX sh that prints the metadata of each request directory under
    ``name`` in the runtime and state directories."""
    q = shlex.quote(name)
    hexes = "[0-9a-f]" * 8
    return f"""\
me=$(id -un)
for base in "${{XDG_RUNTIME_DIR:-/nonexistent}}"/{q} \\
    /run/user/"$(id -u)"/{q} "$HOME"/.local/state/{q}; do
  [ -d "$base" ] || continue
  find "$base" -mindepth 1 -maxdepth 1 -type d -name 'r-*' -mmin -1440 \\
      2>/dev/null | while read -r d; do
    case "${{d##*/}}" in r-{hexes}) ;; *) continue;; esac
    set -- $(ls -ld "$d")
    case "$1" in drwx------|drwx------.|drwx------@) ;; *) continue;; esac
    [ "$3" = "$me" ] || continue
    echo "{REQUEST} ${{d##*/}}"
    for f in request pane state; do
      echo "{FILE} $f"
      n={OTHER_BYTES}; [ "$f" = request ] && n={REQUEST_BYTES}
      [ -f "$d/$f.json" ] && [ ! -L "$d/$f.json" ] && \\
        head -c "$n" "$d/$f.json"
      echo
    done
    r=0; [ -e "$d/result.json" ] && r=1
    c=0; [ -e "$d/cancel.json" ] && c=1
    echo "{FLAGS} result=$r cancel=$c"
  done
done"""


def _blocks(text):
    """[{id, files: {name: [lines]}, flags}] in the scan's output."""
    blocks, block, name = [], None, None
    for line in text.splitlines():
        if line.startswith(REQUEST + " "):
            block = {"id": line[len(REQUEST) + 1:], "files": {},
                     "flags": []}
            blocks.append(block)
            name = None
        elif block is None:
            continue
        elif line.startswith(FILE + " "):
            name = line[len(FILE) + 1:]
            block["files"][name] = []
        elif line.startswith(FLAGS + " "):
            block["flags"] = line.split()[1:]
            name = None
        elif name:
            block["files"][name].append(line)
    return blocks


def _object(lines):
    try:
        data = json.loads("\n".join(lines or []))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _open(block, now):
    """The block's Request if it is well formed and open at ``now``."""
    if (not ID.fullmatch(block["id"])
            or block["flags"] != ["result=0", "cancel=0"]):
        return None
    data = _object(block["files"].get("request"))
    if data is None or data.get("id") != block["id"]:
        return None
    if not (finite(data.get("created")) and finite(data.get("expires"))):
        return None
    texts = [data.get(k) for k in ("pane_id", "workspace_id", "purpose")]
    if not all(isinstance(t, str) for t in texts):
        return None
    deadline = data["expires"]
    state = _object(block["files"].get("state"))
    if (state and isinstance(state.get("phase"), str)
            and finite(state.get("deadline")) and finite(state.get("at"))):
        limit = WRITE_STALE if state["phase"] == "writing" else STALE
        if now - state["at"] <= limit:
            deadline = state["deadline"]
    if now >= deadline:
        return None
    pane = _object(block["files"].get("pane"))
    prompt = pane.get("pane_id") if pane else None
    return Request(block["id"], float(data["created"]), float(deadline),
                   *texts, prompt if isinstance(prompt, str) else None)


def parse(text, now):
    """The open requests in ``scan_shell`` output at the host's ``now``,
    each once."""
    found, seen = [], set()
    for block in _blocks(text):
        request = _open(block, now)
        if request and request.id not in seen:
            seen.add(request.id)
            found.append(request)
    return found
```

- [ ] **Step 4: Wire it into the poll**

In `collect.script`, after the tab-list lines and before the plugin
lines:

```python
    if request_dir:
        lines += [f"echo; echo {REQUESTS_MARKER}",
                  prompts.scan_shell(request_dir)]
```

and import it: `from statslib import PLUGIN_ID, herdr, needs, prompts`.

In `statslib/needs.py`, import `prompts` (`from statslib import herdr,
prompts`) and end `parse_raw` with:

```python
    requests = (prompts.parse(parts.get("requests", ""), now)
                if now is not None else [])
    return Raw(now, herdr.agents(parts.get("agents", "")),
               herdr.workspaces(parts.get("workspaces", "")),
               herdr.tabs(parts.get("tabs", "")), requests)
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run --with pytest --with flake8 python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add statslib/prompts.py statslib/collect.py statslib/needs.py \
  tests/test_prompts.py
git commit -m "✨ feat(needs): open secret requests from their metadata only"
```

---

### Task 5: Items: what waits on you, in order

**Files:**
- Modify: `statslib/needs.py`
- Test: `tests/test_needs.py` (new)

**Interfaces:**
- Consumes: `needs.Raw` (Task 3), `prompts.Request` (Task 4),
  `text.clean` (Task 1), `collect.Row` with `needs` (Task 3).
- Produces:
  - `GROUPS = ("blocked", "secret", "done")` (D2 order).
  - `Where = namedtuple("Where", "workspace workspace_label tab
    tab_label")`: numbers (int or None) and cleaned labels.
  - `Item = namedtuple("Item", "group rank machine target pane_id seq
    agent project where detail deadline first_seen approx key")`.
    `rank`: the row's index (this machine 0). `target`: SSH target, None
    for this machine. `pane_id`: the pane Enter focuses. `seq`:
    `state_change_seq` or None. `detail`: tuple of cleaned lines.
    `deadline`, `first_seen`: epoch seconds on this machine's clock, or
    None. `approx`: first seen is a lower bound. `key`: `(machine,
    pane_id)` for agents, `(machine, request id)` for secrets.
  - `Note = namedtuple("Note", "machine reason")`.
  - `build(rows, targets, poll_time) -> (list[Item], list[Note])`
    (unordered; agents' `first_seen` None until Task 6 stamps them).
  - `order(items) -> list[Item]`.

- [ ] **Step 1: Write the failing tests**

```python
"""statslib.needs: the items of the needs-you list."""

from statslib import collect, needs, prompts
from statslib.needs import Raw, Where


def agent(pane, status, **fields):
    data = {"pane_id": pane, "agent_status": status, "agent": "claude",
            "cwd": "/src/api", "workspace_id": "w1", "tab_id": "w1:t3",
            "state_change_seq": 7}
    data.update(fields)
    return data


def raw(agents, requests=(), now=1000):
    return Raw(now, list(agents), {"w1": (5, "api")},
               {"w1:t3": (18, "review"), "w1:t4": (4, "🔑 secret")},
               list(requests))


def row(label, data=None, error=None):
    return collect.Row(label, None, error, data)


def test_blocked_and_done_agents_are_listed_and_the_rest_ignored():
    rows = [row("build-box", raw([
        agent("w1:p1", "blocked", name="builder"),
        agent("w1:p2", "done", terminal_title_stripped="Fix the form"),
        agent("w1:p3", "working"), agent("w1:p4", "idle")]))]
    items, notes = needs.build(rows, [None], 2000)
    assert notes == []
    assert [(i.group, i.pane_id) for i in items] == [
        ("blocked", "w1:p1"), ("done", "w1:p2")]
    blocked, done = items
    assert (blocked.agent, blocked.project, blocked.machine) == (
        "builder", "api", "build-box")
    assert blocked.target is None and blocked.rank == 0
    assert blocked.where == Where(5, "api", 18, "review")
    assert blocked.seq == 7 and blocked.first_seen is None
    assert blocked.key == ("build-box", "w1:p1")
    assert done.detail == ("Fix the form",)


def test_a_secret_request_is_listed_once_and_jumps_to_its_prompt():
    request = prompts.Request(
        "r-0123abcd", created=880, deadline=1600, pane_id="w1:p1",
        workspace_id="w1", purpose="deploy the \x1b[1mexample\x1b[0m app",
        prompt_pane="w1:p9")
    agents = [agent("w1:p1", "working", name="builder"),
              agent("w1:p9", "blocked", agent="secret-prompt",
                    tab_id="w1:t4")]
    items, _ = needs.build([row("laptop", raw(agents, [request]))],
                           ["me@laptop.example"], 2000)
    [item] = items
    assert item.group == "secret" and item.pane_id == "w1:p9"
    assert item.target == "me@laptop.example"
    assert (item.agent, item.project) == ("builder", "api")
    assert item.where == Where(5, "api", 4, "🔑 secret")
    assert item.detail == ("deploy the example app",)
    # The host's clock said 1000 at a poll that began at 2000 here.
    assert item.first_seen == 1880 and item.deadline == 2600
    assert item.key == ("laptop", "r-0123abcd") and not item.approx


def test_before_its_prompt_opens_a_request_jumps_to_the_agent_that_asked():
    request = prompts.Request("r-0123abcd", 880, 1600, "w1:p1", "w1",
                              "why", None)
    items, _ = needs.build(
        [row("laptop", raw([agent("w1:p1", "working")], [request]))],
        ["me@laptop.example"], 2000)
    assert items[0].pane_id == "w1:p1"
    assert items[0].where == Where(5, "api", 18, "review")


def test_machines_that_could_not_be_asked_are_noted_not_hidden():
    rows = [row("build-box", None, "timeout"),
            row("laptop", raw([])._replace(agents=None)),
            row("lab", None, "disabled")]
    items, notes = needs.build(rows, [None, "a", "b"], 2000)
    assert items == []
    assert notes == [needs.Note("build-box", "down: timeout"),
                     needs.Note("laptop", "no herdr")]


def test_text_from_the_host_is_cleaned():
    bad = agent("w1:p1", "blocked", name="evil\x1b]0;x\x07name",
                cwd="/src/‮api/")
    items, _ = needs.build([row("b", raw([bad]))], [None], 2000)
    assert (items[0].agent, items[0].project) == ("evilname", "api")


def test_names_fall_back_from_name_to_display_agent_to_agent():
    rows = [row("b", raw([
        agent("w1:p1", "done", display_agent="Claude Code"),
        agent("w1:p2", "done"),
        agent("w1:p3", "done", agent=None)]))]
    items, _ = needs.build(rows, [None], 2000)
    assert [i.agent for i in items] == ["Claude Code", "claude", "agent"]


def test_a_blocked_agent_starts_with_its_label_or_title_as_detail():
    rows = [row("b", raw([
        agent("w1:p1", "blocked", state_labels={"blocked": "secret wanted"}),
        agent("w1:p2", "blocked", title="Approve the plan"),
        agent("w1:p3", "blocked")]))]
    items, _ = needs.build(rows, [None], 2000)
    assert [i.detail for i in items] == [
        ("secret wanted",), ("Approve the plan",), ()]


def test_order_is_group_then_oldest_then_machine_then_place():
    def item(group, first, rank=0, ws=1, tab=1):
        return needs.Item(group, rank, "m", None, "p", None, "a", "",
                          Where(ws, "", tab, ""), (), None, first, False,
                          ("m", f"{group}{first}{rank}{ws}{tab}"))
    items = [item("done", 1), item("blocked", 50), item("secret", 10),
             item("blocked", 20, rank=1), item("blocked", 20, ws=2),
             item("blocked", 20, tab=9)]
    got = [(i.group, i.first_seen, i.rank, i.where.workspace, i.where.tab)
           for i in needs.order(items)]
    assert got == [("blocked", 20, 0, 1, 9), ("blocked", 20, 0, 2, 1),
                   ("blocked", 20, 1, 1, 1), ("blocked", 50, 0, 1, 1),
                   ("secret", 10, 0, 1, 1), ("done", 1, 0, 1, 1)]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_needs.py`
Expected: FAIL, `AttributeError: module 'statslib.needs' has no
attribute 'build'`.

- [ ] **Step 3: Implement** (append to `statslib/needs.py`; add `text`
  to its `from statslib import ...` line)

```python
GROUPS = ("blocked", "secret", "done")  # the order they are listed in
AGENT_GROUPS = ("blocked", "done")
# The numbers and labels Herdr's screen shows; a number may be None.
Where = namedtuple("Where", "workspace workspace_label tab tab_label")
# One line of the list. Times are epoch seconds on this machine's clock.
Item = namedtuple(
    "Item", "group rank machine target pane_id seq agent project where"
    " detail deadline first_seen approx key")
# A machine whose agents could not be asked, and why.
Note = namedtuple("Note", "machine reason")
LAST = 1 << 30  # sorts an unknown workspace or tab number last


def _name(agent):
    for field in ("name", "display_agent", "agent"):
        name = text.clean(agent.get(field))
        if name:
            return name
    return "agent"


def _project(agent):
    cwd = agent.get("cwd")
    if not isinstance(cwd, str):
        return ""
    return text.clean(cwd.rstrip("/").rsplit("/", 1)[-1])


def _where(raw, workspace_id, tab_id):
    workspace = (raw.workspaces or {}).get(workspace_id)
    tab = (raw.tabs or {}).get(tab_id)
    if workspace is None and tab is None:
        return None
    return Where(workspace[0] if workspace else None,
                 text.clean(workspace[1]) if workspace else "",
                 tab[0] if tab else None,
                 text.clean(tab[1]) if tab else "")


def _seq(agent):
    seq = agent.get("state_change_seq")
    return seq if isinstance(seq, int) and not isinstance(seq, bool) \
        else None


def _first_detail(agent, status):
    """What to show before (or instead of) the screen lines (D5)."""
    labels = agent.get("state_labels")
    candidates = [labels.get(status) if isinstance(labels, dict) else None]
    if status == "blocked":
        candidates.append(agent.get("title"))
    candidates += [agent.get("terminal_title_stripped"),
                   agent.get("terminal_title")]
    for candidate in candidates:
        line = text.clean(candidate)
        if line:
            return (line,)
    return ()


def _machine_items(rank, machine, target, raw, poll_time):
    panes = {a["pane_id"]: a for a in raw.agents
             if isinstance(a.get("pane_id"), str)}
    prompts_open = {r.prompt_pane for r in raw.requests if r.prompt_pane}
    items = []
    for pane_id, agent in panes.items():
        status = agent.get("agent_status")
        if status not in AGENT_GROUPS or pane_id in prompts_open:
            continue
        items.append(Item(
            status, rank, machine, target, pane_id, _seq(agent),
            _name(agent), _project(agent),
            _where(raw, agent.get("workspace_id"), agent.get("tab_id")),
            _first_detail(agent, status), None, None, False,
            (machine, pane_id)))
    # Request times are the host's; move them onto this machine's clock.
    shift = poll_time - raw.now if raw.now is not None else 0
    for request in raw.requests:
        asking = panes.get(request.pane_id, {})
        place = panes.get(request.prompt_pane) or asking
        items.append(Item(
            "secret", rank, machine, target,
            request.prompt_pane or request.pane_id, None,
            _name(asking) if asking else "agent", _project(asking),
            _where(raw, place.get("workspace_id", request.workspace_id),
                   place.get("tab_id")),
            tuple(filter(None, [text.clean(request.purpose)])),
            request.deadline + shift, request.created + shift, False,
            (machine, request.id)))
    return items


def build(rows, targets, poll_time):
    """(items, notes) for one poll's rows; ``targets[i]`` is row i's SSH
    target (None: this machine). Items are not ordered, and agents have
    no first-seen time yet (``seen.Store.stamp`` gives it)."""
    items, notes = [], []
    for rank, (row, target) in enumerate(zip(rows, targets)):
        if row.error == "disabled":
            continue
        raw = row.needs
        if raw is None or raw.agents is None:
            reason = f"down: {row.error}" if row.error else "no herdr"
            notes.append(Note(row.label, reason))
            continue
        items += _machine_items(rank, row.label, target, raw, poll_time)
    return items, notes


def order(items):
    """Blocked, then secrets, then finished; oldest first in each, then
    by machine, workspace number and tab number."""
    def key(item):
        where = item.where
        return (GROUPS.index(item.group),
                item.first_seen if item.first_seen is not None
                else float("inf"),
                item.rank,
                where.workspace if where and where.workspace is not None
                else LAST,
                where.tab if where and where.tab is not None else LAST)
    return sorted(items, key=key)
```

- [ ] **Step 4: Run the tests**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_needs.py tests/test_lint.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add statslib/needs.py tests/test_needs.py
git commit -m "✨ feat(needs): items for blocked, secret and finished, oldest first"
```

---

### Task 6: First-seen times and the last list, kept locally

**Files:**
- Create: `statslib/seen.py`
- Test: `tests/test_seen.py`

**Interfaces:**
- Consumes: `needs.Item`, `needs.Where` (Task 5), `prompts.finite`
  (Task 4).
- Produces:
  - `state_dir(env) -> Path`: `HERDR_PLUGIN_STATE_DIR`, else
    `$XDG_STATE_HOME/herdr-machine-stats`, else
    `$HOME/.local/state/herdr-machine-stats`.
  - `Store(directory)` with attributes `dir`, `ages` (`needs.json`),
    `listing` (`needs-list.json`), `lock` (`needs.lock`) and methods
    `stamp(items, answered, poll_time, interval) -> list[Item]`
    (`answered`: set of machine labels that gave needs data),
    `save_list(items, as_of)`, `load_list() -> (list[Item], float |
    None)`. Methods may raise `OSError` (callers fall back).

- [ ] **Step 1: Write the failing tests**

```python
"""statslib.seen: first-seen times and the last list, on this machine."""

import json
import stat
import threading
from pathlib import Path

import pytest

from statslib import seen
from statslib.needs import Item, Where


def item(group="blocked", machine="laptop", pane="w1:p1", seq=7,
         detail=()):
    return Item(group, 0, machine, None, pane, seq, "claude", "api",
                Where(5, "api", 18, "review"), detail, None, None, False,
                (machine, pane))


@pytest.fixture
def store(tmp_path):
    return seen.Store(tmp_path / "state")


def test_the_same_wait_keeps_its_first_seen_time(store):
    [a] = store.stamp([item()], {"laptop"}, 1000, 10)
    [b] = store.stamp([item()], {"laptop"}, 1010, 10)
    assert a.first_seen == b.first_seen == 1000


@pytest.mark.parametrize("change", [{"seq": 8}, {"group": "done"}])
def test_a_new_state_starts_the_clock_again(store, change):
    store.stamp([item()], {"laptop"}, 1000, 10)
    [b] = store.stamp([item(**change)], {"laptop"}, 1010, 10)
    assert b.first_seen == 1010


def test_items_first_seen_after_a_gap_are_lower_bounds(store):
    [first] = store.stamp([item()], {"laptop"}, 1000, 10)
    assert first.approx  # nothing was watching before
    kept, new = store.stamp([item(), item(pane="w1:p2")], {"laptop"},
                            1010, 10)
    assert kept.approx and not new.approx
    # 90 s without an update is more than three intervals of 10 s.
    _, _, late = store.stamp(
        [item(), item(pane="w1:p2"), item(pane="w1:p3")], {"laptop"},
        1100, 10)
    assert late.approx


def test_an_unanswered_machine_keeps_its_entries_for_an_hour(store):
    store.stamp([item()], {"laptop"}, 1000, 10)
    store.stamp([], set(), 2000, 10)  # the laptop did not answer
    [b] = store.stamp([item()], {"laptop"}, 2010, 10)
    assert b.first_seen == 1000
    store.stamp([], set(), 2010 + 3600, 10)
    [c] = store.stamp([item()], {"laptop"}, 2020 + 3600, 10)
    assert c.first_seen == 2020 + 3600


def test_an_answered_machine_drops_what_it_no_longer_lists(store):
    store.stamp([item()], {"laptop"}, 1000, 10)
    store.stamp([], {"laptop"}, 1010, 10)
    [b] = store.stamp([item()], {"laptop"}, 1020, 10)
    assert b.first_seen == 1020


def test_secret_requests_keep_their_own_times(store):
    secret = item(group="secret")._replace(first_seen=900,
                                           key=("laptop", "r-0123abcd"))
    [s] = store.stamp([secret], {"laptop"}, 1000, 10)
    assert s.first_seen == 900 and not s.approx


def test_the_files_are_private_and_hold_no_screen_text(store):
    [s] = store.stamp([item(detail=("SCREEN-TEXT",))], {"laptop"}, 1000,
                      10)
    store.save_list([s], 1000)
    for path in (store.ages, store.listing):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert "SCREEN-TEXT" not in path.read_text()


def test_the_last_list_comes_back_without_details(store):
    s = item(detail=("x",))._replace(first_seen=1000)
    store.save_list([s], 1234.5)
    assert store.load_list() == ([s._replace(detail=())], 1234.5)


def test_a_missing_or_broken_list_is_empty(store):
    assert store.load_list() == ([], None)
    store.dir.mkdir(parents=True)
    store.listing.write_text("{broken")
    assert store.load_list() == ([], None)


def test_two_processes_stamping_at_once_lose_nothing(tmp_path):
    def run(machine):
        mine = seen.Store(tmp_path / "state")
        for n in range(30):
            mine.stamp([item(machine=machine)], {machine}, 1000 + n, 10)
    threads = [threading.Thread(target=run, args=(m,)) for m in "ab"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    data = json.loads((tmp_path / "state" / "needs.json").read_text())
    assert sorted(e["machine"] for e in data["items"].values()) == [
        "a", "b"]


def test_the_state_dir_is_herdrs_then_xdg_then_home():
    assert seen.state_dir({"HERDR_PLUGIN_STATE_DIR": "/s",
                           "XDG_STATE_HOME": "/x"}) == Path("/s")
    assert seen.state_dir({"XDG_STATE_HOME": "/x", "HOME": "/h"}) == Path(
        "/x/herdr-machine-stats")
    assert seen.state_dir({"HOME": "/h"}) == Path(
        "/h/.local/state/herdr-machine-stats")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_seen.py`
Expected: FAIL, `ImportError: cannot import name 'seen'`.

- [ ] **Step 3: Write `statslib/seen.py`**

```python
"""When each needs-you item was first seen, kept on this machine.

Herdr gives no time for a status change, so an agent's wait counts from
the first poll that saw it in that status with that state_change_seq.
The dashboard and the popup share these files, so both show the same
ages and a restart does not reset them. They hold ids, statuses,
sequence numbers, names, places and times: never screen text or a
request's purpose. Nothing here is ever written to another machine.
"""

import contextlib
import fcntl
import json
import os
import tempfile
from pathlib import Path

from statslib.needs import Item, Where
from statslib.prompts import finite

# Intervals without an update after which new items are lower bounds:
# nothing was watching.
GAP = 3
KEEP = 3600  # seconds a machine that does not answer keeps its entries
LISTED = ("group", "rank", "machine", "target", "pane_id", "seq",
          "agent", "project", "where", "deadline", "first_seen",
          "approx", "key")


def state_dir(env):
    """Where the files live: Herdr's plugin state directory, else the
    XDG state directory."""
    if env.get("HERDR_PLUGIN_STATE_DIR"):
        return Path(env["HERDR_PLUGIN_STATE_DIR"])
    base = env.get("XDG_STATE_HOME") or os.path.join(
        env.get("HOME") or os.path.expanduser("~"), ".local", "state")
    return Path(base) / "herdr-machine-stats"


def _read(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(path, data):
    """Replace ``path`` atomically with a file only this user reads."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


class Store:
    """First-seen times (``needs.json``) and the last list drawn
    (``needs-list.json``), under one lock."""

    def __init__(self, directory):
        self.dir = Path(directory)
        self.ages = self.dir / "needs.json"
        self.listing = self.dir / "needs-list.json"
        self.lock = self.dir / "needs.lock"

    @contextlib.contextmanager
    def _locked(self):
        self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(self.lock, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield  # closing the file releases the lock

    def stamp(self, items, answered, poll_time, interval):
        """``items`` with first-seen times. A secret keeps its own."""
        with self._locked():
            old = _read(self.ages) or {}
            entries = old.get("items")
            entries = entries if isinstance(entries, dict) else {}
            updated = old.get("updated")
            gap = (not finite(updated)
                   or poll_time - updated > GAP * interval)
            fresh, out = {}, []
            for item in items:
                if item.group == "secret":
                    out.append(item)
                    continue
                name = f"{item.machine}\t{item.pane_id}"
                was = entries.get(name)
                if (isinstance(was, dict) and was.get("status") == item.group
                        and was.get("seq") == item.seq
                        and finite(was.get("first_seen"))):
                    first, approx = was["first_seen"], bool(was.get("approx"))
                else:
                    first, approx = poll_time, gap
                fresh[name] = {"machine": item.machine, "status": item.group,
                               "seq": item.seq, "first_seen": first,
                               "approx": approx, "last_seen": poll_time}
                out.append(item._replace(first_seen=first, approx=approx))
            for name, was in entries.items():
                if (name not in fresh and isinstance(was, dict)
                        and was.get("machine") not in answered
                        and finite(was.get("last_seen"))
                        and poll_time - was["last_seen"] < KEEP):
                    fresh[name] = was
            _write(self.ages, {"updated": poll_time, "items": fresh})
        return out

    def save_list(self, items, as_of):
        """Keep the list (without details) for the popup to show at once."""
        rows = [{field: getattr(item, field) for field in LISTED}
                for item in items]
        with self._locked():
            _write(self.listing, {"as_of": as_of, "items": rows})

    def load_list(self):
        """(items, as_of) of the last list kept; ([], None) without one."""
        data = _read(self.listing)
        try:
            items = [Item(**{**{f: row[f] for f in LISTED}, "detail": (),
                             "where": Where(*row["where"]) if row["where"]
                             else None,
                             "key": tuple(row["key"])})
                     for row in data["items"]]
            return items, float(data["as_of"])
        except (TypeError, KeyError, ValueError):
            return [], None
```

- [ ] **Step 4: Run the tests**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_seen.py tests/test_lint.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add statslib/seen.py tests/test_seen.py
git commit -m "✨ feat(needs): first-seen times shared by dashboard and popup"
```

---

### Task 7: Screen lines of blocked agents, read once per wait

**Files:**
- Modify: `statslib/herdr.py`, `statslib/collect.py`, `statslib/needs.py`
- Test: `tests/test_herdr_reads.py`, `tests/test_collect.py`,
  `tests/test_needs.py`

**Interfaces:**
- Consumes: `text.meaningful` (Task 1), `needs.Item` (Task 5),
  `collect.PATH_LINE`, `collect.run_host`, `collect.HostError`.
- Produces:
  - `herdr.READ_MARKER = "--pane--"`, `herdr.read_shell(pane_ids) ->
    str`, `herdr.screens(text) -> dict[str, list[str]]`.
  - `herdr.focus(pane_id, timeout=5)` (this machine; raises
    `HerdrError`), `herdr.focus_shell(pane_id) -> str` (used by Task 10;
    added here so all new `herdr` names land in one task).
  - `collect.read_screens(target, panes, run=None) -> dict[str,
    list[str]]` (`{}` when the host cannot be read).
  - `needs.Screens(read)` where `read(target, panes) -> {pane: lines}`;
    `Screens.fill(items) -> list[Item]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_herdr_reads.py` (add `import os` and `import
subprocess` at the top):

```python
def test_screens_are_read_with_one_marker_line_per_pane(fake_herdr):
    shim, calls, canned = fake_herdr
    (canned / "agent-read").write_text("Do you want to proceed?\n❯ 1. Yes\n")
    env = dict(os.environ, PATH=f"{shim.parent}{os.pathsep}"
               f"{os.environ['PATH']}")
    out = subprocess.run(
        ["sh", "-c", herdr.read_shell(["w1:p1", "w1:p2"])], env=env,
        capture_output=True, text=True, timeout=20).stdout
    screen = ["Do you want to proceed?", "❯ 1. Yes"]
    assert herdr.screens(out) == {"w1:p1": screen, "w1:p2": screen}
    assert calls.read_text().splitlines() == [
        "agent read w1:p1 --source visible --format text",
        "agent read w1:p2 --source visible --format text"]


def test_focus_names_the_pane_here_and_in_a_remote_shell(fake_herdr,
                                                         monkeypatch):
    shim, calls, _canned = fake_herdr
    monkeypatch.setenv("HERDR_BIN", str(shim))
    herdr.focus("w1:p2")
    assert calls.read_text().splitlines() == ["agent focus w1:p2"]
    assert herdr.focus_shell("w1:p2") == "herdr agent focus w1:p2"
    assert herdr.focus_shell("a b") == "herdr agent focus 'a b'"
```

Append to `tests/test_collect.py`:

```python
def test_read_screens_reads_all_panes_of_a_host_in_one_call():
    run = Runner("--pane-- w1:p1\nline\n")
    assert collect.read_screens("me@laptop.example", ["w1:p1"], run) == {
        "w1:p1": ["line"]}
    [(target, script)] = run.calls
    assert target == "me@laptop.example"
    assert script.startswith(collect.PATH_LINE)
    down = Runner(collect.HostError("timeout"))
    assert collect.read_screens("me@laptop.example", ["w1:p1"], down) == {}
```

Append to `tests/test_needs.py`:

```python
class Reads:
    """A fake screen reader: what each pane shows, and the calls."""

    def __init__(self, screens):
        self.screens, self.calls = screens, []

    def __call__(self, target, panes):
        self.calls.append((target, list(panes)))
        return {p: self.screens[p] for p in panes if p in self.screens}


def blocked(pane, seq=7, detail=()):
    return needs.Item("blocked", 0, "laptop", "me@laptop.example", pane,
                      seq, "claude", "api", None, detail, None, 1000, False,
                      ("laptop", pane))


def test_screen_lines_are_read_once_per_wait_one_call_per_machine():
    reads = Reads({"w1:p1": ["╭────╮", "│ Proceed? │", "│ ❯ 1. Yes │",
                             "╰────╯"],
                   "w1:p2": ["Allow?"]})
    screens = needs.Screens(reads)
    items = [blocked("w1:p1"), blocked("w1:p2")]
    assert [i.detail for i in screens.fill(items)] == [
        ("Proceed?", "❯ 1. Yes"), ("Allow?",)]
    assert reads.calls == [("me@laptop.example", ["w1:p1", "w1:p2"])]
    screens.fill(items)
    assert len(reads.calls) == 1  # the same wait: nothing read again
    screens.fill([blocked("w1:p1", seq=8)])
    assert reads.calls[-1] == ("me@laptop.example", ["w1:p1"])


def test_a_failed_read_keeps_the_fallback_and_is_not_retried():
    reads = Reads({})
    screens = needs.Screens(reads)
    [item] = screens.fill([blocked("w1:p1", detail=("secret wanted",))])
    assert item.detail == ("secret wanted",)
    screens.fill([blocked("w1:p1", detail=("secret wanted",))])
    assert len(reads.calls) == 1


def test_only_blocked_agents_are_read():
    reads = Reads({})
    done = blocked("w1:p1")._replace(group="done", detail=("title",))
    assert needs.Screens(reads).fill([done]) == [done]
    assert reads.calls == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_herdr_reads.py tests/test_collect.py tests/test_needs.py`
Expected: FAIL (`read_shell`, `focus`, `read_screens`, `Screens`
missing).

- [ ] **Step 3: Implement in `statslib/herdr.py`** (add `import shlex`)

```python
READ_MARKER = "--pane--"


def read_shell(pane_ids):
    """Shell that prints each pane's visible screen as plain text, each
    after a ``--pane-- <id>`` line. Reading never marks an agent seen."""
    return "\n".join(
        f"echo {READ_MARKER} {shlex.quote(pane)}\n"
        f"herdr agent read {shlex.quote(pane)} --source visible"
        " --format text 2>/dev/null | tail -n 60"
        for pane in pane_ids)


def screens(text):
    """{pane_id: lines} from ``read_shell`` output."""
    found, lines = {}, None
    for line in text.splitlines():
        if line.startswith(READ_MARKER + " "):
            lines = found.setdefault(line[len(READ_MARKER) + 1:], [])
        elif lines is not None:
            lines.append(line)
    return found


def focus(pane_id, timeout=5):
    """Focus ``pane_id`` on this machine's Herdr. This marks a finished
    agent seen."""
    _local(["agent", "focus", pane_id], timeout)


def focus_shell(pane_id):
    """The same focus, as a shell fragment for another machine."""
    return f"herdr agent focus {shlex.quote(pane_id)}"
```

- [ ] **Step 4: Implement `collect.read_screens`** (after `run_host`)

```python
def read_screens(target, panes, run=None):
    """{pane: screen lines} for ``panes`` on ``target`` (None: here), in
    one call; {} when the host cannot be read."""
    run = run or run_host
    try:
        return herdr.screens(
            run(target, PATH_LINE + "\n" + herdr.read_shell(panes)))
    except HostError:
        return {}
```

- [ ] **Step 5: Implement `needs.Screens`** (append to `statslib/needs.py`)

```python
class Screens:
    """The last meaningful lines of each blocked agent's screen (D5).

    A blocked screen does not change while it waits on the same
    question, so each (machine, pane, state_change_seq) is read once,
    and all new ones of a machine in one call. Kept in memory only.
    """

    def __init__(self, read):
        self.read = read  # read(target, panes) -> {pane: lines}
        self.lines = {}

    def fill(self, items):
        blocked = [i for i in items if i.group == "blocked"]
        wanted = {}
        for item in blocked:
            if (item.machine, item.pane_id, item.seq) not in self.lines:
                wanted.setdefault((item.machine, item.target), []).append(
                    item.pane_id)
        for (machine, target), panes in wanted.items():
            read = self.read(target, panes)
            for item in blocked:
                if item.machine == machine and item.pane_id in panes:
                    self.lines[(machine, item.pane_id, item.seq)] = tuple(
                        text.meaningful(read.get(item.pane_id, [])))
        live = {(i.machine, i.pane_id, i.seq) for i in blocked}
        self.lines = {k: v for k, v in self.lines.items() if k in live}
        return [i._replace(detail=self.lines.get(
                    (i.machine, i.pane_id, i.seq)) or i.detail)
                if i.group == "blocked" else i for i in items]
```

- [ ] **Step 6: Run the whole suite**

Run: `uv run --with pytest --with flake8 python -m pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add statslib/herdr.py statslib/collect.py statslib/needs.py \
  tests/test_herdr_reads.py tests/test_collect.py tests/test_needs.py
git commit -m "✨ feat(needs): read a blocked agent's last lines once per wait"
```

---

### Task 8: Drawing the list

**Files:**
- Modify: `statslib/render.py` (after `AGENT_MARKS`)
- Create: `statslib/needsview.py`
- Test: `tests/test_needsview.py` (new), `tests/test_render.py`

**Interfaces:**
- Consumes: `text` (Task 1), `needs.GROUPS`, `Item`, `Note`, `Where`
  (Task 5), `render.age_text`.
- Produces:
  - `render.SECRET_MARK = ("secret", "🔑", "yellow")`,
    `render.LEGEND = (*AGENT_MARKS, SECRET_MARK)`.
  - `needsview.fit(parts, width)`, `age(item, now) -> str`,
    `details(item, count=3) -> list[str]`, `where_text(where,
    narrow=False) -> str`, `columns(items) -> dict`, `item_lines(item,
    width, now, cols, selected=False, count=3)`, `section(items, notes,
    width, height, now)`, `full(items, notes, width, now, selected) ->
    (lines, starts)`, `legend(width, keys)`, `plain(items, notes, now)
    -> list[str]`. A line is a list of `(text, style)` parts whose cells
    add up to `width` exactly; `items` are in `needs.order`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_render.py`:

```python
def test_one_legend_serves_cards_list_and_popup():
    from statslib import render
    assert [(s, m) for s, m, _ in render.LEGEND] == [
        ("blocked", "◐"), ("working", "●"), ("idle", "○"),
        ("done", "✓"), ("secret", "🔑")]
```

`tests/test_needsview.py`:

```python
"""statslib.needsview: the needs-you list as lines."""

import time

import pytest

from statslib import needsview, text
from statslib.needs import Item, Note, Where

NOW = 10_000
ASKING = ("Do you want to make this edit to settings.py?", "❯ 1. Yes",
          "2. No")


def item(group="blocked", machine="build-box", agent="claude",
         project="api", where=Where(5, "api", 18, "review"), detail=ASKING,
         first_seen=NOW - 720, approx=False, deadline=None, pane="w1:p1"):
    return Item(group, 0, machine, None, pane, 7, agent, project, where,
                detail, deadline, first_seen, approx, (machine, pane))


MIXED = [
    item(),
    item("secret", machine="laptop", agent="codex", project="site",
         where=Where(2, "site", 4, "🔑 secret wanted"),
         detail=("deploy the example app",), deadline=NOW + 600,
         first_seen=NOW - 180),
    item("done", detail=("Fix the login form",), first_seen=NOW - 60,
         pane="w1:p2"),
]


def flat(line):
    return "".join(part for part, _style in line)


def widths(lines):
    return {text.cells(flat(line)) for line in lines}


@pytest.mark.parametrize("width", [30, 40, 69, 70, 100, 160])
def test_every_line_is_exactly_the_width(width):
    cols = needsview.columns(MIXED)
    for one in MIXED:
        assert widths(needsview.item_lines(one, width, NOW, cols)) == {
            width}
    notes = [Note("lab", "down: timeout")]
    assert widths(needsview.section(MIXED, notes, width, 40, NOW)) == {
        width}
    assert widths(needsview.full(MIXED, notes, width, NOW, 0)[0]) == {
        width}
    assert widths([needsview.legend(width, "q close")]) == {width}


def test_a_wide_item_reads_mark_age_machine_agent_project_place():
    lines = needsview.item_lines(item(), 100, NOW,
                                 needsview.columns([item()]))
    assert flat(lines[0]).split() == [
        "◐", "12m", "build-box", "claude", "api", "workspace", "5", "api,",
        "tab", "18", "'review'"]
    assert [flat(line).strip() for line in lines[1:]] == [
        "│ " + line for line in ASKING]


def test_a_narrow_item_takes_two_lines_before_its_details():
    lines = needsview.item_lines(item(), 50, NOW,
                                 needsview.columns([item()]))
    assert flat(lines[0]).split() == ["◐", "12m", "claude", "·", "api"]
    assert flat(lines[1]).strip() == (
        "build-box · ws 5 api › tab 18 'review'")
    assert len(lines) == 5


def test_a_lower_bound_age_ends_in_plus():
    assert needsview.age(item(approx=True), NOW) == "12m+"
    assert needsview.age(item(first_seen=None), NOW) == "?"


def test_a_secret_shows_its_expiry_before_its_purpose():
    hhmm = time.strftime("%H:%M", time.localtime(NOW + 600))
    assert needsview.details(MIXED[1]) == [
        f"expires {hhmm} · deploy the example app"]


def test_where_without_labels_shows_numbers_only():
    assert needsview.where_text(Where(5, "", 18, "")) == (
        "workspace 5, tab 18")
    assert needsview.where_text(None) == ""


def test_the_section_says_so_when_nothing_needs_you():
    [line] = needsview.section([], [], 80, 40, NOW)
    assert flat(line).strip() == "nothing needs you"


def test_the_section_counts_lists_urgent_items_and_sums_finished_ones():
    lines = [flat(line) for line in needsview.section(
        MIXED, [Note("lab", "down: timeout")], 100, 40, NOW)]
    assert lines[0].split()[:8] == [
        "needs", "you", "◐", "1", "🔑", "1", "✓", "1"]
    assert "claude" in lines[1] and "│ Do you want" in lines[2]
    assert "codex" in lines[3] and "expires" in lines[4]
    assert lines[5].strip() == "✓ 1 finished, unseen: 1 on build-box"
    assert lines[6].strip() == "? lab: down: timeout, not counted"


def test_the_section_keeps_to_a_third_of_the_screen():
    many = [item(pane=f"w1:p{n}", first_seen=NOW - n) for n in range(10)]
    lines = needsview.section(many, [], 100, 30, NOW)
    assert len(lines) <= (30 - 2) // 3
    assert flat(lines[-1]).strip() == "+7 more · ! for all"


def test_a_short_screen_gets_only_the_counts():
    assert len(needsview.section(MIXED, [], 100, 19, NOW)) == 1


def test_the_full_list_groups_items_and_knows_where_each_starts():
    lines, starts = needsview.full(MIXED, [Note("lab", "no herdr")], 100,
                                   NOW, 1)
    texts = [flat(line).strip() for line in lines]
    assert texts[0] == "◐ waiting on you (1)"
    assert [texts[s].split()[0] for s in starts] == ["◐", "🔑", "✓"]
    assert texts[-1] == "? lab: no herdr, not counted"
    assert "selected" in {style for _part, style in lines[starts[1]]}
    assert "selected" not in {style for _part, style in lines[starts[0]]}


def test_plain_lists_each_group_for_scripts():
    out = needsview.plain(MIXED, [Note("lab", "down: timeout")], NOW)
    assert out[0] == "waiting on you (1)"
    assert out[1] == (
        "◐ 12m  build-box  claude  api  workspace 5 api, tab 18 'review'")
    assert out[2] == "    │ Do you want to make this edit to settings.py?"
    assert out[-1] == "? lab: down: timeout, not counted"
    assert needsview.plain([], [], NOW) == ["nothing needs you"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_needsview.py tests/test_render.py`
Expected: FAIL (`render.LEGEND`, `statslib.needsview` missing).

- [ ] **Step 3: Add the legend to `statslib/render.py`** (after
  `AGENT_MARKS`)

```python
SECRET_MARK = ("secret", "🔑", "yellow")
# The one status legend: the cards, the needs-you list, the popup and
# the README all use these marks.
LEGEND = (*AGENT_MARKS, SECRET_MARK)
```

- [ ] **Step 4: Write `statslib/needsview.py`**

```python
"""The needs-you list as lines of ``(text, style)`` parts, like the
cards in render.py but measured in terminal cells (🔑 takes two).

``items`` are always in ``needs.order``. What is shown, and why, is in
docs/specs/2026-10-27-needs-you-design.md ("Layout").
"""

import time

from statslib import render, text
from statslib.needs import GROUPS

NARROW = 70    # narrower lists put each item on two lines
DETAILS = 3    # detail lines per item in the full list
INDENT = 11    # where a wide item's detail lines start
MARKS = {status: (mark, style) for status, mark, style in render.LEGEND}
TITLES = {"blocked": "waiting on you", "secret": "secret requested",
          "done": "finished, unseen"}
CAPS = {"machine": 16, "agent": 12, "project": 16}  # column caps, cells


def fit(parts, width):
    """``parts`` cut or padded to exactly ``width`` cells."""
    out, used = [], 0
    for value, style in parts:
        room = width - used
        if room <= 0:
            break
        if text.cells(value) > room:
            value = value[:room] if not value.strip() else text.cut(
                value, room)
        out.append((value, style))
        used += text.cells(value)
    if used < width:
        out.append((" " * (width - used), "text"))
    return out


def age(item, now):
    """How long it has waited; ``+`` marks a lower bound."""
    if item.first_seen is None:
        return "?"
    shown = render.age_text(max(0, int(now - item.first_seen)))
    return shown + "+" if item.approx else shown


def details(item, count=DETAILS):
    """The detail lines: a secret's expiry comes first, so a long
    purpose never hides it."""
    lines = list(item.detail)
    if item.group == "secret" and item.deadline is not None:
        expires = "expires " + time.strftime(
            "%H:%M", time.localtime(item.deadline))
        lines = [expires + (f" · {lines[0]}" if lines else "")]
    return lines[:max(0, count)]


def where_text(where, narrow=False):
    """"workspace 5 api, tab 18 'review'"; narrow: "ws 5 api › tab 18
    'review'". Numbers and labels as Herdr's screen shows them."""
    if where is None:
        return ""
    parts = []
    if where.workspace is not None:
        noun = "ws" if narrow else "workspace"
        parts.append(f"{noun} {where.workspace} {where.workspace_label}"
                     .rstrip())
    if where.tab is not None:
        parts.append(f"tab {where.tab}" + (
            f" '{where.tab_label}'" if where.tab_label else ""))
    return (" › " if narrow else ", ").join(parts)


def columns(items):
    """Column widths for the wide layout, capped."""
    return {field: min(cap, max((text.cells(getattr(i, field))
                                 for i in items), default=0))
            for field, cap in CAPS.items()}


def item_lines(item, width, now, cols, selected=False, count=DETAILS):
    """One item: its head line(s), then up to ``count`` detail lines."""
    mark, style = MARKS[item.group]
    head = "selected" if selected else "title"
    mark = " " + text.pad(mark, 2)
    if width >= NARROW:
        lines = [fit([
            (mark, style), (f" {age(item, now):>5}  ", "text"),
            (text.pad(item.machine, cols["machine"]) + "  ", head),
            (text.pad(item.agent, cols["agent"]) + "  ", head),
            (text.pad(item.project, cols["project"]) + "  ", "label"),
            (where_text(item.where), "dim")], width)]
        lead = " " * INDENT
    else:
        project = f" · {item.project}" if item.project else ""
        place = where_text(item.where, narrow=True)
        lines = [
            fit([(mark, style), (f" {age(item, now)} ", "text"),
                 (item.agent, head), (project, "label")], width),
            fit([(f"   {item.machine}", "label"),
                 (f" · {place}" if place else "", "dim")], width)]
        lead = "   "
    lines += [fit([(lead + "│ ", "dim"), (line, "text")], width)
              for line in details(item, count)]
    return lines


def _note_lines(notes, width):
    return [fit([(f" ? {n.machine}: {n.reason}, not counted", "dim")],
                width) for n in notes]


def section(items, notes, width, height, now):
    """The dashboard's section: counts, the blocked and secret items
    with one detail line each, one line summing the finished ones, and
    the machines not counted; at most a third of the screen."""
    if not items:
        lines = [fit([(" nothing needs you", "dim")], width)]
    else:
        parts = [(" needs you", "title")]
        for group in GROUPS:
            count = sum(i.group == group for i in items)
            if count:
                mark, style = MARKS[group]
                parts += [("  ", "text"), (f"{mark} {count}", style)]
        hint = "! full list "
        used = sum(text.cells(part) for part, _style in parts)
        if width - used > len(hint) + 2:
            parts += [(" " * (width - used - len(hint)), "text"),
                      (hint, "dim")]
        lines = [fit(parts, width)]
    if height < 20:
        return lines[:1]
    budget = max(3, (height - 2) // 3)
    tail = []
    done = [i for i in items if i.group == "done"]
    if done:
        by_machine = {}
        for one in done:
            by_machine[one.machine] = by_machine.get(one.machine, 0) + 1
        mark, style = MARKS["done"]
        tail.append(fit([
            (f" {mark} {len(done)} finished, unseen: ", style),
            (", ".join(f"{n} on {m}" for m, n in by_machine.items()),
             "dim")], width))
    tail += _note_lines(notes, width)
    cols = columns(items)
    count = 1 if width >= 40 else 0
    chunks = [item_lines(i, width, now, cols, count=count)
              for i in items if i.group != "done"]
    room = budget - 1 - min(len(tail), budget - 1)
    body, shown = [], 0
    for n, chunk in enumerate(chunks):
        more = n + 1 < len(chunks)
        if len(body) + len(chunk) + more > room:
            break
        body += chunk
        shown += 1
    if shown < len(chunks) and room >= 1:
        body.append(fit([(f" +{len(chunks) - shown} more · ! for all",
                          "dim")], width))
    return [*lines, *body, *tail][:budget]


def full(items, notes, width, now, selected):
    """(lines, starts): every item under its group's header, and the
    line each item starts on, for scrolling to ``selected``."""
    lines, starts = [], []
    cols = columns(items)
    count = DETAILS if width >= 40 else 1
    for group in GROUPS:
        members = [i for i in items if i.group == group]
        if not members:
            continue
        mark, style = MARKS[group]
        lines.append(fit([(f" {mark} {TITLES[group]} ({len(members)})",
                           style)], width))
        for one in members:
            starts.append(len(lines))
            lines += item_lines(one, width, now, cols,
                                selected=len(starts) - 1 == selected,
                                count=count)
        lines.append(fit([], width))
    lines += _note_lines(notes, width)
    if not lines:
        lines = [fit([(" nothing needs you", "dim")], width)]
    return lines, starts


def legend(width, keys):
    """The footer: the marks of the three groups, then ``keys``."""
    parts = [(" ", "text")]
    for group in GROUPS:
        mark, style = MARKS[group]
        parts += [(f"{mark} ", style), (f"{group}  ", "dim")]
    return fit([*parts, (keys, "dim")], width)


def plain(items, notes, now):
    """The list as plain text lines, for ``--once --needs``."""
    out = []
    for group in GROUPS:
        members = [i for i in items if i.group == group]
        if members:
            out.append(f"{TITLES[group]} ({len(members)})")
        for one in members:
            head = (f"{MARKS[group][0]} {age(one, now)}", one.machine,
                    one.agent, one.project, where_text(one.where))
            out.append("  ".join(part for part in head if part))
            out += [f"    │ {line}" for line in details(one)]
    out += [f"? {n.machine}: {n.reason}, not counted" for n in notes]
    return out or ["nothing needs you"]
```

- [ ] **Step 5: Run the tests**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_needsview.py tests/test_render.py tests/test_lint.py`
Expected: PASS. If a width test fails at 30 columns, the culprit is a
part that `fit` cut to fewer cells than its room (a wide character at
the edge); `fit` pads the remainder, so check that the failing line's
parts come from `fit` and not from a hand-built list.

- [ ] **Step 6: Commit**

```bash
git add statslib/render.py statslib/needsview.py tests/test_needsview.py \
  tests/test_render.py
git commit -m "✨ feat(needs): draw the list: section, full list, legend, plain"
```

---

### Task 9: The section on the dashboard

**Files:**
- Modify: `bin/machine-stats`
- Test: `tests/test_needs_cli.py` (new), `tests/test_cli.py` (one stub)

**Interfaces:**
- Consumes: `collect.poll(..., stats, request_dir)`,
  `collect.read_screens`, `needs.build/order/Screens`, `seen.Store`,
  `seen.state_dir`, `needsview.section/fit`, `text.cells`,
  `config.load_secret_request_dir`.
- Produces in `bin/machine-stats`:
  - `secret_request_dir() -> (name, note)`.
  - `gather_needs(rows, targets, store, screens, interval) -> (items,
    notes)`: build, stamp (falling back to "first seen now, lower
    bound" when the store raises `OSError`), read screens, order, keep
    the list.
  - `Poller(interval, url="", request_dir="", store=None, light=False)`
    with `needs() -> (items | None, notes)`; `items` is None before the
    first poll.
  - `draw_line(screen, y, line, styles)`.
  - `dashboard(screen, interval, mode, mode_note, url="", excluded=(),
    request_dir="", store=None)`.

- [ ] **Step 1: Write the failing test**

`tests/test_needs_cli.py`:

```python
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
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_needs_cli.py`
Expected: FAIL (no "needs you" on screen; no `needs.json`).

- [ ] **Step 3: Implement in `bin/machine-stats`**

1. Imports: add `contextlib` and `os` to the standard imports, and
   `needs, needsview, seen, text` to the `from statslib import (...)`
   list.
2. After `pipeline_url`:

```python
def secret_request_dir():
    """The secret-prompt request directory name ("" for none), and a
    note when a bad value was ignored."""
    try:
        return config.load_secret_request_dir(herdr.config_dir(PLUGIN_ID))
    except herdr.HerdrError:
        return "", None  # deploy_mode already says there is no config dir


def gather_needs(rows, targets, store, screens, interval):
    """(items, notes) of one poll: built, stamped with first-seen times,
    blocked screens read, ordered, and kept for the popup."""
    stamp = time.time()
    items, notes = needs.build(rows, targets, stamp)
    answered = {row.label for row in rows if row.needs is not None}
    try:
        items = store.stamp(items, answered, stamp, interval)
    except OSError:  # no state dir: ages count from now, as lower bounds
        items = [i if i.first_seen is not None
                 else i._replace(first_seen=stamp, approx=True)
                 for i in items]
    items = needs.order(screens.fill(items))
    with contextlib.suppress(OSError):
        store.save_list(items, stamp)
    return items, notes
```

3. `Poller`:

```python
class Poller:
    """Polls every machine in the background; the view never blocks.

    ``light`` polls skip the CPU sample and the plugin list (the
    popup); rows then have needs data and no snapshot.
    """

    def __init__(self, interval, url="", request_dir="", store=None,
                 light=False):
        self.interval = interval
        self.watcher = pipeline.Watcher(url, interval) if url else None
        self.request_dir, self.light = request_dir, light
        self.store = store or seen.Store(seen.state_dir(os.environ))
        self.screens = needs.Screens(collect.read_screens)
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.history = render.History()
        self.rows, self.targets, self.note, self.updated = None, [], None, ""
        self.polled = None  # time.monotonic() when the latest poll began
        self.items, self.needs_notes = None, []
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            began = time.monotonic()
            found, note = load_machines()
            rows = collect.poll(socket.gethostname(), found,
                                stats=not self.light,
                                request_dir=self.request_dir)
            targets = [None, *(m.target for m in found)]
            with self.lock:
                self.history.record(rows)
                self.rows = rows
                self.targets = targets
                self.note = note
                self.updated = time.strftime("%H:%M:%S")
                self.polled = began
            items, notes = gather_needs(rows, targets, self.store,
                                        self.screens, self.interval)
            with self.lock:
                self.items, self.needs_notes = items, notes
            self.wake.wait(self.interval)
            self.wake.clear()

    def needs(self):
        """(items, notes) of the latest poll; items is None before it."""
        with self.lock:
            return self.items, self.needs_notes
```

   Keep `view`, `pipeline` and `refresh` as they are.

4. A shared line drawer, after `put`:

```python
def draw_line(screen, y, line, styles, x=0):
    """One line of ``(text, style)`` parts from column ``x``, placed by
    terminal cells."""
    for value, style in line:
        put(screen, y, x, value, styles.get(style, 0))
        x += text.cells(value)
```

5. In `draw`, after the `if not rows:` early return, draw the section
   and push the cards down:

```python
    items, needs_notes = poller.needs()
    if items is None:
        section = [needsview.fit([(" needs you: polling...", "dim")],
                                 width)]
    else:
        section = needsview.section(items, needs_notes, width, height,
                                    time.time())
    for n, line in enumerate(section):
        draw_line(screen, 1 + n, line, styles)
    extra = poller.watcher is not None
    columns, card_width = render.grid(len(rows) + extra, width)
    visible = max(1, (height - 2 - len(section)) // render.CARD_HEIGHT)
```

   (this replaces the existing `extra`, `columns` and `visible` lines).
   In the card loop use `top = 1 + len(section) + (i // columns) *
   render.CARD_HEIGHT`, and replace the inner `for n, line in
   enumerate(lines):` loop (with its `x` bookkeeping) by:

```python
        for n, line in enumerate(lines):
            draw_line(screen, top + n, line, styles, left)
```

6. `dashboard(screen, interval, mode, mode_note, url="", excluded=(),
   request_dir="", store=None)` creates `Poller(interval, url,
   request_dir, store)`.

7. In `main`, after `url, url_note = pipeline_url(args.pipeline)`:

```python
    request_dir, request_note = secret_request_dir()
    store = seen.Store(seen.state_dir(os.environ))
    curses.wrapper(dashboard, args.interval, mode,
                   join_notes(mode_note, exclude_note, url_note,
                              request_note), url, excluded, request_dir,
                   store)
```

8. In `tests/test_cli.py`, `test_the_poller_reports_when_its_latest_poll_began`
   stubs `collect.poll` with two arguments; `Poller.loop` now passes
   `stats` and `request_dir`, so change the stub to:

```python
    monkeypatch.setattr(collect, "poll", lambda label, found, **kw: [])
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run --with pytest --with flake8 python -m pytest -q`
Expected: PASS, including the existing `test_cli.py` dashboard tests.

- [ ] **Step 5: Commit**

```bash
git add bin/machine-stats tests/test_needs_cli.py tests/test_cli.py
git commit -m "✨ feat(needs): the needs-you section above the cards"
```

---

### Task 10: `!` for the full list, Enter to jump

**Files:**
- Create: `statslib/jump.py`
- Modify: `bin/machine-stats`
- Test: `tests/test_needs_cli.py`

**Interfaces:**
- Consumes: `herdr.focus`, `herdr.focus_shell` (Task 7),
  `collect.run_host`, `collect.PATH_LINE`, `collect.HostError`,
  `needsview.full/legend/where_text`, `draw_line` (Task 9).
- Produces:
  - `jump.jump(item, run=None) -> (landed: bool, message: str |
    None)`: this machine's pane is focused and `landed` is True; a
    remote pane is focused on its machine and the message says where it
    is; a failure says why.
  - In `bin/machine-stats`: `LIST_KEYS`, `list_step(key, pick, count)`,
    `draw_list(screen, styles, title, items, notes, pick, top, footer)
    -> top`.

- [ ] **Step 1: Write the failing tests** (append to
  `tests/test_needs_cli.py`; add `from statslib import collect, jump`
  and `from statslib.needs import Item, Where` to the imports)

```python
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
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_needs_cli.py`
Expected: FAIL (`statslib.jump` missing; `!` does nothing).

- [ ] **Step 3: Write `statslib/jump.py`**

```python
"""Enter on a needs-you item: focus its pane, here or on its machine.

Herdr focuses per server, and nothing in its API switches which machine
your window shows, so a pane on another machine is focused there and
the message says where to find it (spec, "Jumping to a pane").
Focusing marks a finished agent seen.
"""

from statslib import collect, herdr, needsview


def jump(item, run=None):
    """(landed, message). ``landed``: the pane is now in front of you."""
    try:
        if item.target is None:
            herdr.focus(item.pane_id)
            return True, None
        (run or collect.run_host)(
            item.target,
            collect.PATH_LINE + "\n" + herdr.focus_shell(item.pane_id))
    except (herdr.HerdrError, collect.HostError) as exc:
        return False, f"{item.machine}: could not focus: {exc}"
    where = needsview.where_text(item.where) or f"the pane of {item.agent}"
    return False, (f"{item.machine}: {where}. "
                   f"Pick {item.machine} with prefix+w")
```

- [ ] **Step 4: Add the full list to `bin/machine-stats`**

Import `jump` with the other `statslib` modules, then add after
`draw`:

```python
LIST_KEYS = " ↑↓ select  Enter jump  r refresh  ! cards"
LIST_MOVES = {curses.KEY_DOWN: 1, ord("j"): 1, curses.KEY_UP: -1,
              ord("k"): -1, curses.KEY_NPAGE: 5, curses.KEY_PPAGE: -5}


def list_step(key, pick, count):
    """The selection in the full list after ``key``."""
    return render.step(pick, LIST_MOVES.get(key, 0), max(count, 1))


def draw_list(screen, styles, title, items, notes, pick, top, footer):
    """The full list, scrolled so the selected item shows; returns the
    new scroll position."""
    height, width = screen.getmaxyx()
    screen.erase()
    put(screen, 0, 0, title.ljust(width), styles["bar"])
    lines, starts = needsview.full(items, notes, width, time.time(), pick)
    room = max(1, height - 2)
    if starts:
        first = starts[pick]
        last = (starts[pick + 1] if pick + 1 < len(starts)
                else len(lines)) - 1
        top = max(min(top, first), last - room + 1)
    top = max(0, min(top, max(0, len(lines) - room)))
    for n, line in enumerate(lines[top:top + room]):
        draw_line(screen, 1 + n, line, styles)
    draw_line(screen, height - 1, needsview.legend(width, footer), styles)
    screen.refresh()
    return top
```

In `dashboard`, add `listing, pick, top = False, 0, 0` next to the
other state, and right after `start_deploys(deployer, here, picks)`:

```python
        if listing:
            items, needs_notes = poller.needs()
            items = items or []
            pick = render.step(pick, 0, max(len(items), 1))
            top = draw_list(screen, styles,
                            f" needs you  {view[3] or '--:--:--'}", items,
                            needs_notes, pick, top, message or LIST_KEYS)
            key = screen.getch()
            if key == -1:
                continue
            message = None  # a jump's message stays until the next key
            if key in (ord("!"), ord("q"), 27):
                listing = False
            elif key == ord("r"):
                poller.refresh()
            elif key in ENTER_KEYS and items:
                _landed, message = jump.jump(items[pick])
                poller.refresh()  # a focused finished agent is now seen
            else:
                pick = list_step(key, pick, len(items))
            continue
```

In the cards branch, before `elif key in moves and rows:`:

```python
        elif key == ord("!"):
            listing, pick, top, message = True, 0, 0, None
```

and in `draw`, change the keys line to
`" arrows move  Enter btop  d deploy  ! needs you  r refresh  q quit"`.

- [ ] **Step 5: Run the whole suite**

Run: `uv run --with pytest --with flake8 python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add statslib/jump.py bin/machine-stats tests/test_needs_cli.py
git commit -m "✨ feat(needs): ! opens the full list; Enter focuses the pane"
```

---

### Task 11: The popup, `--once --needs` and the manifest

**Files:**
- Modify: `bin/machine-stats`, `herdr-plugin.toml`
- Test: `tests/test_needs_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `--needs` (the popup: full list only, light polls every 5 s
  unless `--interval` is given, the last list from `needs-list.json`
  until the first poll), `--once --needs` (plain text via
  `needsview.plain`), `popup(screen, interval, request_dir, store)`,
  `print_needs(request_dir, store, interval)`, the manifest's `needs`
  pane and action.

- [ ] **Step 1: Write the failing tests** (append; add `import
  subprocess`, `import sys`, `import tomllib` and `from statslib import
  seen` to the imports)

```python
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
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --with pytest --with flake8 python -m pytest -q tests/test_needs_cli.py`
Expected: FAIL (`--needs` is not an option; no `needs` pane).

- [ ] **Step 3: Implement in `bin/machine-stats`**

After `draw_list`:

```python
POPUP_KEYS = " ↑↓ select  Enter jump  r refresh  q close"


def popup(screen, interval, request_dir, store):
    """The popup: the full list only. Enter on this machine's pane
    focuses it and closes; on another machine's it says where it is."""
    styles = start_colors()
    screen.timeout(250)
    cached, as_of = store.load_list()
    poller = Poller(interval, request_dir=request_dir, store=store,
                    light=True)
    pick, top, message = 0, 0, None
    while True:
        items, notes = poller.needs()
        title = " needs you"
        if items is None:  # before the first poll: the last list kept
            items, notes = cached, []
            title += (time.strftime("  as of %H:%M:%S",
                                    time.localtime(as_of))
                      if as_of else "  polling...")
        pick = render.step(pick, 0, max(len(items), 1))
        top = draw_list(screen, styles, title, items, notes, pick, top,
                        message or POPUP_KEYS)
        key = screen.getch()
        if key == -1:
            continue
        message = None  # where a remote pane is stays until a key
        if key in (ord("q"), 27):
            return
        if key == ord("r"):
            poller.refresh()
        elif key in ENTER_KEYS and items:
            landed, message = jump.jump(items[pick])
            if landed:
                return
            poller.refresh()
        else:
            pick = list_step(key, pick, len(items))


def print_needs(request_dir, store, interval):
    """``--once --needs``: one light poll, the list as plain text."""
    found, note = load_machines()
    if note:
        print(note, file=sys.stderr)
    rows = collect.poll(socket.gethostname(), found, stats=False,
                        request_dir=request_dir)
    targets = [None, *(m.target for m in found)]
    items, notes = gather_needs(rows, targets, store,
                                needs.Screens(collect.read_screens),
                                interval)
    for line in needsview.plain(items, notes, time.time()):
        print(line)
```

In `main`:

```python
    parser.add_argument("--interval", type=float, default=None,
                        help="seconds between polls (default 10; 5 with "
                        "--needs)")
    parser.add_argument("--needs", action="store_true",
                        help="only the needs-you list: the popup, or "
                        "with --once a plain list")
```

replace the `--interval` check with:

```python
    interval = args.interval
    if interval is None:
        interval = 5 if args.needs else 10
    if interval < 1:
        parser.error("--interval must be at least 1 second")
```

and, keeping the existing `--once` table branch first but guarded by
`if args.once and not args.needs:`, add before the deploy settings are
read:

```python
    request_dir, request_note = secret_request_dir()
    store = seen.Store(seen.state_dir(os.environ))
    if args.needs:
        if request_note:
            print(request_note, file=sys.stderr)
        if args.once:
            print_needs(request_dir, store, interval)
        else:
            curses.wrapper(popup, interval, request_dir, store)
        return 0
```

(Delete Task 9's `request_dir`/`store` pair after the `url, url_note`
line, since it now comes earlier; the dashboard call then uses
`interval` instead of `args.interval`.)
Update the module docstring's usage line to
`machine-stats [--interval SECONDS] [--once] [--needs] [--deploy MODE]
[--pipeline URL]` and add one sentence: "--needs shows only the
needs-you list (the popup); with --once it prints it."

- [ ] **Step 4: Add the pane and the action to `herdr-plugin.toml`**

After the `dashboard` pane:

```toml
# What waits on you, on every machine: a popup over whatever you do.
[[panes]]
id = "needs"
title = "needs you"
placement = "popup"
width = "90%"
height = "80%"
command = ["python3", "bin/machine-stats", "--needs"]
platforms = ["linux", "macos"]
```

After the `open` action:

```toml
[[actions]]
id = "needs"
title = "Show what needs you"
contexts = ["workspace"]
command = ["herdr", "plugin", "pane", "open", "--plugin", "renzof.herdr-machine-stats", "--entrypoint", "needs", "--placement", "popup", "--focus"]
platforms = ["linux", "macos"]
```

- [ ] **Step 5: Run the whole suite**

Run: `uv run --with pytest --with flake8 python -m pytest -q`
Expected: PASS. If `test_the_popup_shows_the_last_list_at_once` is
flaky, raise its `delay`; the first light poll must not finish before
the first draw.

- [ ] **Step 6: Commit**

```bash
git add bin/machine-stats herdr-plugin.toml tests/test_needs_cli.py
git commit -m "✨ feat(needs): the needs-you popup and --once --needs"
```

---

### Task 12: Docs, the safety wording and the version

**Files:**
- Modify: `README.md`, `AGENTS.md`, `herdr-plugin.toml` (version),
  `docs/specs/2026-10-27-needs-you-design.md` (code table)

- [ ] **Step 1: README**

1. In the card bullets, replace `- **Agents**: ◐ blocked, ● working, ○
   idle, ✓ done.` with `- **Agents**: see "Status marks" below.` and
   add `!` to the **Keys** bullet: "`!` shows the full needs-you list
   (below)".
2. Add after the card bullets:

````markdown
## Status marks

One legend for the cards, the needs-you list and the popup:

| Mark | Meaning |
|---|---|
| ◐ | blocked: waiting on you |
| ● | working |
| ○ | idle |
| ✓ | done: finished, not yet seen |
| 🔑 | secret requested |
| ? | a status this plugin does not know |

## What needs you

Above the cards, one list of every agent, on every machine, that waits
on you: blocked agents, open secret requests, and agents that finished
and you have not looked at yet, oldest first. A blocked agent shows the
last lines of its screen; a finished one, its title. `!` opens the full
list: arrows select, Enter jumps to the pane, `!` goes back.

- **This machine**: Enter focuses the pane.
- **Another machine**: Enter focuses the pane on that machine and says
  where it is, for example `laptop: workspace 5 api, tab 18 'review'.
  Pick laptop with prefix+w`: Herdr has no way for a plugin to switch
  which machine your window shows.
- Focusing a finished agent marks it seen, and it leaves the list.
- Ages count from the first poll that saw the wait (`12m+` when the
  dashboard was not running then); they are kept in the plugin's state
  directory on this machine, never elsewhere, and hold no screen text.
- A machine that is down or has no Herdr is listed as not counted, so
  an empty list never hides a machine that could not be asked.

The same list opens as a popup from Herdr's actions ("Show what needs
you"), or with a key in Herdr's `config.toml`:

```toml
[[keys.command]]
key = "prefix+u"
type = "plugin_action"
command = "renzof.herdr-machine-stats.needs"
description = "needs you"
```

`python3 bin/machine-stats --once --needs` prints the list as plain
text.

### Secret requests

If you run a secret-prompt plugin that keeps a directory per request,
name that directory in `config.toml` and its open requests join the
list (off by default):

```toml
secret_request_dir = "secret-prompt"   # default "": none
```

On each machine the dashboard looks in `$XDG_RUNTIME_DIR/<name>`,
`/run/user/<uid>/<name>` and `~/.local/state/<name>` for directories
named `r-` and eight hex digits, owned by you with mode 0700, under a
day old. It reads only `request.json`, `pane.json` and `state.json`
(size-capped) and whether `result.json` or `cancel.json` exist, and
keeps only the request's times, panes and purpose: never a value, a
path or a key name.
````

3. In the paragraph "Each machine is read with one non-interactive SSH
   call…", replace "Reads are read-only: nothing is written to the
   machines. The only thing ever installed on another machine is this
   plugin, by an explicit deploy, and deploy is off by default." with
   "Reads are read-only: nothing is written to the machines. The only
   changes ever made on another machine are installing this plugin, by
   an explicit deploy (off by default), and focusing a pane, when you
   press Enter on it in the needs-you list."

- [ ] **Step 2: AGENTS.md**

Replace the module bullets and the last bullet with:

```markdown
- `statslib/collect.py`: the POSIX collector script and polling;
  `render.py`: cards and the status legend; `deploy.py`: plugin state
  and installs; `config.py`: the `deploy`, `deploy_exclude`,
  `pipeline_url` and `secret_request_dir` settings; `pipeline.py`: the
  optional pipeline card's `/status` read; `herdr.py`: the only module
  that names the `herdr` CLI.
- Needs-you list: `needs.py` (items and order), `prompts.py` (secret
  requests, metadata only), `seen.py` (first-seen times, local only),
  `text.py` (cleaning and cell widths), `needsview.py` (drawing),
  `jump.py` (Enter). Spec: `docs/specs/2026-10-27-needs-you-design.md`.
- Reads are read-only. The only changes ever made on another machine
  are this plugin, by an explicit deploy, and focusing a pane when you
  press Enter in the needs-you list. The pipeline card only GETs a URL.
```

- [ ] **Step 3: The spec's code table**

In `docs/specs/2026-10-27-needs-you-design.md`, section "Code", change
the `statslib/collect.py` row's "`Snapshot.needs` (the parsed agents,
workspaces, tabs, requests and host clock); `Machine` unchanged" to
"`Row.needs` (the parsed agents, workspaces, tabs, requests and host
clock; a light poll has no snapshot); `Machine` unchanged", trim the
`statslib/needs.py` row to "`Raw`, `Item`, `Where`, `Note`; building and
ordering the list; screen lines", and add rows for `statslib/text.py`,
`statslib/prompts.py`, `statslib/seen.py`, `statslib/needsview.py` and
`statslib/jump.py` with one line each, as in AGENTS.md.

- [ ] **Step 4: Version**

`herdr-plugin.toml`: `version = "0.5.0"`.

- [ ] **Step 5: Full suite and the public-repo scrub**

Run: `uv run --with pytest --with flake8 python -m pytest -q`
Expected: PASS.

Run the scrub over everything this work added or changed:

```bash
git diff origin/main.. -- . ':!docs/plans' | grep '^+' | grep -n -i -E \
  '10\.[0-9]+\.[0-9]+\.[0-9]+|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.|vault|co-authored|generated with' \
  || echo clean
```

Expected: `clean` (only added lines are checked; the existing tests'
example addresses predate this work). Check that `git log origin/main..`
shows no AI attribution.

- [ ] **Step 6: Commit**

```bash
git add README.md AGENTS.md herdr-plugin.toml \
  docs/specs/2026-10-27-needs-you-design.md
git commit -m "🔖 chore: version 0.5.0 (needs-you list and popup)"
```

---

## Finishing

- Open a pull request from the work branch; do not merge it yourself
  without the owner's review, do not deploy, and do not touch any
  installed or linked copy of the plugin.
- Copy the spec's "Manual checks on real Herdr" (1 to 5) into the PR
  description as unchecked boxes; they need a real Herdr session with
  saved machines and are run by the owner. Add a sixth: Herdr accepts
  the manifest's `needs` pane with `width`/`height` (if it rejects
  them, drop the two keys).
- Note in the PR anything that deviated from this plan, with the
  reason.
