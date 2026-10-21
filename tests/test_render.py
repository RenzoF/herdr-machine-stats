"""statslib.render: bars, colour bands, sparklines and machine cards."""

import pytest

from statslib import collect, pipeline, render


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


# -- the pipeline card ---------------------------------------------------

def busy(name, stage, ref, age, harness):
    return pipeline.Worker(name, stage, ref, age, harness)


def view(**changes):
    base = dict(
        error=None, capacity=2,
        workers=[busy("worker-1", "implement", "shop#630", 720,
                      "claude"),
                 busy("worker-2", "review", "billing#194", 240,
                      "codex")],
        ci=(2, 2), waiting=13, failed=1, cards=0, last_lease=240,
        level="attention", verdict="! 1 job failed")
    base.update(changes)
    return pipeline.View(**base)


def test_the_pipeline_card_shows_each_worker_the_counters_and_the_verdict():
    lines = render.pipeline_card(view(), 50)
    assert [text(line) for line in lines] == [
        "╭─ pipeline ───────────────────────── 2 workers ─╮",
        "│ worker-1 implement shop#630     12m claude     │",
        "│ worker-2 review    billing#194   4m codex      │",
        "│                                                │",
        "│ CI 2/2  waiting 13  failed 1  cards 0          │",
        "│ ! last lease 4m ago  1 job failed              │",
        "╰────────────────────────────────────────────────╯",
    ]


@pytest.mark.parametrize("width", [30, 40, 41, 50, 77, 120])
@pytest.mark.parametrize("changes", [
    {}, {"error": "timed out", "level": "unreachable"},
    {"workers": [], "capacity": 0, "ci": None, "last_lease": None},
    {"workers": [busy(f"worker-{n}", "implement", "A-very-long-repo#1", 5,
                      "claude") for n in range(6)], "capacity": 6},
])
def test_every_pipeline_card_line_is_exactly_as_wide_as_the_card(
        width, changes):
    lines = render.pipeline_card(view(**changes), width)
    assert len(lines) == render.CARD_HEIGHT
    assert {len(text(line)) for line in lines} == {width}


def test_an_idle_worker_says_idle_and_for_how_long():
    idle = busy("worker-2", None, "", 300, "")
    lines = render.pipeline_card(view(workers=[
        view().workers[0], idle]), 50)
    assert text(lines[2]).startswith("│ worker-2 idle 5m")


def test_more_workers_than_lines_end_in_a_count():
    workers = [busy(f"worker-{n}", "review", "x#1", 60, "codex")
               for n in range(5)]
    lines = render.pipeline_card(view(workers=workers, capacity=5), 50)
    shown = [text(line)[2:10] for line in lines[1:4]]
    assert shown == ["worker-0", "worker-1", "+3 more "]


def test_the_border_follows_the_state():
    edges = {level: render.pipeline_card(view(level=level), 50)[0][0][1]
             for level in ("ok", "attention", "stuck")}
    assert edges == {"ok": "border", "attention": "yellow", "stuck": "red"}


def test_an_unreachable_dispatcher_is_dim_and_says_why():
    lines = render.pipeline_card(pipeline.unreachable("timed out"), 50)
    assert lines[0][0][1] == "dim"
    assert text(lines[1]) == "│ unreachable: timed out" + " " * 25 + "│"
    assert styles_of(lines[1], " unreachable") == ["yellow"]
    assert all(text(line).strip("│ ") == "" for line in lines[2:-1])


def test_before_the_first_read_the_card_says_polling():
    lines = render.pipeline_card(None, 50)
    assert text(lines[1]).startswith("│ polling...")


def test_the_verdict_and_counters_take_their_colour():
    stuck = render.pipeline_card(view(level="stuck", verdict="✗ stalled",
                                      cards=2), 50)
    assert styles_of(stuck[5], " ✗") == ["red"]
    assert styles_of(stuck[5], "  stalled") == ["red"]
    assert styles_of(stuck[5], " last lease 4m ago") == ["dim"]
    assert styles_of(stuck[4], "cards 2") == ["yellow"]
    assert styles_of(stuck[4], "CI 2/2") == ["yellow"]  # full, work waits
    ok = render.pipeline_card(view(level="ok", verdict="✓ moving", failed=0,
                                   waiting=0), 50)
    assert styles_of(ok[5], " ✓ moving") == ["green"]
    assert text(ok[5]) == "│ ✓ moving  last lease 4m ago" + " " * 20 + "│"
    assert styles_of(ok[4], "failed 0") == ["label"]
    assert styles_of(ok[4], "CI 2/2") == ["label"]


def test_a_single_worker_is_not_pluralised():
    lines = render.pipeline_card(view(capacity=1), 50)
    assert " 1 worker ─" in text(lines[0])


@pytest.mark.parametrize("seconds, want", [
    (None, "?"), (0, "0s"), (59, "59s"), (60, "1m"), (3599, "59m"),
    (3600, "1h00m"), (11100, "3h05m"), (86400, "1d"), (200000, "2d")])
def test_age_text_is_short(seconds, want):
    assert render.age_text(seconds) == want


@pytest.mark.parametrize("width", [30, 40, 50, 56, 80])
def test_a_long_repo_name_gives_way_so_age_and_harness_still_fit(width):
    workers = [
        busy("worker-1", "implement", "customer-context-service#117", 62,
             "claude"),
        busy("worker-2", "plan", "command-center#138", 79, "claude")]
    lines = render.pipeline_card(view(workers=workers), width)
    first, second = text(lines[1]), text(lines[2])
    assert len(first) == len(second) == width
    if width >= 40:
        assert "#117" in first and "1m" in first
        assert "#138" in second and "1m" in second
    if width >= 56:
        assert "claude" in first and "claude" in second
    if width == 40:
        assert "claude" not in first  # no room: the harness gives way


@pytest.mark.parametrize("ref, room, want", [
    ("shop#630", 20, "shop#630"),
    ("customer-context-service#117", 18, "customer-cont…#117"),
    ("customer-context-service#117", 8, "c…#117"[:8]),
    ("x#1", 2, "x#"), ("noissue", 4, "nois")])
def test_cut_ref_keeps_the_issue_number(ref, room, want):
    got = render._cut_ref(ref, room)
    assert len(got) <= room
    if "…" in want:
        assert got.endswith("#" + ref.rpartition("#")[2])


@pytest.mark.parametrize("text_, room, want", [
    ("9 cards wait on you (+1)", 40, "9 cards wait on you (+1)"),
    ("9 cards wait on you (+1)", 24, "9 cards wait on you (+1)"),
    ("9 cards wait on you (+1)", 23, "9 cards wait on you…"),
    ("9 cards wait on you (+1)", 13, "9 cards wait…"),
    ("9 cards wait on you (+1)", 12, "9 cards…"),   # not "9 cards wa…"
    ("9 cards wait on you (+1)", 8, "9 cards…"),
    ("9 cards wait on you (+1)", 7, "9…"),
    ("alphabetical", 5, "…"),                          # no word fits
    ("anything", 0, ""),
])
def test_ellipsize_cuts_between_words_and_ends_with_one_ellipsis(
        text_, room, want):
    got = render.ellipsize(text_, room)
    assert got == want and len(got) <= room
    assert got.count("…") <= 1


LONG = ("! draining: deploy of the dispatcher, then a long maintenance "
        "window for the whole fleet (+3)")


@pytest.mark.parametrize("width", [40, 44, 50, 60, 80])
def test_the_verdict_line_keeps_the_lease_whole_and_cuts_between_words(
        width):
    lines = render.pipeline_card(
        view(level="attention", verdict=LONG, last_lease=4 * 60), width)
    line = text(lines[5])
    assert len(line) == width
    assert "! last lease 4m ago" in line  # never cut, at any width
    shown = line[1:-1].strip()
    detail = shown.split("  ", 1)[1] if "  " in shown else ""
    assert detail.startswith("draining")
    if detail.endswith("…"):
        before = detail[:-1]
        assert LONG[2:].startswith(before)          # a prefix of the text
        assert LONG[2 + len(before)] in " ,:"       # ended on a word edge
        assert detail.count("…") == 1


def test_at_width_40_the_attention_text_gives_way_to_the_lease():
    lines = render.pipeline_card(
        view(level="attention", verdict="! 9 cards wait on you (+1)",
             last_lease=55), 40)
    assert text(lines[5]) == "│ ! last lease 55s ago  9 cards wait…  │"


def test_a_stuck_card_leads_with_the_mark_and_the_lease():
    lines = render.pipeline_card(
        view(level="stuck",
             verdict="✗ stalled: 2 workers idle with work waiting",
             last_lease=9 * 60), 40)
    assert text(lines[5]) == "│ ✗ last lease 9m ago  stalled: 2…     │"


def test_without_a_lease_the_line_says_so():
    lines = render.pipeline_card(
        view(level="attention", verdict="! 1 job failed",
             last_lease=None), 50)
    assert "! no lease yet  1 job failed" in text(lines[5])
