"""Markdown → Document.

Recognised lines:
- an item's subject: a list item (`-`, `*` or `+`, then a space) with some
  text, optionally ticked (`[ ] ` or `[x] `) and optionally ending in an ID
  comment `<!-- q:7f3a -->`
- an item's body: the lines straight after the subject that are indented
  further than it and aren't list items themselves. Blank lines inside the
  body belong to it when more body follows, as in a markdown list item with
  several paragraphs, and a fenced code block in the body is kept whole.

Everything else becomes a RawLine. A non-blank raw line belongs to the
innermost item indented less than it, so it travels with that item if it
moves. Blank lines belong to the container of the next non-blank line, and
fenced code blocks outside a body are kept whole in the container they open in.
"""

from __future__ import annotations

import re

from .ids import new_id
from .model import (
    Container,
    Document,
    Item,
    Kind,
    RawLine,
    Status,
    indent_width,
    leading_whitespace,
)

ITEM_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[-*+]) (?:\[(?P<box>[ xX])\] )?(?P<rest>.*)$"
)
ID_RE = re.compile(r"[ \t]*<!--[ \t]*q:(?P<id>[A-Za-z0-9_-]+)[ \t]*-->[ \t]*$")
FENCE_RE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})")
# `- - -` and `* * *` are horizontal rules, not items.
RULE_RE = re.compile(r"^[ \t]*([-*_])([ \t]*\1){2,}[ \t]*$")
EMPTY_BOX_RE = re.compile(r"^\[[ xX]\]$")


def parse(text: str) -> Document:
    doc = Document()
    if "\r\n" in text:
        doc.newline = "\r\n"
    lines = text.split(doc.newline)
    if lines[-1] == "":
        lines.pop()
    else:
        doc.trailing_newline = False

    stack: list[Item] = []
    pending_blanks: list[str] = []
    # The item whose body is being read, and a code fence open inside it.
    body_of: Item | None = None
    body_fence: str | None = None
    # A code fence open outside any body, and the container it's in.
    fence: tuple[Container, str] | None = None

    def container() -> Container:
        return stack[-1] if stack else doc

    for line in lines:
        if body_of is not None and body_fence is not None:
            _add_body_line(body_of, line)
            if _closes(line, body_fence):
                body_fence = None
            continue

        if fence is not None:
            fence_container, fence_mark = fence
            fence_container.items.append(RawLine(line))
            if _closes(line, fence_mark):
                fence = None
            continue

        if not line.strip():
            pending_blanks.append(line)
            continue

        width = indent_width(leading_whitespace(line))
        is_item = _match_item(line) is not None

        if body_of is not None:
            if not is_item and width > indent_width(body_of.indent):
                for blank in pending_blanks:
                    _add_body_line(body_of, blank)
                pending_blanks.clear()
                _add_body_line(body_of, line)
                m = FENCE_RE.match(line)
                if m:
                    body_fence = m["fence"]
                continue
            body_of = None

        while stack and indent_width(stack[-1].indent) >= width:
            stack.pop()
        parent = container()
        parent.items.extend(RawLine(b) for b in pending_blanks)
        pending_blanks.clear()

        item = _parse_item(line, parent) if is_item else None
        if item is not None:
            parent.items.append(item)
            stack.append(item)
            body_of = item
            continue

        parent.items.append(RawLine(line))
        m = FENCE_RE.match(line)
        if m:
            fence = (parent, m["fence"])

    doc.items.extend(RawLine(b) for b in pending_blanks)
    _assign_ids(doc)
    return doc


def _closes(line: str, mark: str) -> bool:
    m = FENCE_RE.match(line)
    return bool(
        m
        and m["fence"][0] == mark[0]
        and len(m["fence"]) >= len(mark)
        and not line[m.end() :].strip()
    )


def _match_item(line: str) -> re.Match[str] | None:
    if RULE_RE.match(line):
        return None
    m = ITEM_RE.match(line)
    if m is None:
        return None
    rest = ID_RE.sub("", m["rest"]).strip()
    if not rest or (m["box"] is None and EMPTY_BOX_RE.match(rest)):
        return None
    return m


def _parse_item(line: str, parent: Container) -> Item | None:
    m = _match_item(line)
    if m is None:
        return None
    rest = m["rest"]
    id_match = ID_RE.search(rest)
    item_id = ""
    if id_match:
        item_id = id_match["id"]
        rest = rest[: id_match.start()]
    box = m["box"]
    item = Item(
        item_id,
        rest.strip(),
        parent=parent,
        status=Status.DONE if box in ("x", "X") else Status.OPEN,
        kind=Kind.PLAIN if box is None else Kind.TODO,
        indent=m["indent"],
        marker=m["marker"],
    )
    item.source_subject = line
    item.source_body = []
    return item


def _add_body_line(item: Item, line: str) -> None:
    assert item.source_body is not None
    item.source_body.append(line)
    if not line.strip():
        content = ""
    else:
        if item.body_indent is None:
            # The item's content column (where text starts after `- `), so
            # anything indented beyond it, like code, keeps its indentation.
            column = item.indent + "  "
            item.body_indent = (
                column if line.startswith(column) else leading_whitespace(line)
            )
        indent = item.body_indent
        content = line[len(indent) :] if line.startswith(indent) else line.lstrip(" \t")
    # Straight to the field: the source lines are what's being read.
    item._text = f"{item._text}\n{content}"


def _assign_ids(doc: Document) -> None:
    """Give every item a unique ID, touching only the lines that lack one."""
    items = list(doc.walk())
    taken = {each.id for each in items if each.id}
    seen: set[str] = set()
    for each in items:
        if each.id and each.id not in seen:
            seen.add(each.id)
            continue
        fresh = new_id(taken)
        taken.add(fresh)
        seen.add(fresh)
        assert each.source_subject is not None
        if each.id:
            # A duplicate, usually from copy-paste: swap the ID inside the comment.
            m = ID_RE.search(each.source_subject)
            assert m is not None
            start, end = m.span("id")
            each.source_subject = (
                each.source_subject[:start] + fresh + each.source_subject[end:]
            )
        else:
            each.source_subject = f"{each.source_subject.rstrip()} <!-- q:{fresh} -->"
        each.id = fresh
        doc.ids_assigned = True
    for each in items:
        doc.register(each)
