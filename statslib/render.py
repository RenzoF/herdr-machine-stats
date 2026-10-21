"""Drawing for the machine stats dashboard, as plain data so it can be tested.

A card is a list of lines; a line is a list of ``(text, style)`` parts
whose texts add up to the card's width exactly. Style names are mapped to
terminal colours by the curses front end (``bin/machine-stats``).
"""

from statslib.collect import row_level
from statslib.deploy import linked

CARD_HEIGHT = 7
MIN_CARD = 40  # narrower cards leave the gauges too short to read
TAIL = 8  # columns after each gauge: sparkline or used/total size
SPARKS = "▁▂▃▄▅▆▇█"
# Status symbols and styles, in the order a person watching cares about.
AGENT_MARKS = (
    ("blocked", "◐", "red"),
    ("working", "●", "green"),
    ("idle", "○", "dim"),
    ("done", "✓", "blue"),
)
NOTE_STYLES = {"current": "green", "older": "yellow", "newer": "blue",
               "missing": "yellow", "unknown": "dim"}


def bar(pct, width):
    """A gauge of ``width`` cells, filled to ``pct`` percent."""
    filled = min(width, int(pct * width / 100 + 0.5))
    return "█" * filled + "░" * (width - filled)


def band(pct):
    """The colour for a percentage: green, then yellow, then red."""
    if pct < 60:
        return "green"
    return "yellow" if pct < 85 else "red"


def sparkline(values, width):
    """The latest ``width`` percentages as block heights."""
    recent = values[-width:] if width > 0 else []
    return "".join(
        SPARKS[min(7, int(v * 7 / 100 + 0.5))] for v in recent)


class History:
    """Recent CPU percentages per machine, oldest first."""

    def __init__(self, size=30):
        self.size = size
        self.values = {}

    def record(self, rows):
        for row in rows:
            if row.snapshot is not None:
                kept = self.values.setdefault(row.label, [])
                kept.append(row.snapshot.cpu_pct)
                del kept[:-self.size]

    def cpu(self, label):
        return list(self.values.get(label, []))


def grid(count, width):
    """(columns, card width) for ``count`` cards across ``width``."""
    columns = max(1, min(count, width // MIN_CARD))
    return columns, width // columns


def _fit(parts, width):
    """``parts`` cut or padded with spaces to exactly ``width`` columns."""
    out, used = [], 0
    for text, style in parts:
        if used >= width:
            break
        text = text[:width - used]
        out.append((text, style))
        used += len(text)
    if used < width:
        out.append((" " * (width - used), "text"))
    return out


def _size(used_kb, total_kb):
    gib = 1048576
    text = f"{round(used_kb / gib)}/{round(total_kb / gib)}G"
    if len(text) > TAIL:
        text = f"{used_kb / gib / 1024:.1f}/{total_kb / gib / 1024:.1f}T"
    return text


def _gauge(label, pct, tail, tail_style, inner):
    # " LABEL" 6, gauge, " " 1, "100%" 4, " " 1, tail, " " 1.
    width = max(1, inner - 13 - TAIL)
    filled = len(bar(pct, width).rstrip("░"))
    cells = [("█", band((i + 1) * 100 / width)) for i in range(filled)]
    cells += [("░", "dim")] * (width - filled)
    return _fit([(f" {label:<5}", "label"), *cells, (" ", "text"),
                 (f"{pct:3d}%", band(pct)), (" ", "text"),
                 (tail.ljust(TAIL), tail_style)], inner)


def _footer(snap, inner):
    parts = [(f" load {snap.load:.1f}", "label")]
    counts = snap.agents
    if counts is None:
        parts.append(("  no herdr", "dim"))
    elif not counts:
        parts.append(("  no agents", "dim"))
    else:
        known = {status for status, _mark, _style in AGENT_MARKS}
        for status, mark, style in AGENT_MARKS:
            if counts.get(status):
                parts += [("  ", "text"), (f"{mark} {counts[status]}", style)]
        for status in sorted(set(counts) - known):
            parts += [("  ", "text"), (f"? {counts[status]}", "yellow")]
    return _fit(parts, inner)


def plugin_note(state, entry, status):
    """The card's plugin line: the latest deploy, else the state."""
    if status:
        style = ("red" if status.startswith(("failed", "refused"))
                 else "green" if status == "deployed" else "yellow")
        return f"plugin {status}", style
    if linked(entry):
        return "plugin linked", "dim"
    return f"plugin {state}", NOTE_STYLES.get(state, "dim")


def _border(row, selected):
    if selected:
        return "selected"
    return {"down": "red", "dim": "dim", "alert": "yellow"}.get(
        row_level(row), "border")


def card(row, history, width, selected=False, note=None):
    """The lines of one machine's card, each exactly ``width`` wide.

    ``note`` is an optional ``(text, style)`` pair for the plugin line.
    """
    edge = _border(row, selected)
    inner = width - 2
    snap = row.snapshot
    info = f" {snap.os} · {snap.ncpu}c " if snap else ""
    name = row.label[:max(1, width - 7)]
    fill = width - 6 - len(name) - len(info)
    if fill < 1:
        info, fill = "", max(0, width - 6 - len(name))
    top = [("╭─ ", edge), (name, "title"), (" ", edge),
           ("─" * fill, edge), (info, "dim"), ("─╮", edge)]
    if snap is None:
        if row.error == "disabled":
            first = _fit([(" disabled", "dim")], inner)
        else:
            first = _fit([(f" down: {row.error}", "red")], inner)
        body = [first] + [_fit([], inner)] * (CARD_HEIGHT - 3)
    else:
        body = [
            _gauge("CPU", snap.cpu_pct,
                   sparkline(history.cpu(row.label), TAIL), "spark", inner),
            _gauge("MEM", snap.mem_pct,
                   _size(snap.mem_used_kb, snap.mem_total_kb), "label",
                   inner),
            _gauge("DISK", snap.disk_pct,
                   _size(snap.disk_used_kb, snap.disk_total_kb), "label",
                   inner),
            _footer(snap, inner),
            _fit([(f" {note[0]}", note[1])] if note else [], inner),
        ]
    sides = [[("│", edge), *line, ("│", edge)] for line in body]
    bottom = [("╰", edge), ("─" * inner, edge), ("╯", edge)]
    return [top, *sides, bottom]


def summary(rows):
    """One line for the title bar, for example "6 machines · 5 up"."""
    levels = [row_level(row) for row in rows]
    noun = "machine" if len(rows) == 1 else "machines"
    parts = [f"{len(rows)} {noun}",
             f"{sum(row.snapshot is not None for row in rows)} up"]
    if levels.count("down"):
        parts.append(f"{levels.count('down')} down")
    if levels.count("alert"):
        parts.append(f"{levels.count('alert')} alert")
    return " · ".join(parts)


def step(selected, delta, count):
    """The selection after moving ``delta`` cards, kept on a card."""
    return max(0, min(count - 1, selected + delta))


# -- the pipeline card ---------------------------------------------------

LEVEL_EDGES = {"stuck": "red", "attention": "yellow", "ok": "border",
               "unreachable": "dim"}
LEVEL_STYLES = {"stuck": "red", "attention": "yellow", "ok": "green"}
WORKER_LINES = CARD_HEIGHT - 4  # the body minus the counters and verdict


def age_text(seconds):
    """A short age: 45s, 12m, 3h05m, 2d."""
    if seconds is None:
        return "?"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"
    return f"{seconds // 86400}d"


def _cut_ref(ref, room):
    """``ref`` ("repo#12") in ``room`` columns: the repo name gives way
    and the issue number stays."""
    if len(ref) <= room:
        return ref
    repo, _, issue = ref.rpartition("#")
    keep = room - len(issue) - 2  # "…#" and the number
    if not repo or keep < 1:
        return ref[:max(room, 0)]
    return f"{repo[:keep]}…#{issue}"


def _worker_lines(workers, inner):
    shown = workers
    if len(workers) > WORKER_LINES:
        shown = workers[:WORKER_LINES - 1]
    name = max((len(w.name) for w in shown), default=0)
    stage = max((len(w.stage or "") for w in shown), default=0)
    harness = max((len(w.harness) for w in shown), default=0)
    # " name stage ref age harness": what is left after the other columns.
    fixed = 1 + name + 1 + stage + 1 + 1 + 4
    # On a narrow card the harness is the first thing to go: the repo
    # and issue matter more.
    show_harness = bool(harness) and inner - fixed - (1 + harness) >= 12
    if show_harness:
        fixed += 1 + harness
    room = max(6, inner - fixed)
    refs = {w.name: _cut_ref(w.ref, room) for w in shown}
    ref = max((len(r) for r in refs.values()), default=0)
    lines = []
    for w in shown:
        if w.stage is None:
            idle = "idle" + (f" {age_text(w.age)}" if w.age is not None
                             else "")
            lines.append(_fit([(f" {w.name:<{name}} ", "label"),
                               (idle, "dim")], inner))
            continue
        parts = [(f" {w.name:<{name}} ", "label"),
                 (f"{w.stage:<{stage}} ", "text"),
                 (f"{refs[w.name]:<{ref}} ", "title"),
                 (f"{age_text(w.age):>4}", "text")]
        if w.harness and show_harness:
            parts.append((f" {w.harness}", "dim"))
        lines.append(_fit(parts, inner))
    if len(workers) > WORKER_LINES:
        lines.append(_fit([(f" +{len(workers) - len(shown)} more", "dim")],
                          inner))
    return lines + [_fit([], inner)] * (WORKER_LINES - len(lines))


def _counters(view, inner):
    parts = [(" ", "text")]
    if view.ci is not None:
        in_use, cap = view.ci
        full = in_use >= cap and view.waiting
        parts += [(f"CI {in_use}/{cap}", "yellow" if full else "label"),
                  ("  ", "text")]
    parts += [(f"waiting {view.waiting}", "label"), ("  ", "text"),
              (f"failed {view.failed}",
               "yellow" if view.failed else "label"), ("  ", "text"),
              (f"cards {view.cards}", "yellow" if view.cards else "label")]
    return _fit(parts, inner)


def pipeline_card(view, width):
    """The pipeline card's lines, each exactly ``width`` wide.

    ``view`` is a ``pipeline.View`` (nothing yet: None, drawn as polling).
    """
    inner = width - 2
    level = view.level if view else "unreachable"
    edge = LEVEL_EDGES[level]
    info = ""
    if view and view.error is None and view.capacity is not None:
        noun = "worker" if view.capacity == 1 else "workers"
        info = f" {view.capacity} {noun} "
    name = "pipeline"
    fill = width - 6 - len(name) - len(info)
    if fill < 1:
        info, fill = "", width - 6 - len(name)
    top = [("╭─ ", edge), (name, "title"), (" ", edge),
           ("─" * max(0, fill), edge), (info, "dim"), ("─╮", edge)]
    blank = _fit([], inner)
    if view is None:
        body = [_fit([(" polling...", "dim")], inner)]
        body += [blank] * (CARD_HEIGHT - 3)
    elif view.error is not None:
        body = [_fit([(" unreachable", "yellow"),
                      (f": {view.error}", "dim")], inner)]
        body += [blank] * (CARD_HEIGHT - 3)
    else:
        last = ("no lease yet" if view.last_lease is None
                else f"last lease {age_text(view.last_lease)} ago")
        body = [*_worker_lines(view.workers, inner), _counters(view, inner),
                _fit([(f" {view.verdict}", LEVEL_STYLES[view.level]),
                      (f"  {last}", "dim")], inner)]
    sides = [[("│", edge), *line, ("│", edge)] for line in body]
    bottom = [("╰", edge), ("─" * inner, edge), ("╯", edge)]
    return [top, *sides, bottom]
