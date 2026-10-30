"""statslib.text: cleaning and measuring text from other programs."""

import pytest

from statslib import text


@pytest.mark.parametrize("raw, want", [
    ("\x1b[1;31mred\x1b[0m", "red"),
    ("\x1b]8;;https://example.com\x1b\\link\x1b]8;;\x1b\\", "link"),
    ("\x1b]0;a title\x07after", "after"),
    ("\x9b31mc1\x9bm", "c1"),
    ("\x1bPdcs payload\x1b\\kept", "kept"),
    ("\x1b(Bplain", "plain"),
    ("a‮b‍c", "abc"),
    ("tab\there", "tab here"),
    ("bell\x07 and nul\x00", "bell and nul"),
    ("  many   spaces  ", "many spaces"),
    ("line\nbreak", "linebreak"),
])
def test_clean_removes_escape_sequences_and_control_characters(raw, want):
    assert text.clean(raw) == want


@pytest.mark.parametrize("value", [None, 3, ["x"], {"a": 1}])
def test_clean_turns_anything_but_a_string_into_nothing(value):
    assert text.clean(value) == ""


@pytest.mark.parametrize("value, width", [
    ("abc", 3), ("🔑 key", 6), ("é", 1), ("日本", 4), ("◐ ● ✓", 5),
])
def test_cells_counts_terminal_columns(value, width):
    assert text.cells(value) == width


def test_cut_keeps_what_fits():
    assert text.cut("short", 10) == "short"


def test_cut_breaks_between_words_and_ends_with_one_ellipsis():
    assert text.cut("one two three", 9) == "one two…"


def test_cut_splits_a_word_when_no_whole_word_fits():
    assert text.cut("abcdefghij", 5) == "abcd…"


def test_cut_counts_wide_characters():
    assert text.cut("🔑🔑🔑", 5) == "🔑🔑…"


def test_cut_with_no_room_is_empty():
    assert text.cut("abc", 0) == ""


def test_pad_fills_or_cuts_to_exactly_the_width():
    assert text.pad("🔑", 4) == "🔑  "
    assert text.pad("toolong", 4) == "too…"
    assert text.cells(text.pad("🔑 secret wanted", 7)) == 7


def test_meaningful_keeps_the_last_three_lines_that_say_something():
    screen = [
        "╭──────────────────────────────╮",
        "│ Do you want to edit app.py?  │",
        "│ ❯ 1. Yes                     │",
        "│   2. No                      │",
        "",
        "╰──────────────────────────────╯",
        "   ",
    ]
    assert text.meaningful(screen) == [
        "Do you want to edit app.py?", "❯ 1. Yes", "2. No"]


def test_meaningful_cleans_each_line_and_keeps_fewer_when_asked():
    assert text.meaningful(["\x1b[1mfirst\x1b[0m", "second"], keep=1) == [
        "second"]
    assert text.meaningful([]) == []
