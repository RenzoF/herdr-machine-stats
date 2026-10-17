"""statslib.render: bars, colour bands, sparklines and machine cards."""

import pytest

from statslib import collect, render


def snap(**changes):
    base = dict(os="Linux", ncpu=12, load=4.31, cpu_pct=46, mem_pct=65,
                mem_used_kb=15 * 1048576, mem_total_kb=23 * 1048576,
                disk_pct=64, disk_used_kb=74 * 1048576,
                disk_total_kb=118 * 1048576,
                agents={"working": 1, "idle": 8, "done": 5},
                plugin=None)
    base.update(changes)
    return collect.Snapshot(**base)


def text(line):
    return "".join(part for part, _style in line)


def styles_of(line, part):
    return [style for text_, style in line if text_ == part]


@pytest.mark.parametrize("pct, width, want", [
    (50, 10, "█████░░░░░"),
    (12, 10, "█░░░░░░░░░"),  # 1.2 cells rounds to one
    (0, 4, "░░░░"),
    (100, 4, "████"),
    (130, 4, "████"),  # never wider than the gauge
])
def test_bar_fills_its_share_of_the_width(pct, width, want):
    assert render.bar(pct, width) == want


@pytest.mark.parametrize("pct, want", [
    (0, "green"), (59, "green"), (60, "yellow"), (84, "yellow"),
    (85, "red"), (100, "red"),
])
def test_band_turns_from_green_through_yellow_to_red(pct, want):
    assert render.band(pct) == want


def test_sparkline_scales_zero_to_hundred_onto_eight_steps():
    assert render.sparkline([0, 50, 100], 10) == "▁▅█"


def test_sparkline_keeps_only_the_latest_values_that_fit():
    assert render.sparkline([100, 100, 0, 0, 0], 3) == "▁▁▁"
    assert render.sparkline([], 5) == ""


def test_history_keeps_recent_cpu_per_machine_and_skips_down_rows():
    history = render.History(size=3)
    for cpu in (10, 20, 30, 40):
        history.record([collect.Row("a", snap(cpu_pct=cpu), None),
                        collect.Row("b", None, "timeout")])
    assert history.cpu("a") == [20, 30, 40]
    assert history.cpu("b") == []


@pytest.mark.parametrize("count, width, want", [
    (6, 140, (3, 46)),
    (6, 100, (2, 50)),
    (6, 30, (1, 30)),
    (2, 200, (2, 100)),  # no empty columns when there are few machines
])
def test_grid_fits_as_many_columns_as_the_width_allows(count, width, want):
    assert render.grid(count, width) == want


def card(row, width=46, selected=False, cpu=(10, 50, 90)):
    history = render.History()
    history.values[row.label] = list(cpu)
    return render.card(row, history, width, selected)


def test_card_shows_gauges_sizes_load_and_agents_at_its_exact_width():
    lines = card(collect.Row("agent-desk", snap(), None))
    assert [len(text(line)) for line in lines] == [46] * render.CARD_HEIGHT
    body = [text(line) for line in lines]
    assert "agent-desk" in body[0] and "Linux · 12c" in body[0]
    assert "CPU" in body[1] and "46%" in body[1] and "▂▅▇" in body[1]
    assert "MEM" in body[2] and "65%" in body[2] and "15/23G" in body[2]
    assert "DISK" in body[3] and "64%" in body[3] and "74/118G" in body[3]
    assert "load 4.3" in body[4]
    assert "● 1" in body[4] and "○ 8" in body[4] and "✓ 5" in body[4]


def test_card_colours_each_value_by_its_band():
    lines = card(collect.Row("MBP", snap(cpu_pct=20, disk_pct=92), None))
    assert styles_of(lines[1], " 20%") == ["green"]
    assert styles_of(lines[3], " 92%") == ["red"]


def test_a_full_gauge_runs_from_green_to_red():
    lines = card(collect.Row("hot", snap(cpu_pct=100), None))
    cells = [style for part, style in lines[1] if part == "█"]
    assert cells[0] == "green" and cells[-1] == "red"
    assert "yellow" in cells


def test_blocked_agents_are_red_and_counted_first():
    lines = card(collect.Row("a", snap(agents={"idle": 2, "blocked": 1}),
                             None))
    footer = text(lines[4])
    assert footer.index("◐ 1") < footer.index("○ 2")
    assert styles_of(lines[4], "◐ 1") == ["red"]


@pytest.mark.parametrize("row, selected, want", [
    (collect.Row("a", snap(agents={}), None), False, "border"),
    (collect.Row("a", snap(agents={}), None), True, "selected"),
    (collect.Row("a", snap(agents={}, mem_pct=95), None), False, "yellow"),
    (collect.Row("a", None, "timeout"), False, "red"),
    (collect.Row("a", None, "disabled"), False, "dim"),
])
def test_the_border_shows_selection_alerts_and_down_machines(
        row, selected, want):
    lines = card(row, selected=selected)
    assert lines[0][0] == ("╭─ ", want)
    assert lines[-1][0][1] == want


def test_a_down_card_names_the_reason_within_its_width():
    lines = card(collect.Row("macmini", None, "x" * 80), width=40)
    assert [len(text(line)) for line in lines] == [40] * render.CARD_HEIGHT
    assert "down: xxx" in text(lines[1])


def test_summary_counts_machines_that_are_up_down_and_alerting():
    rows = [collect.Row("a", snap(agents={}), None),
            collect.Row("b", snap(agents={"blocked": 1}), None),
            collect.Row("c", None, "timeout"),
            collect.Row("d", None, "disabled")]
    assert render.summary(rows) == "4 machines · 2 up · 1 down · 1 alert"
    assert render.summary(rows[:1]) == "1 machine · 1 up"


@pytest.mark.parametrize("selected, delta, want", [
    (0, 1, 1), (4, 1, 4),  # stops at the last card
    (1, -1, 0), (0, -1, 0),  # and at the first
    (1, 3, 4), (4, -3, 1),  # a row down or up in three columns
    (2, 3, 4),  # a row down from the end lands on the last card
])
def test_step_moves_the_selection_and_stays_on_a_card(selected, delta, want):
    assert render.step(selected, delta, 5) == want


@pytest.mark.parametrize("state, entry, status, want", [
    ("current", {"source": {"kind": "github"}}, None,
     ("plugin current", "green")),
    ("current", {"source": {"kind": "local"}}, None,
     ("plugin linked", "dim")),
    ("older", {"source": {"kind": "github"}}, None,
     ("plugin older", "yellow")),
    ("newer", {"source": {"kind": "github"}}, None,
     ("plugin newer", "blue")),
    ("missing", {}, None, ("plugin missing", "yellow")),
    ("unknown", None, None, ("plugin unknown", "dim")),
    ("missing", {}, "deploying...", ("plugin deploying...", "yellow")),
    ("missing", {}, "deployed", ("plugin deployed", "green")),
    ("missing", {}, "failed: timeout", ("plugin failed: timeout", "red")),
    ("missing", {}, "refused: this copy has uncommitted changes",
     ("plugin refused: this copy has uncommitted changes", "red")),
])
def test_plugin_note_shows_state_or_the_latest_deploy(
        state, entry, status, want):
    assert render.plugin_note(state, entry, status) == want


def test_card_draws_the_plugin_note_under_the_agents():
    history = render.History()
    lines = render.card(collect.Row("a", snap(), None), history, 46,
                        note=("plugin missing", "yellow"))
    assert len(lines) == render.CARD_HEIGHT == 7
    assert "plugin missing" in text(lines[5])
    assert styles_of(lines[5], " plugin missing") == ["yellow"]
    assert all(len(text(line)) == 46 for line in lines)
