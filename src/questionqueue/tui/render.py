"""Drawing items for the outline: the subject line only, like a commit's
subject, with the box coloured and file references underlined."""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass

from rich.style import Style
from rich.text import Text

from ..core import Document, Item, ops
from ..core.refs import REF_RE

INDENT = "  "

OPEN_BOX = "bold #8FA0FF"
DONE_BOX = "bold #6FD3AE"
MUTED = "#8A90A0"
DONE_TEXT = "#9AA0AE"
REF = "underline #7FD4E0"
# How much of a further line a find shows after the subject.
GLIMPSE = 30

# What a search found, as vim's hlsearch shows it.
FOUND = "bold #181B20 on #E8C468"


@dataclass(frozen=True)
class Found:
    """The items a search (or a replace) finds, and what to mark in them."""

    pattern: re.Pattern[str]
    ids: frozenset[str]


def mark(text: Text, pattern: re.Pattern[str], start: int = 0) -> bool:
    """Mark what `pattern` finds in `text` from `start`. Whether it found any."""
    hits = list(pattern.finditer(text.plain, start))
    for hit in hits:
        if hit.end() > hit.start():
            text.stylize(FOUND, hit.start(), hit.end())
    return bool(hits)


def draw_line(
    depth: int,
    subject: str,
    *,
    box: str = "",
    is_open: bool = True,
    number: int | None = None,
    width: int = 0,
    folded: int = 0,
    found: re.Pattern[str] | None = None,
) -> Text:
    """`subject`, `[ ] subject`, `[-] subject` or `[x] subject`, indented by depth, after its
    number in a dim gutter, and `▸ 3` when three items are folded away under it.
    With `found`, what it finds in the subject is marked."""
    gutter = "" if number is None else str(number)
    text = Text(f"{gutter:>{width}} " if width else "", style=MUTED)
    text.append(INDENT * depth)
    if box:
        # The meta tells a click it landed on the box, which ticks it.
        style = Style.parse(OPEN_BOX if is_open else DONE_BOX) + Style(
            meta={"box": True}
        )
        text.append(box, style=style)
        text.append(" ")
    else:
        text.append("• ", style=MUTED)
    start = len(text)
    text.append(subject, style=None if is_open else DONE_TEXT)
    for match in REF_RE.finditer(subject):
        # The meta tells a click which reference it landed on.
        style = Style.parse(REF) + Style(meta={"ref": match[0]})
        text.stylize(style, start + match.start(), start + match.end())
    if found is not None:
        mark(text, found, start)
    if folded:
        text.append(f"  ▸ {folded}", style=MUTED)
    return text


def item_line(
    item: Item,
    text: str | None = None,
    *,
    number: int | None = None,
    width: int = 0,
    folded: bool = False,
    found: re.Pattern[str] | None = None,
) -> Text:
    """How an item looks in the outline, optionally with text still being typed.
    With `found`, what it finds is marked, and when that's only further down,
    the first line it's on follows the subject."""
    first, _, rest = (item.text if text is None else text).partition("\n")
    line = draw_line(
        item.depth,
        first,
        box="[-]" if item.mixed else item.box,
        is_open=item.is_open,
        number=number,
        width=width,
        folded=sum(1 for _ in item.descendants()) if folded else 0,
        found=found,
    )
    if found is not None and not found.search(first):
        further = next((each for each in rest.split("\n") if found.search(each)), None)
        if further is not None:
            line.append("  ⋯ ", style=MUTED)
            start = len(line)
            line.append(glimpse(further.strip(), found), style=MUTED)
            mark(line, found, start)
    return line


def glimpse(line: str, found: re.Pattern[str]) -> str:
    """A short stretch of `line` around what `found` finds in it, so it
    follows the subject without wrapping."""
    if len(line) <= GLIMPSE:
        return line
    hit = found.search(line)
    start = max(0, (hit.start() if hit else 0) - GLIMPSE // 3)
    end = start + GLIMPSE
    return ("…" if start else "") + line[start:end] + ("…" if end < len(line) else "")


def gutter_width(doc: Document) -> int:
    return len(str(max(len(doc), 1)))


def outline(
    doc: Document, folded: Collection[str] = (), found: Found | None = None
) -> list[tuple[Text, str]]:
    """The items showing, in order, each with its ID. Items are numbered in
    file order, so folding doesn't renumber anything. What `found` finds is marked."""
    numbers = {item.id: n for n, item in enumerate(doc.walk(), start=1)}
    width = gutter_width(doc)
    return [
        (
            item_line(
                item,
                number=numbers[item.id],
                width=width,
                folded=item.id in folded and bool(item.children),
                found=found.pattern if found and item.id in found.ids else None,
            ),
            item.id,
        )
        for item in ops.visible(doc, folded)
    ]
