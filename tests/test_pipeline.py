"""statslib.pipeline: the dispatcher's /status as a View."""

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from statslib import pipeline

NOW = datetime(2026, 10, 19, 14, 0, 0, tzinfo=timezone.utc)


def lease(worker, job, created="2026-10-19T13:48:00Z", account="claude:p"):
    return {"id": 1, "worker": worker, "job": job, "state": "leased",
            "account": account, "created_at": created}


def job(ident, issue, stage, slug="Acme/shop", state="leased",
        worker=""):
    return {"id": ident, "issue": issue, "stage": stage, "state": state,
            "worker": worker, "slug": slug, "name": None}


def status(**changes):
    """A /status shaped like the live one: two workers, both busy."""
    base = {
        "ok": True, "held": False, "capacity": 2, "draining": False,
        "running": 3,
        "leases": [
            lease("acme-worker-1", "J1"),
            lease("acme-worker-2", "J2", "2026-10-19T13:56:00Z",
                  "codex:proxy")],
        "jobs": [
            job("J1", 630, "implement", worker="acme-worker-1"),
            job("J2", 194, "review", "Acme/billing",
                worker="acme-worker-2"),
            job("J3", 504, "ci")],
        "cards": [], "usage_attention": [],
        "repos": {
            "Acme/shop": {"alias": "shop", "held": False,
                          "hold_reason": "", "cards": [],
                          "crashed": "", "gave_up": False},
            "Acme/billing": {"alias": "billing", "held": False,
                             "hold_reason": "", "cards": [],
                             "crashed": "", "gave_up": False}},
        "governor": {"ci_max_parallel": 2, "ci_in_use": 1},
        "stall": {
            "condition": False, "active": False, "idle_workers": [],
            "last_lease_at": "2026-10-19T13:56:00Z",
            "repos": {"Acme/shop": {
                "planned": list(range(13)), "scored": [641, 642]}}},
    }
    base.update(changes)
    return base


def test_busy_workers_name_their_stage_issue_age_and_harness():
    view = pipeline.summarize(status(), NOW)
    assert view.error is None and view.capacity == 2
    assert view.workers == [
        pipeline.Worker("worker-1", "implement", "shop#630", 720,
                        "claude"),
        pipeline.Worker("worker-2", "review", "billing#194", 240,
                        "codex")]


def test_the_counters_come_from_the_governor_stall_jobs_and_every_repo():
    s = status()
    s["jobs"].append(job("J4", 201, "verify", state="failed"))
    s["repos"]["Acme/billing"]["cards"] = [{"id": 1}, {"id": 2}]
    view = pipeline.summarize(s, NOW)
    assert view.ci == (1, 2)
    assert view.waiting == 15  # 13 planned and 2 scored
    assert view.failed == 1
    assert view.cards == 2  # the top-level "cards" is []: not the source
    assert view.last_lease == 240


def test_a_moving_pipeline_is_ok():
    view = pipeline.summarize(status(), NOW)
    assert (view.level, view.verdict) == ("ok", "✓ moving")


def test_idle_workers_come_from_the_stall_report():
    s = status(leases=[lease("acme-worker-1", "J1")])
    s["stall"]["idle_workers"] = [{"worker": "acme-worker-2",
                                   "since": "2026-10-19T13:55:00Z",
                                   "long": False}]
    view = pipeline.summarize(s, NOW)
    assert view.workers[1] == pipeline.Worker("worker-2", None, "", 300, "")


def test_a_worker_nobody_names_is_still_counted_from_capacity():
    view = pipeline.summarize(status(leases=[], jobs=[]), NOW)
    assert [w.name for w in view.workers] == ["-", "-"]


def test_nothing_running_and_nothing_waiting_is_idle_and_ok():
    s = status(leases=[], jobs=[])
    s["stall"]["repos"] = {}
    view = pipeline.summarize(s, NOW)
    assert (view.level, view.verdict) == ("ok", "✓ idle")


def test_a_stalled_pipeline_is_stuck_and_says_how_many_workers_idle():
    s = status(leases=[], jobs=[])
    s["stall"].update(condition=True, active=True, idle_workers=[
        {"worker": "acme-worker-1", "since": "2026-10-19T13:00:00Z",
         "long": True},
        {"worker": "acme-worker-2", "since": "2026-10-19T13:00:00Z",
         "long": True}])
    view = pipeline.summarize(s, NOW)
    assert view.level == "stuck"
    assert view.verdict == "✗ stalled: 2 workers idle with work waiting"


def test_an_open_stall_episode_is_stuck_even_when_clearing():
    s = status()
    s["stall"]["active"] = True
    view = pipeline.summarize(s, NOW)
    assert (view.level, view.verdict) == ("stuck", "✗ stalled")


def test_a_failed_job_needs_attention():
    s = status()
    s["jobs"].append(job("J4", 201, "verify", state="failed"))
    view = pipeline.summarize(s, NOW)
    assert (view.level, view.verdict) == ("attention", "! 1 job failed")


def test_draining_names_the_reason():
    view = pipeline.summarize(status(draining={
        "since": "2026-10-19T13:00:00Z", "reason": "deploy"}), NOW)
    assert (view.level, view.verdict) == ("attention", "! draining: deploy")


def test_a_held_repository_names_itself_and_the_reason():
    s = status()
    s["repos"]["Acme/billing"].update(held=True, hold_reason="tamper")
    view = pipeline.summarize(s, NOW)
    assert view.verdict == "! billing held: tamper"


def test_cards_waiting_on_a_person_need_attention():
    s = status()
    s["repos"]["Acme/shop"]["cards"] = [{"id": 1}]
    assert pipeline.summarize(s, NOW).verdict == "! 1 card waits on you"
    s["repos"]["Acme/shop"]["cards"] = [{"id": 1}, {"id": 2}]
    assert pipeline.summarize(s, NOW).verdict == "! 2 cards wait on you"


def test_usage_attention_needs_attention():
    s = status(usage_attention=[["acme-worker-1", "a@b", "expired"]])
    assert pipeline.summarize(s, NOW).verdict == "! account needs attention"


def test_a_lane_that_gave_up_or_a_dispatcher_not_ok_is_stuck():
    s = status()
    s["repos"]["Acme/billing"]["gave_up"] = True
    assert pipeline.summarize(s, NOW).verdict == "✗ billing gave up"
    assert pipeline.summarize(status(ok=False), NOW).level == "stuck"


def test_stuck_comes_before_attention_and_the_rest_are_counted():
    s = status(draining={"reason": "deploy"})
    s["stall"]["condition"] = True
    s["jobs"].append(job("J4", 201, "verify", state="failed"))
    view = pipeline.summarize(s, NOW)
    assert view.level == "stuck"
    assert view.verdict == "✗ stalled (+2)"


def test_a_lease_without_its_job_row_still_shows_the_worker():
    view = pipeline.summarize(status(jobs=[]), NOW)
    assert view.workers[0][1:3] == ("?", "?")


def test_missing_and_odd_fields_never_raise():
    for odd in ({}, {"repos": [], "jobs": "x", "leases": None,
                     "stall": [], "capacity": "unknown", "governor": 3},
                {"stall": {"repos": {"a": 1}, "idle_workers": [1]}}):
        view = pipeline.summarize(odd, NOW)
        assert view.error is None and view.level == "ok"


@pytest.mark.parametrize("stamp, want", [
    ("2026-10-19T13:59:00Z", 60), ("2026-10-19T13:59:00+00:00", 60),
    ("2026-10-19T14:05:00Z", 0), ("junk", None), (None, None)])
def test_seconds_since_reads_iso_stamps(stamp, want):
    assert pipeline.seconds_since(stamp, NOW) == want


@pytest.mark.parametrize("url, ok", [
    ("http://dispatcher.example:8787/status", True),
    ("https://x/status", True),
    ("file:///etc/passwd", False), ("ftp://x/", False), ("x", False),
    ("", False), (None, False), ("http:/x", False)])
def test_only_http_urls_are_accepted(url, ok):
    assert pipeline.valid_url(url) is ok


class Dispatcher:
    """A local server standing in for the dispatcher."""

    def __init__(self, code=200, body=b"{}", delay=0):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.paths.append(self.path)
                time.sleep(delay)
                self.send_response(code)
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            def log_message(self, *args):
                pass

        self.paths = []
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/status"
        threading.Thread(target=self.server.serve_forever,
                         daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def serve():
    servers = []

    def make(**kw):
        servers.append(Dispatcher(**kw))
        return servers[-1]
    yield make
    for server in servers:
        server.close()


def test_read_fetches_status_and_summarizes_it(serve):
    server = serve(body=json.dumps(status()).encode())
    view = pipeline.read(server.url)
    assert view.error is None and view.capacity == 2
    assert server.paths == ["/status"]


def test_a_refused_connection_is_unreachable():
    view = pipeline.read("http://127.0.0.1:1/status")
    assert view.error and view.level == "unreachable"


def test_a_server_error_names_the_code(serve):
    assert pipeline.read(serve(code=503).url).error == "HTTP 503"


@pytest.mark.parametrize("body, why", [
    (b"<html>", "not JSON"), (b"[1, 2]", "not a /status object")])
def test_an_answer_that_is_not_a_status_is_unreachable(serve, body, why):
    assert why in pipeline.read(serve(body=body).url).error


def test_a_slow_dispatcher_times_out(serve):
    server = serve(body=b"{}", delay=1)
    with pytest.raises(pipeline.PipelineError):
        pipeline.fetch(server.url, timeout=0.2)


def test_a_url_that_is_not_http_is_never_opened():
    view = pipeline.read("file:///etc/passwd")
    assert view.error == "url is not http or https"


def test_the_watcher_keeps_the_latest_view_and_refreshes_on_request():
    seen = []

    def reader(url, failures):
        seen.append(url)
        return pipeline.unreachable(f"read {len(seen)}")
    watcher = pipeline.Watcher("http://x/status", 60, reader)
    deadline = time.monotonic() + 5
    while watcher.view() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert watcher.view().error == "read 1" and watcher.polled is not None
    watcher.refresh()
    while len(seen) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen == ["http://x/status"] * 2


def failed_job(ident="J9", **extra):
    return {**job(ident, 201, "verify", state="failed"), **extra}


def with_failed(*jobs):
    s = status()
    s["jobs"].extend(jobs)
    return s


@pytest.mark.parametrize("stamp, counted", [
    ("2026-10-19T13:00:00Z", True),   # an hour ago
    ("2026-10-18T14:00:01Z", True),   # a second inside the window
    ("2026-10-18T14:00:00Z", False),  # exactly 24 h ago: out
    ("2026-10-01T09:00:00Z", False),  # a stale failure
])
def test_a_failed_job_counts_only_for_24_hours_by_its_updated_at(
        stamp, counted):
    s = with_failed(failed_job(updated_at=stamp))
    view = pipeline.summarize(s, NOW)
    assert view.failed == int(counted)
    assert view.level == ("attention" if counted else "ok")


def test_a_job_without_a_timestamp_counts_from_when_it_was_first_seen():
    s = with_failed(failed_job())  # /status today: no timestamp at all
    seen = {}
    assert pipeline.summarize(s, NOW, seen).failed == 1
    assert seen == {"J9": NOW}
    day = timedelta(hours=24)
    assert pipeline.summarize(s, NOW + day - timedelta(seconds=1),
                              seen).failed == 1
    assert pipeline.summarize(s, NOW + day, seen).failed == 0
    assert seen == {"J9": NOW}  # still the first sighting


def test_a_job_that_leaves_the_failed_list_is_forgotten():
    seen = {}
    pipeline.summarize(with_failed(failed_job()), NOW, seen)
    pipeline.summarize(status(), NOW, seen)
    assert seen == {}


def test_without_a_record_a_job_with_no_timestamp_counts_as_just_seen():
    assert pipeline.summarize(with_failed(failed_job()), NOW).failed == 1


def test_the_timestamp_wins_over_the_first_sighting():
    seen = {"J9": NOW}
    s = with_failed(failed_job(updated_at="2026-10-01T09:00:00Z"))
    assert pipeline.summarize(s, NOW, seen).failed == 0


def test_the_watcher_keeps_one_record_for_every_read():
    records = []
    watcher = pipeline.Watcher(
        "http://x/status", 60,
        lambda url, seen: records.append(seen) or pipeline.unreachable(""))
    deadline = time.monotonic() + 5
    while not records and time.monotonic() < deadline:
        time.sleep(0.01)
    assert records[0] is watcher.seen


def test_the_dispatcher_is_read_without_going_through_a_proxy(
        serve, monkeypatch):
    server = serve(body=json.dumps(status()).encode())
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")  # nothing listens
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    view = pipeline.read(server.url)
    assert view.error is None and server.paths == ["/status"]


def test_a_worker_holding_a_lease_is_not_also_listed_idle():
    s = status()  # worker-1 and worker-2 both hold leases
    s["stall"]["idle_workers"] = [{"worker": "acme-worker-1",
                                   "since": "2026-10-19T13:59:45Z",
                                   "long": False}]  # a stale report
    view = pipeline.summarize(s, NOW)
    assert [w.name for w in view.workers] == ["worker-1", "worker-2"]
    assert all(w.stage for w in view.workers)
