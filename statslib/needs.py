"""The needs-you list: what waits on you, on every machine.

``parse_raw`` reads one host's part of the collector output; later
functions turn rows into ordered items. What each group means is in
docs/specs/2026-10-27-needs-you-design.md.
"""

from collections import namedtuple

from statslib import herdr, prompts, text

# One host's needs data: its clock (epoch seconds, or None), the agent
# list, {workspace_id: (number, label)}, {tab_id: (number, label)} and
# its open secret requests, and the panes of every secret prompt there
# (open request or not).
Raw = namedtuple("Raw", "now agents workspaces tabs requests prompt_panes",
                 defaults=(frozenset(),))


def parse_raw(parts):
    """A ``Raw`` from ``collect.sections`` of one host's output."""
    facts = dict(line.split("=", 1)
                 for line in parts.get("facts", "").splitlines()
                 if "=" in line)
    try:
        now = int(facts.get("now", ""))
    except ValueError:
        now = None
    requests = (prompts.parse(parts.get("requests", ""), now)
                if now is not None else [])
    return Raw(now, herdr.agents(parts.get("agents", "")),
               herdr.workspaces(parts.get("workspaces", "")),
               herdr.tabs(parts.get("tabs", "")), requests,
               prompts.panes(parts.get("requests", "")))


GROUPS = ("blocked", "secret", "done")  # the order they are listed in
AGENT_GROUPS = ("blocked", "done")
# The numbers and labels Herdr's screen shows; a number may be None.
Where = namedtuple("Where", "workspace workspace_label tab tab_label")
# One line of the list. Times are epoch seconds on this machine's clock.
# ``screen``: the pane is a known coding agent, so its screen may be read
# for the detail lines; any other pane (a secret prompt reports itself as
# a blocked agent) shows its labels and title only (D7).
Item = namedtuple(
    "Item", "group rank machine target pane_id seq agent project where"
    " detail deadline first_seen approx key screen", defaults=(False,))
# The agent kinds Herdr can start, so the ones it reports for coding
# agents whose screens are read: the list in `herdr agent start --help`
# of Herdr 0.9.5. Any other kind shows labels and title only.
CODING_AGENTS = frozenset({
    "pi", "claude", "codex", "gemini", "cursor", "devin", "agy", "cline",
    "omp", "mastracode", "opencode", "copilot", "kimi", "kiro", "droid",
    "amp", "grok", "hermes", "kilo", "qodercli", "qwen", "letta", "maki",
    "muse"})
# A machine whose agents could not be asked, and why.
Note = namedtuple("Note", "machine reason")
LAST = 1 << 30  # sorts an unknown workspace or tab number last


def _name(agent):
    for field in ("name", "display_agent", "agent"):
        name = text.clean(agent.get(field))
        if name:
            return name
    return "agent"


def _kind(agent):
    kind = agent.get("agent")
    return kind.strip().lower() if isinstance(kind, str) else ""


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
    prompt_panes = set(raw.prompt_panes)
    prompt_panes.update(r.prompt_pane for r in raw.requests
                        if r.prompt_pane)
    items = []
    for pane_id, agent in panes.items():
        status = agent.get("agent_status")
        if status not in AGENT_GROUPS or pane_id in prompt_panes:
            continue
        items.append(Item(
            status, rank, machine, target, pane_id, _seq(agent),
            _name(agent), _project(agent),
            _where(raw, agent.get("workspace_id"), agent.get("tab_id")),
            _first_detail(agent, status), None, None, False,
            (machine, pane_id), _kind(agent) in CODING_AGENTS))
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
            None if request.deadline is None else request.deadline + shift,
            request.created + shift, False,
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
            reason = (f"down: {text.clean(row.error)}" if row.error
                      else "no herdr")
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
        blocked = [i for i in items if i.group == "blocked" and i.screen]
        wanted = {}
        for item in blocked:
            if (item.machine, item.pane_id, item.seq) not in self.lines:
                wanted.setdefault((item.machine, item.target), []).append(
                    item.pane_id)
        for (machine, target), panes in wanted.items():
            read = self.read(target, panes)
            for item in blocked:
                # A failed read, or a pane the host did not return, is
                # not remembered: it is read again at the next poll.
                if (item.machine == machine and item.pane_id in panes
                        and item.pane_id in read):
                    self.lines[(machine, item.pane_id, item.seq)] = tuple(
                        text.meaningful(read[item.pane_id]))
        live = {(i.machine, i.pane_id, i.seq) for i in blocked}
        self.lines = {k: v for k, v in self.lines.items() if k in live}
        return [i._replace(detail=self.lines.get(
                    (i.machine, i.pane_id, i.seq)) or i.detail)
                if i.group == "blocked" and i.screen else i for i in items]
