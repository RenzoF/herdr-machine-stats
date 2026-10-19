"""The pipeline card's data: the dispatcher's ``/status``, read-only.

One GET of the configured URL per poll, in a thread of its own so a slow
dispatcher never delays the machine polls. ``summarize`` turns the JSON
into a ``View`` the renderer draws; what each field means is in
docs/specs/2026-10-19-pipeline-card.md.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from collections import namedtuple
from datetime import datetime, timezone

TIMEOUT = 3  # seconds for the one request
MAX_BYTES = 4_000_000  # a /status is tens of kilobytes; this is a backstop
SCHEMES = ("http", "https")

# One worker line: ``stage`` is None for an idle worker.
Worker = namedtuple("Worker", "name stage ref age harness")
# ``error`` is None for a reading; then the rest is filled. ``level`` is
# "ok", "attention" or "stuck"; ``ci`` is (in use, max) or None; ``age`` of
# the last lease and the workers' ages are seconds or None.
View = namedtuple(
    "View", "error workers capacity ci waiting failed cards last_lease"
    " level verdict")


class PipelineError(Exception):
    """The dispatcher gave no usable ``/status``."""


def unreachable(reason):
    return View(reason, [], None, None, 0, 0, 0, None, "unreachable", "")


def valid_url(url):
    return isinstance(url, str) and url.split("://", 1)[0] in SCHEMES \
        and "://" in url


def fetch(url, timeout=TIMEOUT):
    """The parsed ``/status`` at ``url``; PipelineError says why not."""
    if not valid_url(url):
        raise PipelineError("url is not http or https")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise PipelineError(f"HTTP {exc.code}") from None
    except urllib.error.URLError as exc:
        raise PipelineError(str(exc.reason) or "no answer") from None
    except (OSError, ValueError) as exc:  # timeouts, resets, bad URLs
        raise PipelineError(str(exc) or type(exc).__name__) from None
    if len(body) > MAX_BYTES:
        raise PipelineError("answer too large")
    try:
        data = json.loads(body)
    except ValueError:
        raise PipelineError("answer is not JSON") from None
    if not isinstance(data, dict):
        raise PipelineError("answer is not a /status object")
    return data


def seconds_since(stamp, now):
    """Seconds from an ISO timestamp to ``now``, or None if unreadable."""
    if not isinstance(stamp, str):
        return None
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0, int((now - then).total_seconds()))


def _dicts(value):
    return [v for v in value if isinstance(v, dict)] \
        if isinstance(value, list) else []


def _count(value):
    return len(value) if isinstance(value, list) else 0


def _short(worker):
    """``rwb-worker-1`` as ``worker-1``."""
    worker = str(worker or "?")
    return worker[4:] if worker.startswith("rwb-") else worker


def _workers(status, now):
    jobs = {j.get("id"): j for j in _dicts(status.get("jobs"))}
    busy = []
    for lease in _dicts(status.get("leases")):
        job = jobs.get(lease.get("job"), {})
        slug = str(job.get("slug") or "")
        ref = f"{slug.rsplit('/', 1)[-1]}#{job.get('issue')}" \
            if job.get("issue") is not None else "?"
        account = str(lease.get("account") or "")
        busy.append(Worker(
            _short(lease.get("worker")), str(job.get("stage") or "?"), ref,
            seconds_since(lease.get("created_at"), now),
            account.split(":", 1)[0]))
    busy.sort(key=lambda w: w.name)
    stall = status.get("stall")
    idle = [Worker(_short(w.get("worker")), None, "",
                   seconds_since(w.get("since"), now), "")
            for w in _dicts(stall.get("idle_workers"))] \
        if isinstance(stall, dict) else []
    idle.sort(key=lambda w: w.name)
    capacity = status.get("capacity")
    capacity = capacity if isinstance(capacity, int) else None
    missing = (capacity or 0) - len(busy) - len(idle)
    return busy + idle + [Worker("-", None, "", None, "")] * max(0, missing)


def _waiting(stall):
    repos = stall.get("repos") if isinstance(stall, dict) else None
    if not isinstance(repos, dict):
        return 0
    return sum(_count(r.get("planned")) + _count(r.get("scored"))
               for r in repos.values() if isinstance(r, dict))


def _ci(status):
    governor = status.get("governor")
    if not isinstance(governor, dict):
        return None
    in_use, cap = governor.get("ci_in_use"), governor.get("ci_max_parallel")
    if isinstance(in_use, int) and isinstance(cap, int):
        return in_use, cap
    return None


def _plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def _problems(status, repos, cards, failed):
    """(level, text) for each thing that needs a person, worst first."""
    stuck, attention = [], []
    stall = status.get("stall")
    stall = stall if isinstance(stall, dict) else {}
    if stall.get("condition") or stall.get("active"):
        idle = [w for w in _dicts(stall.get("idle_workers")) if w.get("long")]
        stuck.append("✗ stalled" + (
            f": {_plural(len(idle), 'worker', 'workers')} idle with work "
            "waiting" if stall.get("condition") and idle else ""))
    for slug, repo in repos:
        if repo.get("gave_up"):
            stuck.append(f"✗ {slug} gave up")
    if status.get("ok") is False:
        stuck.append("✗ dispatcher not ok")
    draining = status.get("draining")
    if draining:
        reason = draining.get("reason") if isinstance(draining, dict) else ""
        attention.append("! draining" + (f": {reason}" if reason else ""))
    for slug, repo in repos:
        if repo.get("held"):
            reason = repo.get("hold_reason")
            attention.append(f"! {slug} held" + (f": {reason}" if reason
                                                 else ""))
        if repo.get("crashed"):
            attention.append(f"! {slug} crashed")
    if cards:
        attention.append(
            f"! {_plural(cards, 'card waits', 'cards wait')} on you")
    if _count(status.get("usage_attention")):
        attention.append("! account needs attention")
    if failed:
        attention.append(f"! {_plural(failed, 'job', 'jobs')} failed")
    return stuck, attention


def summarize(status, now=None):
    """A View of a parsed ``/status``."""
    now = now or datetime.now(timezone.utc)
    repos = [(str(r.get("alias") or slug).rsplit("/", 1)[-1], r)
             for slug, r in sorted((status.get("repos") or {}).items())
             if isinstance(r, dict)] \
        if isinstance(status.get("repos"), dict) else []
    # The top-level "cards" is the first repository's; count them all.
    cards = sum(_count(r.get("cards")) for _alias, r in repos)
    failed = sum(j.get("state") == "failed"
                 for j in _dicts(status.get("jobs")))
    workers = _workers(status, now)
    stall = status.get("stall")
    stuck, attention = _problems(status, repos, cards, failed)
    level = "stuck" if stuck else "attention" if attention else "ok"
    found = stuck + attention
    if found:
        verdict = found[0] + (f" (+{len(found) - 1})"
                              if len(found) > 1 else "")
    elif any(w.stage for w in workers):
        verdict = "✓ moving"
    else:
        verdict = "✓ idle"
    capacity = status.get("capacity")
    return View(
        None, workers, capacity if isinstance(capacity, int) else None,
        _ci(status), _waiting(stall), failed, cards,
        seconds_since(stall.get("last_lease_at"), now)
        if isinstance(stall, dict) else None, level, verdict)


def read(url):
    """A View of the dispatcher at ``url``, or an unreachable one."""
    try:
        return summarize(fetch(url))
    except PipelineError as exc:
        return unreachable(str(exc))


class Watcher:
    """Reads the dispatcher every ``interval`` seconds, in the background."""

    def __init__(self, url, interval, reader=read):
        self.url, self.interval, self.reader = url, interval, reader
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.latest = None
        self.polled = None  # time.monotonic() when the latest read began
        threading.Thread(target=self.loop, daemon=True).start()

    def loop(self):
        while True:
            began = time.monotonic()
            view = self.reader(self.url)
            with self.lock:
                self.latest, self.polled = view, began
            self.wake.wait(self.interval)
            self.wake.clear()

    def view(self):
        with self.lock:
            return self.latest

    def refresh(self):
        self.wake.set()
