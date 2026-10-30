"""When each needs-you item was first seen, kept on this machine.

Herdr gives no time for a status change, so an agent's wait counts from
the first poll that saw it in that status with that state_change_seq.
The dashboard and the popup share these files, so both show the same
ages and a restart does not reset them. They hold ids, statuses,
sequence numbers, names, places and times: never screen text or a
request's purpose. Nothing here is ever written to another machine.
"""

import contextlib
import fcntl
import json
import os
import tempfile
from pathlib import Path

from statslib.needs import Item, Where
from statslib.prompts import finite

# Intervals without an update after which new items are lower bounds:
# nothing was watching.
GAP = 3
KEEP = 3600  # seconds a machine that does not answer keeps its entries
LISTED = ("group", "rank", "machine", "target", "pane_id", "seq",
          "agent", "project", "where", "deadline", "first_seen",
          "approx", "key")


def state_dir(env):
    """Where the files live: Herdr's plugin state directory, else the
    XDG state directory."""
    if env.get("HERDR_PLUGIN_STATE_DIR"):
        return Path(env["HERDR_PLUGIN_STATE_DIR"])
    base = env.get("XDG_STATE_HOME") or os.path.join(
        env.get("HOME") or os.path.expanduser("~"), ".local", "state")
    return Path(base) / "herdr-machine-stats"


def _read(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(path, data):
    """Replace ``path`` atomically with a file only this user reads."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


class Store:
    """First-seen times (``needs.json``) and the last list drawn
    (``needs-list.json``), under one lock."""

    def __init__(self, directory):
        self.dir = Path(directory)
        self.ages = self.dir / "needs.json"
        self.listing = self.dir / "needs-list.json"
        self.lock = self.dir / "needs.lock"

    @contextlib.contextmanager
    def _locked(self):
        self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(self.lock, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield  # closing the file releases the lock

    def stamp(self, items, answered, poll_time, interval):
        """``items`` with first-seen times. A secret keeps its own."""
        with self._locked():
            old = _read(self.ages) or {}
            entries = old.get("items")
            entries = entries if isinstance(entries, dict) else {}
            updated = old.get("updated")
            gap = (not finite(updated)
                   or poll_time - updated > GAP * interval)
            fresh, out = {}, []
            for item in items:
                if item.group == "secret":
                    out.append(item)
                    continue
                name = f"{item.machine}\t{item.pane_id}"
                was = entries.get(name)
                if (isinstance(was, dict) and was.get("status") == item.group
                        and was.get("seq") == item.seq
                        and finite(was.get("first_seen"))):
                    first, approx = was["first_seen"], bool(was.get("approx"))
                else:
                    first, approx = poll_time, gap
                fresh[name] = {"machine": item.machine, "status": item.group,
                               "seq": item.seq, "first_seen": first,
                               "approx": approx, "last_seen": poll_time}
                out.append(item._replace(first_seen=first, approx=approx))
            for name, was in entries.items():
                if (name not in fresh and isinstance(was, dict)
                        and was.get("machine") not in answered
                        and finite(was.get("last_seen"))
                        and poll_time - was["last_seen"] < KEEP):
                    fresh[name] = was
            _write(self.ages, {"updated": poll_time, "items": fresh})
        return out

    def save_list(self, items, as_of):
        """Keep the list (without details) for the popup to show at once."""
        rows = [{field: getattr(item, field) for field in LISTED}
                for item in items]
        with self._locked():
            _write(self.listing, {"as_of": as_of, "items": rows})

    def load_list(self):
        """(items, as_of) of the last list kept; ([], None) without one."""
        data = _read(self.listing)
        try:
            items = [Item(**{**{f: row[f] for f in LISTED}, "detail": (),
                             "where": Where(*row["where"]) if row["where"]
                             else None,
                             "key": tuple(row["key"])})
                     for row in data["items"]]
            return items, float(data["as_of"])
        except (TypeError, KeyError, ValueError):
            return [], None
