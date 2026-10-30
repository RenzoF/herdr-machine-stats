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
