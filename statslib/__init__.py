"""herdr-machine-stats: live stats for every machine Herdr knows."""

import tomllib
from pathlib import Path

PLUGIN_ID = "renzof.herdr-machine-stats"
REPO = "RenzoF/herdr-machine-stats"
PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def local_version(root=PLUGIN_ROOT):
    """The version in this copy's herdr-plugin.toml."""
    with open(Path(root) / "herdr-plugin.toml", "rb") as f:
        return tomllib.load(f)["version"]
