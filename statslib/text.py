"""Text from other programs, made safe and measured for the terminal.

Everything the needs-you list shows came from Herdr, a request file or
an agent's screen. ``clean`` removes what a terminal would act on;
``cells``, ``cut`` and ``pad`` measure in terminal columns, so a wide
character such as 🔑 takes two.
"""

import re
import unicodedata

_SEQUENCES = re.compile(
    r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]"           # CSI
    r"|(?:\x1b[\]PX^_]|[\x90\x98\x9d\x9e\x9f])"   # OSC DCS SOS PM APC,
    r"[^\x07\x1b\x9c]*(?:\x07|\x1b\\|\x9c)?"      # up to BEL or ST
    r"|\x1b[ -/]*[0-~]"                           # other ESC sequences
)
# Controls, format characters (bidi overrides, zero-width joiners),
# private use, surrogates and unassigned code points.
_DROPPED = {"Cc", "Cf", "Co", "Cs", "Cn"}
# Box drawing that agent UIs put around their prompts.
BOX = "─━│┃┄┅┆┇┈┉┊┋┌┐└┘├┤┬┴┼╭╮╯╰═║╔╗╚╝╠╣╦╩╬▁▔"


def clean(value):
    """``value`` as one line of plain text; anything but a string is
    ``""``."""
    if not isinstance(value, str):
        return ""
    value = _SEQUENCES.sub("", value).replace("\t", " ")
    kept = "".join(c for c in value
                   if unicodedata.category(c) not in _DROPPED)
    return " ".join(kept.split())


def cells(value):
    """The terminal columns ``value`` takes."""
    total = 0
    for char in value:
        if unicodedata.category(char) in ("Mn", "Me", "Cf"):
            continue
        total += 2 if unicodedata.east_asian_width(char) in "WF" else 1
    return total


def _prefix(value, room):
    """The longest start of ``value`` within ``room`` cells."""
    used = 0
    for i, char in enumerate(value):
        used += cells(char)
        if used > room:
            return value[:i]
    return value


def cut(value, room):
    """``value`` within ``room`` cells: cut between words and ended with
    one ellipsis; a word is split only when no whole word fits."""
    if cells(value) <= room:
        return value
    if room < 1:
        return ""
    kept = ""
    for word in value.split(" "):
        longer = f"{kept} {word}" if kept else word
        if cells(longer) > room - 1:
            break
        kept = longer
    if not kept:
        kept = _prefix(value, room - 1)
    return kept.rstrip(" ,;:(") + "…"


def pad(value, width):
    """``value`` cut or padded with spaces to exactly ``width`` cells."""
    value = cut(value, width)
    return value + " " * (width - cells(value))


def meaningful(lines, keep=3):
    """The last ``keep`` lines of a screen that say something: cleaned,
    box-drawing borders stripped, blank and border-only lines dropped."""
    kept = []
    for line in lines:
        line = clean(line).strip(BOX + " ")
        if line:
            kept.append(line)
    return kept[-keep:] if keep > 0 else []
