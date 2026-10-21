"""The plugin's settings, from config.toml in its Herdr config directory.

    deploy = "off"   # off | ask | auto
    pipeline_url = ""   # the dispatcher's /status; empty: no pipeline card
    deploy_exclude = ["name"]   # machines (card names) deploy skips
"""

import tomllib
from pathlib import Path

from statslib import pipeline

MODES = ("off", "ask", "auto")


def load(directory):
    """(deploy mode, note): the note explains a fallback to "off"."""
    path = Path(directory) / "config.toml"
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return "off", None
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return "off", f"config.toml unreadable ({exc}); deploy is off"
    mode = data.get("deploy", "off")
    if mode not in MODES:
        return "off", (f"deploy = {mode!r} is not off, ask or auto; "
                       "deploy is off")
    return mode, None


def load_deploy_exclude(directory):
    """(names, note): the machines deploy must skip.

    A value that is not a list of names returns a note, and the caller
    turns deploy off: ignoring a broken exclusion would deploy to the
    very machines it was meant to protect.
    """
    path = Path(directory) / "config.toml"
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return (), None
    except (OSError, tomllib.TOMLDecodeError):
        return (), None  # load() already says the file is unreadable
    names = data.get("deploy_exclude", [])
    if not isinstance(names, list) or not all(
            isinstance(n, str) and n for n in names):
        return (), ("deploy_exclude must be a list of machine names; "
                    "deploy is off")
    return tuple(names), None


def load_pipeline_url(directory):
    """(url, note): "" means no pipeline card; the note says why a bad
    value was ignored."""
    path = Path(directory) / "config.toml"
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return "", None
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return "", f"config.toml unreadable ({exc}); no pipeline card"
    url = data.get("pipeline_url", "")
    if url and not pipeline.valid_url(url):
        return "", (f"pipeline_url = {url!r} is not an http(s) URL; "
                    "no pipeline card")
    return url, None
