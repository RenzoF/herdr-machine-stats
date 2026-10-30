"""Enter on a needs-you item: focus its pane, here or on its machine.

Herdr focuses per server, and nothing in its API switches which machine
your window shows, so a pane on another machine is focused there and
the message says where to find it (spec, "Jumping to a pane").
Focusing marks a finished agent seen.
"""

from statslib import collect, herdr, needsview


def jump(item, run=None):
    """(landed, message). ``landed``: the pane is now in front of you."""
    try:
        if item.target is None:
            herdr.focus(item.pane_id)
            return True, None
        (run or collect.run_host)(
            item.target,
            collect.PATH_LINE + "\n" + herdr.focus_shell(item.pane_id))
    except (herdr.HerdrError, collect.HostError) as exc:
        return False, f"{item.machine}: could not focus: {exc}"
    where = needsview.where_text(item.where) or f"the pane of {item.agent}"
    return False, (f"{item.machine}: {where}. "
                   f"Pick {item.machine} with prefix+w")
