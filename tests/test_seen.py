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
