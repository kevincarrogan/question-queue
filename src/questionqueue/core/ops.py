"""Tree operations. Every operation takes IDs and returns Items, never positions in the file."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable

from .errors import InvalidMove
from .ids import new_id
from .model import (
    INDENT_STEP,
    Container,
    Document,
    Item,
    Kind,
    Status,
    indent_width,
)


def add(
    doc: Document,
    text: str,
    parent_id: str | None = None,
    as_sibling_of: str | None = None,
    kind: Kind = Kind.PLAIN,
) -> Item:
    """Add an open item: last child of `parent_id` (the root if None), or straight after `as_sibling_of`."""
    if parent_id is not None and as_sibling_of is not None:
        raise ValueError("pass parent_id or as_sibling_of, not both")
    text = _clean_text(text)
    if as_sibling_of is not None:
        sibling = doc.get(as_sibling_of)
        container = sibling.parent
    else:
        container = doc.get(parent_id) if parent_id is not None else doc
    item = Item(new_id(doc.ids()), text, parent=container, kind=kind)
    item.indent = _child_indent(container)
    if as_sibling_of is not None:
        container.items.insert(container.items.index(sibling) + 1, item)
    else:
        _insert_at(container, item, len(container.children))
    doc.register(item)
    _settle(container)
    return item


def set_text(doc: Document, item_id: str, text: str) -> Item:
    """Replace the whole text: the subject line, then any body lines."""
    item = doc.get(item_id)
    item.text = _clean_text(text)
    return item


def set_kind(doc: Document, item_id: str, kind: Kind) -> Item:
    """Give an item a box to tick, or take it away. A plain item is never done."""
    item = doc.get(item_id)
    item.kind = kind
    if kind is Kind.PLAIN:
        item.status = Status.OPEN
    _settle(item if kind is Kind.TODO else item.parent)
    return item


def mark_done(doc: Document, item_id: str) -> Item:
    """Tick an item, giving it a box first if it's plain.

    Ticks cascade both ways. Down: the boxes under it are ticked too. Up: an
    item with boxes under it is ticked exactly when all of them are, so its
    parent may now be done. Only boxes count; a plain item stops the cascade.
    """
    item = doc.get(item_id)
    item.kind = Kind.TODO
    _tick(item, Status.DONE)
    _settle(item.parent)
    return item


def reopen(doc: Document, item_id: str) -> Item:
    """Untick an item and the boxes under it, and so its ticked parents."""
    item = doc.get(item_id)
    _tick(item, Status.OPEN)
    _settle(item.parent)
    return item


def move(
    doc: Document,
    item_id: str,
    new_parent_id: str | None,
    index: int | None = None,
) -> Item:
    """Move a item and its subtree under `new_parent_id` (the root if None).

    `index` is a position among the new parent's child items, counted
    after the item is taken out of its old place. None means last.
    """
    item = doc.get(item_id)
    new_parent: Container = doc if new_parent_id is None else doc.get(new_parent_id)
    if isinstance(new_parent, Item) and (
        new_parent is item or item in new_parent.ancestors()
    ):
        raise InvalidMove(f"can't move {item_id} inside itself")

    old_parent = item.parent
    old_items = list(old_parent.items)
    old_parent.items.remove(item)
    siblings = new_parent.children
    if index is None:
        index = len(siblings)
    if not 0 <= index <= len(siblings):
        old_parent.items[:] = old_items
        raise IndexError(f"index {index} out of range for {len(siblings)} siblings")

    if new_parent is not old_parent:
        target = indent_width(_child_indent(new_parent))
        item.shift(target - indent_width(item.indent))
        item.parent = new_parent
    _insert_at(new_parent, item, index)
    _settle(old_parent)
    _settle(new_parent)
    return item


def reorder(doc: Document, item_id: str, index: int) -> Item:
    """Move a item to `index` among its own siblings."""
    return move(doc, item_id, doc.get(item_id).parent_id, index)


def replaced(
    text: str, old: str, new: str, *, every: bool = False, ignore_case: bool = False
) -> str:
    """`text` with `old` replaced by `new`, as `replace` does it."""
    if not old:
        raise ValueError("nothing to replace")
    pattern = re.compile(re.escape(old), re.IGNORECASE if ignore_case else 0)
    count = 0 if every else 1
    return "\n".join(
        pattern.sub(lambda _: new, line, count=count) for line in text.split("\n")
    )


def replace(
    doc: Document,
    old: str,
    new: str,
    item_ids: Iterable[str],
    *,
    every: bool = False,
    ignore_case: bool = False,
) -> list[Item]:
    """Replace `old` with `new` in each item's text, like vim's `s/old/new/`:
    the first occurrence on each line, or every one with `every` (vim's g),
    ignoring case with `ignore_case` (vim's i). The text is literal, not a
    pattern. Returns the items that changed; an item whose first line would
    end up blank is left alone."""
    changed: list[Item] = []
    for item_id in item_ids:
        item = doc.get(item_id)
        text = replaced(item.text, old, new, every=every, ignore_case=ignore_case)
        if text == item.text:
            continue
        try:
            set_text(doc, item_id, text)
        except ValueError:
            continue
        changed.append(item)
    return changed


def visible(doc: Document, folded: Collection[str] = ()) -> list[Item]:
    """Items in outline order, leaving out everything under a folded item."""
    shown: list[Item] = []

    def walk(container: Container) -> None:
        for child in container.children:
            shown.append(child)
            if child.id not in folded:
                walk(child)

    walk(doc)
    return shown


def step(
    doc: Document, item_id: str, *, down: bool, folded: Collection[str] = ()
) -> Item:
    """Move an item (with everything under it) one row up or down the outline
    as it's shown, so it can travel into and out of branches.

    Down: past the next row below it. If that row has children showing, the
    item becomes its first child; otherwise its next sibling. Up: to just
    before the row above it, as that row's previous sibling. Raises
    InvalidMove at either end.
    """
    item = doc.get(item_id)
    rows = visible(doc, folded)
    subtree = {each.id for each in item.walk()}
    others = [row for row in rows if row.id not in subtree]
    position = rows.index(item)
    if down:
        below = [row for row in rows[position:] if row.id not in subtree]
        if not below:
            raise InvalidMove("already at the bottom")
        target = below[0]
        if target.children and target.id not in folded:
            return move(doc, item_id, target.id, 0)
        siblings = [c for c in target.parent.children if c is not item]
        return move(doc, item_id, target.parent_id, siblings.index(target) + 1)
    above = [row for row in others if rows.index(row) < position]
    if not above:
        raise InvalidMove("already at the top")
    target = above[-1]
    siblings = [c for c in target.parent.children if c is not item]
    return move(doc, item_id, target.parent_id, siblings.index(target))


def indent(doc: Document, item_id: str) -> Item:
    """Make a item the last child of its previous sibling."""
    item = doc.get(item_id)
    siblings = item.parent.children
    position = siblings.index(item)
    if position == 0:
        raise InvalidMove("no previous sibling to indent under")
    return move(doc, item_id, siblings[position - 1].id)


def outdent(doc: Document, item_id: str) -> Item:
    """Make a item the next sibling of its parent."""
    item = doc.get(item_id)
    parent = item.parent
    if not isinstance(parent, Item):
        raise InvalidMove("already at the root")
    grandparent = parent.parent
    position = grandparent.children.index(parent)
    return move(doc, item_id, parent.parent_id, position + 1)


def delete(doc: Document, item_id: str) -> Item:
    """Remove a item with its body, its descendants and any lines nested under it."""
    item = doc.get(item_id)
    item.parent.items.remove(item)
    doc.unregister(item)
    _settle(item.parent)
    return item


def trail(doc: Document, item_id: str) -> list[Item]:
    """The ancestors of a item, root-most first."""
    return doc.get(item_id).ancestors()


def next_open(doc: Document, from_id: str | None = None) -> Item | None:
    """The next open item, finishing the current branch before moving across.

    From the current item, look at its own descendants first. Then widen
    the scope one ancestor at a time: within each ancestor, look at the
    siblings after us, then the ones before us, then the ancestor itself. At
    the root this wraps round the whole document. The current item is never
    returned.
    """
    if from_id is None:
        return next((q for q in doc.walk() if q.is_open), None)

    node = doc.get(from_id)
    for q in node.descendants():
        if q.is_open:
            return q
    while True:
        container = node.parent
        siblings = container.children
        position = siblings.index(node)
        for sibling in siblings[position + 1 :] + siblings[:position]:
            for q in sibling.walk():
                if q.is_open:
                    return q
        if not isinstance(container, Item):
            return None
        if container.is_open:
            return container
        node = container


def _tick(item: Item, status: Status) -> None:
    item.status = status
    for child in item.ticks:
        _tick(child, status)


def _settle(node: Container) -> None:
    """After the boxes under `node` change, make it and the boxes above it
    agree with them: ticked when every box under it is. Climbs until a
    plain item (or the root), which has no say."""
    while isinstance(node, Item) and node.kind is Kind.TODO:
        if node.ticks:
            done = all(not t.is_open for t in node.ticks)
            node.status = Status.DONE if done else Status.OPEN
        node = node.parent


def _clean_text(text: str) -> str:
    """Trailing blank lines dropped; the subject (first line) can't be empty."""
    if "\r" in text:
        raise ValueError("item text can't contain carriage returns")
    lines = text.split("\n")
    while len(lines) > 1 and not lines[-1].strip():
        lines.pop()
    lines[0] = lines[0].strip()
    if not lines[0]:
        raise ValueError("an item's first line can't be empty")
    return "\n".join(lines)


def _child_indent(container: Container) -> str:
    """The indent a new child of `container` should get: match its siblings if it has any."""
    existing = container.children
    if existing:
        return existing[0].indent
    if isinstance(container, Item):
        return container.indent + INDENT_STEP
    return ""


def _insert_at(container: Container, item: Item, index: int) -> None:
    """Insert before the `index`-th child item, or after the last one."""
    children = container.children
    if index < len(children):
        container.items.insert(container.items.index(children[index]), item)
    elif children:
        container.items.insert(container.items.index(children[-1]) + 1, item)
    else:
        container.items.append(item)
