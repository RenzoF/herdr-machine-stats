"""The needs-you list: what waits on you, on every machine.

``parse_raw`` reads one host's part of the collector output; later
functions turn rows into ordered items. What each group means is in
docs/specs/2026-10-27-needs-you-design.md.
"""

from collections import namedtuple

from statslib import herdr, prompts

# One host's needs data: its clock (epoch seconds, or None), the agent
# list, {workspace_id: (number, label)}, {tab_id: (number, label)} and
# its open secret requests.
Raw = namedtuple("Raw", "now agents workspaces tabs requests")


def parse_raw(parts):
    """A ``Raw`` from ``collect.sections`` of one host's output."""
    facts = dict(line.split("=", 1)
                 for line in parts.get("facts", "").splitlines()
                 if "=" in line)
    try:
        now = int(facts.get("now", ""))
    except ValueError:
        now = None
    requests = (prompts.parse(parts.get("requests", ""), now)
                if now is not None else [])
    return Raw(now, herdr.agents(parts.get("agents", "")),
               herdr.workspaces(parts.get("workspaces", "")),
               herdr.tabs(parts.get("tabs", "")), requests)
