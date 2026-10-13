"""Drawing items for the outline: the subject line only, like a commit's
subject, with the box coloured and file references underlined."""

from __future__ import annotations

from collections.abc import Collection

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


def draw_line(
    depth: int,
    subject: str,
    *,
    box: str = "",
    is_open: bool = True,
    number: int | None = None,
    width: int = 0,
    folded: int = 0,
) -> Text:
    """`subject`, `[ ] subject`, `[-] subject` or `[x] subject`, indented by depth, after its
    number in a dim gutter, and `▸ 3` when three items are folded away under it."""
    gutter = "" if number is None else str(number)
    text = Text(f"{gutter:>{width}} " if width else "", style=MUTED)
    text.append(INDENT * depth)
    if box:
        text.append(f"{box} ", style=OPEN_BOX if is_open else DONE_BOX)
    else:
        text.append("• ", style=MUTED)
    start = len(text)
    text.append(subject, style=None if is_open else DONE_TEXT)
    for match in REF_RE.finditer(subject):
        # The meta tells a click which reference it landed on.
        style = Style.parse(REF) + Style(meta={"ref": match[0]})
        text.stylize(style, start + match.start(), start + match.end())
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
) -> Text:
    """How an item looks in the outline, optionally with text still being typed."""
    first = (item.text if text is None else text).partition("\n")[0]
    return draw_line(
        item.depth,
        first,
        box="[-]" if item.mixed else item.box,
        is_open=item.is_open,
        number=number,
        width=width,
        folded=sum(1 for _ in item.descendants()) if folded else 0,
    )


def gutter_width(doc: Document) -> int:
    return len(str(max(len(doc), 1)))


def outline(doc: Document, folded: Collection[str] = ()) -> list[tuple[Text, str]]:
    """The items showing, in order, each with its ID. Items are numbered in
    file order, so folding doesn't renumber anything."""
    numbers = {item.id: n for n, item in enumerate(doc.walk(), start=1)}
    width = gutter_width(doc)
    return [
        (
            item_line(
                item,
                number=numbers[item.id],
                width=width,
                folded=item.id in folded and bool(item.children),
            ),
            item.id,
        )
        for item in ops.visible(doc, folded)
    ]
