"""Drawing for the fleet dashboard, as plain data so it can be tested.

A card is a list of lines; a line is a list of ``(text, style)`` parts
whose texts add up to the card's width exactly. Style names are mapped to
terminal colours by the curses front end (``bin/fleet``).
"""

from fleetlib.collect import row_level

CARD_HEIGHT = 6
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


def _border(row, selected):
    if selected:
        return "selected"
    return {"down": "red", "dim": "dim", "alert": "yellow"}.get(
        row_level(row), "border")


def card(row, history, width, selected=False):
    """The lines of one machine's card, each exactly ``width`` wide."""
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
        ]
    sides = [[("│", edge), *line, ("│", edge)] for line in body]
    bottom = [("╰", edge), ("─" * inner, edge), ("╯", edge)]
    return [top, *sides, bottom]
