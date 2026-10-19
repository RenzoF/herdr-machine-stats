"""The plugin's settings, from config.toml in its Herdr config directory.

    deploy = "off"   # off | ask | auto
    pipeline_url = ""   # the dispatcher's /status; empty: no pipeline card
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
