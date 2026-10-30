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
