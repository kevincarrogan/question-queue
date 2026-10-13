"""The outline, and how each item remembers the lines it came from.

An item is a list item in the file: a subject line (`- text`, optionally
ticked as `- [ ] text` / `- [x] text`), then optionally a body of indented
lines under it, like a commit message. Items nest under items.

An item that hasn't changed since it was parsed writes back its original
lines byte for byte. Changing its text drops all of them; ticking it, or
adding or removing its box, drops only the subject line. That is what keeps
load → save lossless for notes the tool hasn't touched.
"""

from __future__ import annotations

from collections.abc import Iterator
from enum import StrEnum

from .errors import ItemNotFound

INDENT_STEP = "  "
TAB_WIDTH = 4


class Status(StrEnum):
    OPEN = "open"
    DONE = "done"


class Kind(StrEnum):
    """Whether the item has a box to tick."""

    PLAIN = "plain"  # - text
    TODO = "todo"  # - [ ] text  /  - [x] text


def indent_width(indent: str) -> int:
    return len(indent.expandtabs(TAB_WIDTH))


def leading_whitespace(line: str) -> str:
    return line[: len(line) - len(line.lstrip(" \t"))]


def shift_line(line: str, delta: int) -> str:
    """Indent a line by `delta` columns (outdent if negative). Blank lines are left as they are."""
    if not line.strip() or delta == 0:
        return line
    if delta > 0:
        return " " * delta + line
    removed = 0
    i = 0
    while i < len(line) and line[i] in " \t" and removed < -delta:
        removed += TAB_WIDTH if line[i] == "\t" else 1
        i += 1
    return line[i:]


class RawLine:
    """A line the parser doesn't recognise: kept verbatim and in position."""

    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return f"RawLine({self.text!r})"


type Entry = Item | RawLine


class Container:
    """Anything that holds an ordered mix of items and raw lines."""

    items: list[Entry]

    @property
    def children(self) -> list[Item]:
        return [entry for entry in self.items if isinstance(entry, Item)]


class Item(Container):
    def __init__(
        self,
        id: str,
        text: str,
        *,
        parent: Container,
        status: Status = Status.OPEN,
        kind: Kind = Kind.PLAIN,
        indent: str = "",
        marker: str = "-",
    ) -> None:
        self.id = id
        self._text = text
        self._status = status
        self._kind = kind
        self.parent = parent
        self.items = []
        self.indent = indent
        self.marker = marker
        # The source lines, while they still match the fields above.
        self.source_subject: str | None = None
        self.source_body: list[str] | None = None
        # The indent the body's lines were written with.
        self.body_indent: str | None = None

    def __repr__(self) -> str:
        return f"Item({self.id!r}, {self.subject!r}, {self._kind.value}, {self._status.value})"

    @property
    def text(self) -> str:
        """The whole item: the subject line, then the body's lines."""
        return self._text

    @text.setter
    def text(self, value: str) -> None:
        if value != self._text:
            self._text = value
            self.source_subject = None
            self.source_body = None

    @property
    def subject(self) -> str:
        return self._text.split("\n", 1)[0]

    @property
    def body(self) -> str:
        parts = self._text.split("\n", 1)
        return parts[1] if len(parts) > 1 else ""

    @property
    def status(self) -> Status:
        return self._status

    @status.setter
    def status(self, value: Status) -> None:
        if value != self._status:
            self._status = value
            self.source_subject = None

    @property
    def kind(self) -> Kind:
        return self._kind

    @kind.setter
    def kind(self, value: Kind) -> None:
        if value != self._kind:
            self._kind = value
            self.source_subject = None

    @property
    def is_open(self) -> bool:
        return self._status is Status.OPEN

    @property
    def box(self) -> str:
        """`[ ]`, `[x]`, or nothing for a plain item."""
        if self._kind is Kind.PLAIN:
            return ""
        return "[ ]" if self.is_open else "[x]"

    @property
    def ticks(self) -> list[Item]:
        """The children with boxes. When there are any, they decide whether
        this item is ticked (see `ops.mark_done`)."""
        return [child for child in self.children if child.kind is Kind.TODO]

    @property
    def mixed(self) -> bool:
        """A box whose ticks are partly done. In the file it's `[ ]`, since
        it isn't done; the outline shows `[-]`."""
        ticks = self.ticks if self._kind is Kind.TODO else []
        return any(t.mixed for t in ticks) or len({t.is_open for t in ticks}) > 1

    @property
    def parent_id(self) -> str | None:
        return self.parent.id if isinstance(self.parent, Item) else None

    @property
    def depth(self) -> int:
        depth = 0
        node = self.parent
        while isinstance(node, Item):
            depth += 1
            node = node.parent
        return depth

    def ancestors(self) -> list[Item]:
        """Root-most first, ending with the parent. O(depth) via parent pointers."""
        chain: list[Item] = []
        node = self.parent
        while isinstance(node, Item):
            chain.append(node)
            node = node.parent
        chain.reverse()
        return chain

    def walk(self) -> Iterator[Item]:
        """This item and every item under it, in document order."""
        yield self
        for child in self.children:
            yield from child.walk()

    def descendants(self) -> Iterator[Item]:
        it = self.walk()
        next(it)
        yield from it

    def render_subject(self) -> str:
        box = f"{self.box} " if self.box else ""
        return f"{self.indent}{self.marker} {box}{self.subject} <!-- q:{self.id} -->"

    def render_body(self) -> list[str]:
        if not self.body:
            return []
        prefix = (
            self.body_indent
            if self.body_indent is not None
            else self.indent + INDENT_STEP
        )
        return [f"{prefix}{line}" if line else "" for line in self.body.split("\n")]

    def own_lines(self) -> list[str]:
        """The subject line and the body's lines, not including children."""
        subject = (
            self.source_subject
            if self.source_subject is not None
            else self.render_subject()
        )
        body = self.source_body if self.source_body is not None else self.render_body()
        return [subject, *body]

    def shift(self, delta: int) -> None:
        """Re-indent this whole subtree by `delta` columns, raw lines included."""
        if delta == 0:
            return
        self.indent = leading_whitespace(shift_line(self.indent + "x", delta))
        if self.source_subject is not None:
            self.source_subject = shift_line(self.source_subject, delta)
        if self.source_body is not None:
            self.source_body = [shift_line(s, delta) for s in self.source_body]
        if self.body_indent is not None:
            self.body_indent = leading_whitespace(
                shift_line(self.body_indent + "x", delta)
            )
        for entry in self.items:
            if isinstance(entry, Item):
                entry.shift(delta)
            else:
                entry.text = shift_line(entry.text, delta)


class Document(Container):
    """The root. Holds top-level items and everything else in the file."""

    def __init__(self) -> None:
        self.items = []
        self.newline = "\n"
        self.trailing_newline = True
        # Set by the parser when it had to add or replace IDs.
        self.ids_assigned = False
        self._index: dict[str, Item] = {}

    def __contains__(self, item_id: object) -> bool:
        return item_id in self._index

    def __len__(self) -> int:
        return len(self._index)

    def get(self, item_id: str) -> Item:
        try:
            return self._index[item_id]
        except KeyError:
            raise ItemNotFound(item_id) from None

    def walk(self) -> Iterator[Item]:
        """Every item, in document order."""
        for child in self.children:
            yield from child.walk()

    def ids(self) -> set[str]:
        return set(self._index)

    def register(self, item: Item) -> None:
        for each in item.walk():
            self._index[each.id] = each

    def unregister(self, item: Item) -> None:
        for each in item.walk():
            self._index.pop(each.id, None)
