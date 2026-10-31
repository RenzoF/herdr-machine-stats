"""Secret requests: which ones are open, from their metadata only.

A secret-prompt plugin keeps one directory per request. The scan prints
three small metadata files of each and tests whether two more exist; it
never reads anything else, and ``parse`` keeps only the fields of
``Request``: the secret's path and key name are dropped here. The rules
are the ones the requesting side applies (spec, "Secret requests").
"""

import json
import math
import re
import shlex
from collections import namedtuple

ID = re.compile(r"r-[0-9a-f]{8}")
STALE = 90          # a state.json older than this is ignored
WRITE_STALE = 210   # ... except while writing, which has no heartbeat
REQUEST_BYTES = 4096
OTHER_BYTES = 1024
REQUEST, FILE, FLAGS = "--request--", "--file--", "--flags--"

# Times are the host's epoch seconds. ``deadline`` is when the request
# stops being open (None while its value is being written, which has no
# limit); ``prompt_pane`` is the prompt's pane, None until it opened.
Request = namedtuple(
    "Request", "id created deadline pane_id workspace_id purpose"
    " prompt_pane")


def finite(value):
    """True for an int or float that is finite; a bool is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def scan_shell(name):
    """POSIX sh that prints the metadata of each request directory under
    ``name`` in the runtime and state directories."""
    q = shlex.quote(name)
    hexes = "[0-9a-f]" * 8
    return f"""\
me=$(id -un)
for base in "${{XDG_RUNTIME_DIR:-/nonexistent}}"/{q} \\
    /run/user/"$(id -u)"/{q} "$HOME"/.local/state/{q}; do
  [ -d "$base" ] || continue
  find "$base" -mindepth 1 -maxdepth 1 -type d -name 'r-*' -mmin -1440 \\
      2>/dev/null | while read -r d; do
    case "${{d##*/}}" in r-{hexes}) ;; *) continue;; esac
    set -- $(ls -ld "$d")
    case "$1" in drwx------|drwx------.|drwx------@) ;; *) continue;; esac
    [ "$3" = "$me" ] || continue
    echo "{REQUEST} ${{d##*/}}"
    for f in request pane state; do
      echo "{FILE} $f"
      n={OTHER_BYTES}; [ "$f" = request ] && n={REQUEST_BYTES}
      [ -f "$d/$f.json" ] && [ ! -L "$d/$f.json" ] && \\
        head -c "$n" "$d/$f.json"
      echo
    done
    r=0; [ -e "$d/result.json" ] && r=1
    c=0; [ -e "$d/cancel.json" ] && c=1
    echo "{FLAGS} result=$r cancel=$c"
  done
done"""


def _blocks(text):
    """[{id, files: {name: [lines]}, flags}] in the scan's output."""
    blocks, block, name = [], None, None
    for line in text.splitlines():
        if line.startswith(REQUEST + " "):
            block = {"id": line[len(REQUEST) + 1:], "files": {},
                     "flags": []}
            blocks.append(block)
            name = None
        elif block is None:
            continue
        elif line.startswith(FILE + " "):
            name = line[len(FILE) + 1:]
            block["files"][name] = []
        elif line.startswith(FLAGS + " "):
            block["flags"] = line.split()[1:]
            name = None
        elif name:
            block["files"][name].append(line)
    return blocks


def _object(lines):
    try:
        data = json.loads("\n".join(lines or []))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _open(block, now):
    """The block's Request if it is well formed and open at ``now``."""
    if (not ID.fullmatch(block["id"])
            or block["flags"] != ["result=0", "cancel=0"]):
        return None
    data = _object(block["files"].get("request"))
    if data is None or data.get("id") != block["id"]:
        return None
    if not (finite(data.get("created")) and finite(data.get("expires"))):
        return None
    texts = [data.get(k) for k in ("pane_id", "workspace_id", "purpose")]
    if not all(isinstance(t, str) for t in texts):
        return None
    deadline = data["expires"]
    state = _object(block["files"].get("state"))
    if (state and isinstance(state.get("phase"), str)
            and finite(state.get("deadline")) and finite(state.get("at"))):
        writing = state["phase"] == "writing"
        if now - state["at"] <= (WRITE_STALE if writing else STALE):
            # The requester waits for a write however long it takes.
            deadline = None if writing else state["deadline"]
    if deadline is not None and now >= deadline:
        return None
    pane = _object(block["files"].get("pane"))
    prompt = pane.get("pane_id") if pane else None
    return Request(block["id"], float(data["created"]),
                   None if deadline is None else float(deadline), *texts,
                   prompt if isinstance(prompt, str) else None)


def panes(text):
    """The prompt panes named by every request directory in the scan,
    open or not: a prompt pane outlives its request and may still be
    listed by Herdr as an agent."""
    found = set()
    for block in _blocks(text):
        pane = _object(block["files"].get("pane"))
        prompt = pane.get("pane_id") if pane else None
        if isinstance(prompt, str):
            found.add(prompt)
    return frozenset(found)


def parse(text, now):
    """The open requests in ``scan_shell`` output at the host's ``now``,
    each once."""
    found, seen = [], set()
    for block in _blocks(text):
        request = _open(block, now)
        if request and request.id not in seen:
            seen.add(request.id)
            found.append(request)
    return found
