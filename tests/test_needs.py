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
                      ("laptop", pane), True)


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


def test_a_blocked_pane_that_is_not_a_coding_agent_is_never_read():
    # A prompt pane reports itself as a blocked agent of its own kind;
    # its screen can show what is being asked for (D7).
    rows = [row("b", raw([
        agent("w1:p1", "blocked", agent="claude"),
        agent("w1:p2", "blocked", agent="secret-prompt",
              state_labels={"blocked": "secret wanted"}),
        agent("w1:p3", "blocked", agent=None)]))]
    items, _ = needs.build(rows, [None], 2000)
    assert [(i.pane_id, i.screen) for i in items] == [
        ("w1:p1", True), ("w1:p2", False), ("w1:p3", False)]
    reads = Reads({p: ["TARGET-PATH and KEY-NAME"]
                   for p in ("w1:p1", "w1:p2", "w1:p3")})
    filled = needs.Screens(reads).fill(items)
    assert reads.calls == [(None, ["w1:p1"])]
    assert filled[1].detail == ("secret wanted",)
    assert "TARGET-PATH" not in repr(filled[1:])


def test_a_prompt_pane_of_any_request_is_dropped_open_or_not():
    # An answered or cancelled request is not open, but its prompt pane
    # may still be listed by Herdr as a blocked agent.
    data = raw([agent("w1:p9", "blocked", agent="secret-prompt")])
    data = data._replace(prompt_panes=frozenset({"w1:p9"}))
    items, _ = needs.build([row("laptop", data)], [None], 2000)
    assert items == []
