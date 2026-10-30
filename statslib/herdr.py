"""The few Herdr reads machine-stats needs.

Only this module names the herdr CLI.
"""

import json
import os
import shlex
import subprocess
from pathlib import Path


class HerdrError(RuntimeError):
    """Herdr answered with an error."""


class HerdrUnavailable(HerdrError):
    """The herdr binary is missing."""


class HerdrTimeout(HerdrError):
    """Herdr did not answer in time."""


def _local(args, timeout):
    """stdout of ``herdr <args>`` on this machine, outside a Herdr pane."""
    try:
        result = subprocess.run(
            [os.environ.get("HERDR_BIN", "herdr"), *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise HerdrTimeout(str(exc)) from exc
    except OSError as exc:
        raise HerdrUnavailable(str(exc)) from exc
    if result.returncode:
        raise HerdrError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def machine_list_text(timeout=10):
    """The raw output of ``herdr machine list``: saved SSH machines.

    Works outside a Herdr pane: it only reads the saved machine profiles.
    """
    return _local(["machine", "list"], timeout)


def config_dir(plugin_id, timeout=10):
    """The Herdr config directory of ``plugin_id``."""
    printed = _local(["plugin", "config-dir", plugin_id], timeout).strip()
    if not printed:  # Path("") would be the current directory
        raise HerdrError("herdr plugin config-dir printed nothing")
    return Path(printed)


# The agent list as a shell fragment, for scripts that run on other hosts.
AGENT_LIST_SHELL = "herdr agent list 2>/dev/null"


def status_counts(text):
    """Agents by status in the output of ``herdr agent list``.

    Returns None when ``text`` is not that output, for example because the
    host has no Herdr or its server is not running.
    """
    try:
        agents = json.loads(text)["result"]["agents"]
        counts = {}
        for agent in agents:
            status = agent.get("agent_status") or "unknown"
            counts[status] = counts.get(status, 0) + 1
        return counts
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


WORKSPACE_LIST_SHELL = "herdr workspace list 2>/dev/null"
TAB_LIST_SHELL = "herdr tab list 2>/dev/null"


def _result_list(text, key):
    """The dicts in ``result[key]`` of a herdr JSON answer, or None."""
    try:
        items = json.loads(text)["result"][key]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(items, list):
        return None
    return [item for item in items if isinstance(item, dict)]


def _numbered(items, id_field):
    """{id: (number, label)}: the numbers and labels Herdr's screen
    shows. Entries without a string id or an integer number are
    skipped."""
    if items is None:
        return None
    found = {}
    for item in items:
        ident, number = item.get(id_field), item.get("number")
        if (isinstance(ident, str) and isinstance(number, int)
                and not isinstance(number, bool)):
            label = item.get("label")
            found[ident] = (number, label if isinstance(label, str) else "")
    return found


def agents(text):
    """The agents in ``herdr agent list`` output; None when unusable."""
    return _result_list(text, "agents")


def workspaces(text):
    """{workspace_id: (number, label)} from ``herdr workspace list``."""
    return _numbered(_result_list(text, "workspaces"), "workspace_id")


def tabs(text):
    """{tab_id: (number, label)} from ``herdr tab list``."""
    return _numbered(_result_list(text, "tabs"), "tab_id")


def plugin_list_shell(plugin_id):
    """``herdr plugin list`` for one plugin, as a remote shell fragment."""
    return f"herdr plugin list --plugin {plugin_id} --json 2>/dev/null"


def plugin_entry(text):
    """The plugin's entry from ``herdr plugin list --json``.

    ``{}`` when Herdr answered and the plugin is not installed; None when
    there is no usable answer (no Herdr, or garbage).
    """
    try:
        plugins = json.loads(text)["result"]["plugins"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(plugins, list):
        return None
    return plugins[0] if plugins else {}


READ_MARKER = "--pane--"


def read_shell(pane_ids):
    """Shell that prints each pane's visible screen as plain text, each
    after a ``--pane-- <id>`` line. Reading never marks an agent seen."""
    return "\n".join(
        f"echo {READ_MARKER} {shlex.quote(pane)}\n"
        f"herdr agent read {shlex.quote(pane)} --source visible"
        " --format text 2>/dev/null | tail -n 60"
        for pane in pane_ids)


def screens(text):
    """{pane_id: lines} from ``read_shell`` output."""
    found, lines = {}, None
    for line in text.splitlines():
        if line.startswith(READ_MARKER + " "):
            lines = found.setdefault(line[len(READ_MARKER) + 1:], [])
        elif lines is not None:
            lines.append(line)
    return found


def focus(pane_id, timeout=5):
    """Focus ``pane_id`` on this machine's Herdr. This marks a finished
    agent seen."""
    _local(["agent", "focus", pane_id], timeout)


def focus_shell(pane_id):
    """The same focus, as a shell fragment for another machine."""
    return f"herdr agent focus {shlex.quote(pane_id)}"
