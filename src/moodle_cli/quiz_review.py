"""Reading a finished quiz attempt out of the review HTML Moodle renders for it.

``mod_quiz_get_attempt_review`` returns each question as the HTML fragment of the student's
review page, not as data. The fragment follows Moodle's question markup, whose classes
separate the prompt (``.qtext``), the response (``.answer``), the right answer
(``.rightanswer``) and the feedback (``.specificfeedback``, ``.generalfeedback``). Each
question type lays out its response differently, so each type gets its own extractor; the
parts every type shares are read once, here.

The quiz's review options decide which of those parts the campus renders at all. A part
the quiz hides is simply absent from the fragment, so every field below reads absent as
``None`` instead of as an empty answer.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from moodle_cli.models import ReviewAnswer, ReviewQuestion

#: Elements that never have content, so never get a closing tag.
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
#: Elements whose end breaks a line of text.
_BLOCK_TAGS = frozenset(
    {
        "br",
        "p",
        "div",
        "li",
        "ul",
        "ol",
        "tr",
        "table",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "fieldset",
        "legend",
        "label",
    }
)
#: Elements whose content never reads as text.
_SKIPPED_TAGS = frozenset({"script", "style"})
#: Classes Moodle puts on text meant only for screen readers ("Question 1", "Select one:").
_HIDDEN_CLASSES = frozenset({"accesshide", "visually-hidden", "sr-only"})


@dataclass
class Element:
    """One HTML element of a question fragment, with its children in document order."""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[Element | str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def iter(self) -> Iterator[Element]:
        """Every descendant element, depth first, in document order."""
        for child in self.children:
            if isinstance(child, Element):
                yield child
                yield from child.iter()

    def find_all(self, tag: str | None = None, *, class_: str | None = None) -> list[Element]:
        return [
            e
            for e in self.iter()
            if (tag is None or e.tag == tag) and (class_ is None or class_ in e.classes)
        ]

    def find(self, tag: str | None = None, *, class_: str | None = None) -> Element | None:
        return next(iter(self.find_all(tag, class_=class_)), None)

    def text(self) -> str:
        """Visible text, one line per block element, whitespace collapsed within a line.

        Screen-reader-only text is left out: it repeats what the layout already says.
        """
        parts: list[str] = []
        self._collect(parts)
        lines = (" ".join(line.split()) for line in "".join(parts).split("\n"))
        return "\n".join(line for line in lines if line)

    def _collect(self, parts: list[str]) -> None:
        if self.tag in _SKIPPED_TAGS or self.classes & _HIDDEN_CLASSES:
            return
        for child in self.children:
            if isinstance(child, str):
                parts.append(child)
            else:
                child._collect(parts)
        if self.tag in _BLOCK_TAGS:
            parts.append("\n")


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("root")
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = Element(tag, {k: v or "" for k, v in attrs})
        self._stack[-1].children.append(element)
        if tag not in _VOID_TAGS:
            self._stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack[-1].children.append(Element(tag, {k: v or "" for k, v in attrs}))

    def handle_endtag(self, tag: str) -> None:
        # Close back to the matching element; a stray end tag with no open match is dropped.
        for depth in range(len(self._stack) - 1, 0, -1):
            if self._stack[depth].tag == tag:
                del self._stack[depth:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].children.append(data)


def parse_fragment(markup: str) -> Element:
    builder = _TreeBuilder()
    builder.feed(markup)
    builder.close()
    return builder.root


def _text_of(root: Element, class_: str) -> str | None:
    """The text of the first element with ``class_``, or ``None`` when it is absent or empty."""
    element = root.find(class_=class_)
    return (element.text() or None) if element is not None else None


def _is_checked(element: Element) -> bool:
    return "checked" in element.attrs


def _correctness(classes: set[str]) -> bool | None:
    """Moodle's verdict on one part of a response; ``None`` when the quiz hides it."""
    if "correct" in classes:
        return True
    if "incorrect" in classes or "partiallycorrect" in classes:
        return False
    return None


@dataclass
class Parts:
    """What a type's extractor reads off the fragment; the shared parts are read elsewhere."""

    prompt: str
    choices: list[str] = field(default_factory=list)
    answers: list[ReviewAnswer] = field(default_factory=list)


def _parse_generic(root: Element) -> Parts:
    """Prompt plus whatever the ``.answer`` block shows, for a type with no extractor."""
    answer = _text_of(root, "answer")
    return Parts(
        prompt=_text_of(root, "qtext") or "",
        answers=[ReviewAnswer(text=answer)] if answer else [],
    )


def _parse_choice_rows(root: Element) -> Parts:
    """One option per row of ``.answer``; the checked rows are the student's response.

    A row carries ``correct``/``incorrect`` only when it was chosen and the quiz shows
    whether responses were right. The option's text is its ``.flex-fill`` content when the
    row has one: that leaves out the ``a.`` numbering and the chosen option's own feedback,
    which sit beside it in the same row.
    """
    choices: list[str] = []
    answers: list[ReviewAnswer] = []
    block = root.find(class_="answer")
    rows = [c for c in block.children if isinstance(c, Element)] if block else []
    for row in rows:
        label = (row.find(class_="flex-fill") or row).text()
        choices.append(label)
        if any(_is_checked(i) for i in row.find_all("input")):
            answers.append(
                ReviewAnswer(
                    text=label,
                    correct=_correctness(row.classes),
                    feedback=_text_of(row, "specificfeedback"),
                )
            )
    return Parts(prompt=_text_of(root, "qtext") or "", choices=choices, answers=answers)


def _parse_truefalse(root: Element) -> Parts:
    return _parse_choice_rows(root)


def _parse_multichoice(root: Element) -> Parts:
    return _parse_choice_rows(root)


def _parse_shortanswer(root: Element) -> Parts:
    """The typed response lives in the input's ``value``; the verdict sits on the input too."""
    prompt = _text_of(root, "qtext") or ""
    block = root.find(class_="answer")
    box = block.find("input") if block else None
    typed = box.attrs.get("value", "").strip() if box else ""
    if box is None or not typed:
        return Parts(prompt=prompt)
    return Parts(
        prompt=prompt, answers=[ReviewAnswer(text=typed, correct=_correctness(box.classes))]
    )


def _distinct(texts: list[str]) -> list[str]:
    return list(dict.fromkeys(t for t in texts if t))


#: The value of the placeholder option a match row shows until the student picks one.
_MATCH_PLACEHOLDER = "0"


def _parse_match(root: Element) -> Parts:
    """One ``stem -> chosen option`` answer per row whose select left the placeholder.

    The row's verdict sits on its ``td.control``, and only when the quiz shows correctness.
    """
    offered: list[str] = []
    answers: list[ReviewAnswer] = []
    block = root.find(class_="answer")
    for row in block.find_all("tr") if block else []:
        stem, control = row.find("td", class_="text"), row.find("td", class_="control")
        select = control.find("select") if control else None
        if stem is None or control is None or select is None:
            continue
        options = [
            o for o in select.find_all("option") if o.attrs.get("value") != _MATCH_PLACEHOLDER
        ]
        offered.extend(o.text() for o in options)
        chosen = next((o for o in options if "selected" in o.attrs), None)
        if chosen is not None:
            answers.append(
                ReviewAnswer(
                    text=f"{stem.text()} -> {chosen.text()}", correct=_correctness(control.classes)
                )
            )
    return Parts(prompt=_text_of(root, "qtext") or "", choices=_distinct(offered), answers=answers)


def _numbered(classes: set[str], prefix: str) -> str | None:
    """The number of a ``<prefix><n>`` class such as ``place3``."""
    return next((c.removeprefix(prefix) for c in classes if c.removeprefix(prefix).isdigit()), None)


def _icon_correctness(node: Element | str | None) -> bool | None:
    """The verdict of a feedback icon; ``None`` when ``node`` is not one."""
    if not isinstance(node, Element) or node.tag != "i":
        return None
    if "text-success" in node.classes:
        return True
    if node.classes & {"text-danger", "text-warning"}:
        return False
    return None


#: Reads the gap at ``siblings[index]``, or returns ``None`` when that element is not a gap.
_GapReader = Callable[[list[Element | str], int], ReviewAnswer | None]


def _fill_gaps(root: Element, read_gap: _GapReader) -> tuple[str, list[ReviewAnswer]]:
    """The prompt with each gap rendered inline as the student filled it, and the gaps' answers.

    The prompt's gaps are replaced in place, in document order.
    """
    qtext = root.find(class_="qtext")
    if qtext is None:
        return "", []
    answers: list[ReviewAnswer] = []

    def fill(element: Element) -> None:
        children = element.children
        for index, child in enumerate(children):
            if not isinstance(child, Element):
                continue
            answer = read_gap(children, index)
            if answer is None:
                fill(child)
            else:
                answers.append(answer)
                children[index] = f"[{answer.text or '___'}]"

    fill(qtext)
    return qtext.text(), answers


def _parse_gapselect(root: Element) -> Parts:
    """One ``.control`` per gap, wrapping a ``<select>`` whose ``selected`` option is the
    student's word.

    The select carries ``correct``/``incorrect`` only when the quiz shows correctness.
    """
    choices = _distinct([o.text() for s in root.find_all("select") for o in s.find_all("option")])

    def read_gap(siblings: list[Element | str], index: int) -> ReviewAnswer | None:
        control = siblings[index]
        if not isinstance(control, Element) or "control" not in control.classes:
            return None
        select = control.find("select")
        if select is None:
            return None
        chosen = (o.text() for o in select.find_all("option") if "selected" in o.attrs)
        return ReviewAnswer(text=next(chosen, ""), correct=_correctness(select.classes))

    prompt, answers = _fill_gaps(root, read_gap)
    return Parts(prompt=prompt, choices=choices, answers=answers)


def _parse_ddwtos(root: Element) -> Parts:
    """One empty ``.drop`` per gap, filled through the hidden ``placeinput`` of its place.

    The input holds the number of the chosen ``draghome`` within the gap's group, ``0`` or
    empty when the gap was left blank.
    """
    homes = root.find_all(class_="draghome")
    pool = {
        (_numbered(h.classes, "group"), _numbered(h.classes, "choice")): h.text() for h in homes
    }
    placed = {
        _numbered(i.classes, "place"): i.attrs.get("value")
        for i in root.find_all("input", class_="placeinput")
    }

    def read_gap(siblings: list[Element | str], index: int) -> ReviewAnswer | None:
        drop = siblings[index]
        if not isinstance(drop, Element) or "drop" not in drop.classes:
            return None
        # Moodle renders every drop followed by one space, then a feedback icon when the
        # quiz shows correctness; the space is the renderer's, not the prompt's.
        rest = siblings[index + 1 :]
        if rest and isinstance(rest[0], str) and rest[0].startswith(" "):
            siblings[index + 1] = rest[0][1:]
        icon = next((c for c in rest if not (isinstance(c, str) and c.isspace())), None)
        choice = placed.get(_numbered(drop.classes, "place"))
        text = pool.get((_numbered(drop.classes, "group"), choice), "")
        return ReviewAnswer(text=text, correct=_icon_correctness(icon))

    prompt, answers = _fill_gaps(root, read_gap)
    return Parts(prompt=prompt, choices=_distinct([h.text() for h in homes]), answers=answers)


_EXTRACTORS: dict[str, Callable[[Element], Parts]] = {
    "truefalse": _parse_truefalse,
    "multichoice": _parse_multichoice,
    "shortanswer": _parse_shortanswer,
    "match": _parse_match,
    "gapselect": _parse_gapselect,
    "ddwtos": _parse_ddwtos,
}


def _mark(value: Any) -> float | None:
    """A mark arrives as a string, and is absent when the quiz hides marks."""
    if value is None or value == "":
        return None
    return float(value)


def parse_question(question: dict[str, Any]) -> ReviewQuestion:
    """One entry of ``mod_quiz_get_attempt_review``'s ``questions`` as a structured question."""
    root = parse_fragment(question.get("html") or "")
    question_type = str(question.get("type") or "")
    parts = _EXTRACTORS.get(question_type, _parse_generic)(root)
    # An option's own feedback also carries ``specificfeedback``, inside its row; the
    # question's feedback is the one under ``.outcome``.
    outcome = root.find(class_="outcome") or Element("outcome")
    return ReviewQuestion(
        number=str(question.get("questionnumber") or question.get("slot") or ""),
        type=question_type,
        state=question.get("state") or None,
        mark=_mark(question.get("mark")),
        max_mark=float(question.get("maxmark") or 0),
        prompt=parts.prompt,
        choices=parts.choices,
        answers=parts.answers,
        right_answer=_text_of(outcome, "rightanswer"),
        feedback=_text_of(outcome, "specificfeedback"),
        general_feedback=_text_of(outcome, "generalfeedback"),
    )
