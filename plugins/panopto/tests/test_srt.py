"""Tests for SRT parsing and the pause-gap paragraph grouping.

Pure and unmocked: parsing and markdown rendering touch neither the network nor disk,
so there is nothing a fixture would buy here that hand-built input does not already.
"""

from __future__ import annotations

import pytest
from moodle_cli_panopto.srt import (
    Cue,
    Paragraph,
    SrtError,
    group_into_paragraphs,
    parse_srt,
    to_markdown,
)

# -- parse_srt -----------------------------------------------------------------------


def test_parse_srt_joins_multi_line_cue_text() -> None:
    raw = (
        "1\n00:00:00,000 --> 00:00:05,000\nHello\nworld\n"
        "\n2\n00:00:05,500 --> 00:00:10,000\nSecond cue\n"
    )

    cues = parse_srt(raw)

    assert cues == [
        Cue(index=1, start=0.0, end=5.0, text="Hello world"),
        Cue(index=2, start=5.5, end=10.0, text="Second cue"),
    ]


def test_parse_srt_strips_the_disclaimer_from_the_first_cue_only() -> None:
    raw = (
        "1\n00:00:06,510 --> 00:00:20,590\n"
        "[Auto-generated transcript. Edits may have been applied for clarity.]\n"
        "Real text here.\n"
        "\n2\n00:00:21,000 --> 00:00:25,000\n[not a disclaimer] more text\n"
    )

    cues = parse_srt(raw)

    assert cues[0].text == "Real text here."
    assert cues[1].text == "[not a disclaimer] more text"


def test_parse_srt_raises_on_empty_input() -> None:
    with pytest.raises(SrtError):
        parse_srt("")


def test_parse_srt_raises_when_nothing_looks_like_a_cue() -> None:
    with pytest.raises(SrtError):
        parse_srt("this is not an SRT file at all")


# -- group_into_paragraphs ------------------------------------------------------------


def test_group_into_paragraphs_breaks_only_above_the_gap_threshold() -> None:
    cues = [
        Cue(1, 0.0, 2.0, "a"),
        Cue(2, 4.0, 6.0, "b"),  # gap == 2.0s: not > 2.0, stays in the same paragraph
        Cue(3, 8.01, 10.0, "c"),  # gap == 2.01s: > 2.0, starts a new paragraph
    ]

    paragraphs = group_into_paragraphs(cues)

    assert paragraphs == [
        Paragraph(start=0.0, text="a b"),
        Paragraph(start=8.01, text="c"),
    ]


def test_group_into_paragraphs_handles_a_single_cue() -> None:
    assert group_into_paragraphs([Cue(1, 0.0, 1.0, "solo")]) == [Paragraph(start=0.0, text="solo")]


def test_group_into_paragraphs_handles_no_cues() -> None:
    assert group_into_paragraphs([]) == []


# -- to_markdown ------------------------------------------------------------------------


def test_to_markdown_renders_title_timestamps_and_paragraphs() -> None:
    cues = [Cue(1, 0.0, 2.0, "Hola."), Cue(2, 65.0, 67.0, "Chau.")]

    markdown = to_markdown(cues, title="Clase 1")

    assert markdown == "# Clase 1\n\n**00:00:00**\nHola.\n\n**00:01:05**\nChau.\n"


def test_to_markdown_without_a_title_omits_the_heading() -> None:
    markdown = to_markdown([Cue(1, 0.0, 2.0, "Hola.")])

    assert not markdown.startswith("#")
    assert markdown == "**00:00:00**\nHola.\n"
