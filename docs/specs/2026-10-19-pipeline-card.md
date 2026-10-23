# Pipeline card

One extra, read-only card on the dashboard showing whether the
job-dispatcher pipeline is working through issues. Nothing is added to
`herdr machine list`, nothing is run on the workers, and no key acts on
the pipeline.

## Source

`GET <pipeline_url>` (the dispatcher's `/status`, JSON, no auth), polled
by a background thread of its own, so a slow dispatcher never delays the
machine polls and the other way round. Standard library (`urllib`) only,
3 second timeout, one request per poll interval.

Only `http://` and `https://` URLs are accepted; anything else is a
config note and no card. The request ignores `http_proxy` / `https_proxy`
(a `ProxyHandler({})` opener): the dispatcher is on the local network, and
a desktop proxy would make it look unreachable.

## Configuration

`config.toml` in the plugin's config directory:

```toml
pipeline_url = "http://dispatcher.example:8787/status"   # default "": no card
```

`--pipeline URL` overrides it for one run. Empty (the default), a missing
file or a bad value means no card, so users of the public plugin see no
change. A bad value adds a footer note, like `deploy`.

## Layout

A card of the usual shape and height (`CARD_HEIGHT`), placed after the
machine cards. It is not selectable: arrows, Enter and `d` act on
machines only.

```
╭─ pipeline ───────────────────────── 2 workers ─╮
│ worker-1 implement shop#630     12m claude     │
│ worker-2 review    billing#194   4m codex      │
│                                                │
│ CI 2/2  waiting 13  failed 1  cards 0          │
│ ! 1 job failed  last lease 4m ago              │
╰────────────────────────────────────────────────╯
```

Body, five lines:

1. to 3. One line per worker, busy first. At most three lines; with more
   workers the last line reads `+N more`.
4. Counters: `CI in_use/max`, `waiting N`, `failed N`, `cards N`.
5. The verdict: `last lease <age> ago` and one of the states below, or the
   first thing that needs attention.

## Data mapping

| Shown | From `/status` |
|---|---|
| busy worker | `leases[]`: `worker`, `account`, `created_at` (age); its job is `jobs[]` with `id == lease.job`: `stage`, `issue`, `slug` |
| idle worker | `stall.idle_workers[]` (`worker`, `since`): every free worker, from `stall.py` `measure` |
| worker count | `capacity` (an integer, else `unknown`) |
| harness | `account` up to the first `:` (`claude:proxy` shows `claude`) |
| CI | `governor.ci_in_use`, `governor.ci_max_parallel` |
| waiting | sum over `stall.repos[*]` of `len(planned) + len(scored)`: the dispatcher's own "N issues wait". Repos that are drained, held or without eligible work are not in it |
| failed | `jobs[]` with `state == "failed"` that failed in the last 24 hours (below) |
| cards | sum over `repos[*].cards`. The top-level `cards` is the first repository's only |
| last lease | `stall.last_lease_at` |
| usage attention | `usage_attention[]` |
| held | `repos[*].held`, `hold_reason` |
| draining | `draining` (`false`, or `{since, reason}`) |
| stalled | `stall.condition` (workers idle past `stall_after_min` while work waits, beyond the review reserve), `stall.active` (the episode), `stall.clearing_since` (the condition has gone and the dispatcher is waiting for the clear to hold) |
| not ok | `ok` is false (no vault token sink, no lock or no worker registry) |
| lane trouble | `repos[*].gave_up`, `repos[*].crashed` |

**When a job failed.** A job entry in `/status` has `id`, `issue`,
`stage`, `state`, `worker`, `slug` and `name`: no timestamp. The
dispatcher's job row has `updated_at`; if an entry carries that field, the
card uses it (the job counts while `now - updated_at` is under 24 hours).
Without it, the card uses the time this dashboard first saw that job id
failed, kept in memory (not on disk) until the job leaves the failed list.
So a stale failure that was already there when the dashboard started
counts for 24 hours after the start, then drops off; no recent failure is
ever hidden. Exposing `updated_at` on job entries in `/status` would make
this exact.

A job in a `ci` stage has no worker (it runs on the CI host); it is
counted in the CI figure, not shown as a worker line.

## States

The border and the verdict take the worst of:

- **stuck** (red): `stall.condition`, or `stall.active` without
  `clearing_since`; any `gave_up`; `ok` false. Verdict `✗ stalled`,
  `✗ lane gave up` or `✗ not ok`.
- **attention** (yellow): a stall clearing (`stall.active` and
  `clearing_since`, `condition` false: work moves again, the episode
  is not yet closed); draining; a held repository; `cards > 0`;
  `usage_attention`; `failed > 0`; a crashed lane. Verdict names the
  first, for example `! stall clearing`, `! 2 cards wait on you`,
  `! draining: deploy`.
- **ok** (the plain border): `✓ moving` when a worker is busy, `✓ idle`
  when none is and nothing waits.
- **unreachable** (dim border): the request failed or timed out, or the
  body was not the expected JSON. First line `unreachable: <reason>`;
  the rest blank. Not red: the dashboard also runs on machines that
  cannot reach the dispatcher.

Counters carry their own colour (failed and cards yellow when above 0,
CI yellow when full and work waits); the verdict line carries the state's
colour.

## Not in scope

Anything that acts on the pipeline (drain, tick), the workers as
machines, and the machine-stats issues #1 and #2.

## Tests

Fake `/status` payloads for ok, idle, stalled, failed, draining, held,
cards on a second repository, usage attention, and unreachable (refused,
timeout, bad JSON, bad URL scheme); card width exactness at several
widths; config parsing; the poller against a local HTTP server.
