"""The few Herdr reads machine-stats needs.

Only this module names the herdr CLI.
"""

import json
import os
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
    return Path(_local(["plugin", "config-dir", plugin_id], timeout).strip())


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
