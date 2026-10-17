"""The plugin's settings, from config.toml in its Herdr config directory.

    deploy = "off"   # off | ask | auto
"""

import tomllib
from pathlib import Path

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
