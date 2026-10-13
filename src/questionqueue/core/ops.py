"""Tree operations. Every operation takes and returns IDs or Questions, never positions in the file."""

from __future__ import annotations

from .errors import InvalidMove
from .ids import new_id
from .model import (
    INDENT_STEP,
    Container,
    Document,
    Question,
    Status,
    indent_width,
)


def add(
    doc: Document,
    text: str,
    parent_id: str | None = None,
    as_sibling_of: str | None = None,
) -> Question:
    """Add an open question: last child of `parent_id` (the root if None), or straight after `as_sibling_of`."""
    if parent_id is not None and as_sibling_of is not None:
        raise ValueError("pass parent_id or as_sibling_of, not both")
    _check_text(text)
    if as_sibling_of is not None:
        sibling = doc.get(as_sibling_of)
        container = sibling.parent
    else:
        container = doc.get(parent_id) if parent_id is not None else doc
    question = Question(new_id(doc.ids()), text, parent=container)
    question.indent = _child_indent(container)
    if as_sibling_of is not None:
        container.items.insert(container.items.index(sibling) + 1, question)
    else:
        _insert_at(container, question, len(container.children))
    doc.register(question)
    return question


def answer(doc: Document, question_id: str, text: str) -> Question:
    """Replace the answer, verbatim."""
    question = doc.get(question_id)
    question.answer = text
    return question


def mark_answered(doc: Document, question_id: str) -> Question:
    question = doc.get(question_id)
    question.status = Status.ANSWERED
    return question


def reopen(doc: Document, question_id: str) -> Question:
    question = doc.get(question_id)
    question.status = Status.OPEN
    return question


def set_text(doc: Document, question_id: str, text: str) -> Question:
    _check_text(text)
    question = doc.get(question_id)
    question.text = text
    return question


def move(
    doc: Document,
    question_id: str,
    new_parent_id: str | None,
    index: int | None = None,
) -> Question:
    """Move a question and its subtree under `new_parent_id` (the root if None).

    `index` is a position among the new parent's child questions, counted
    after the question is taken out of its old place. None means last.
    """
    question = doc.get(question_id)
    new_parent: Container = doc if new_parent_id is None else doc.get(new_parent_id)
    if isinstance(new_parent, Question) and (
        new_parent is question or question in new_parent.ancestors()
    ):
        raise InvalidMove(f"can't move {question_id} inside itself")

    old_parent = question.parent
    old_items = list(old_parent.items)
    old_parent.items.remove(question)
    siblings = new_parent.children
    if index is None:
        index = len(siblings)
    if not 0 <= index <= len(siblings):
        old_parent.items[:] = old_items
        raise IndexError(f"index {index} out of range for {len(siblings)} siblings")

    if new_parent is not old_parent:
        target = indent_width(_child_indent(new_parent))
        question.shift(target - indent_width(question.indent))
        question.parent = new_parent
    _insert_at(new_parent, question, index)
    return question


def reorder(doc: Document, question_id: str, index: int) -> Question:
    """Move a question to `index` among its own siblings."""
    return move(doc, question_id, doc.get(question_id).parent_id, index)


def indent(doc: Document, question_id: str) -> Question:
    """Make a question the last child of its previous sibling."""
    question = doc.get(question_id)
    siblings = question.parent.children
    position = siblings.index(question)
    if position == 0:
        raise InvalidMove("no previous sibling to indent under")
    return move(doc, question_id, siblings[position - 1].id)


def outdent(doc: Document, question_id: str) -> Question:
    """Make a question the next sibling of its parent."""
    question = doc.get(question_id)
    parent = question.parent
    if not isinstance(parent, Question):
        raise InvalidMove("already at the root")
    grandparent = parent.parent
    position = grandparent.children.index(parent)
    return move(doc, question_id, parent.parent_id, position + 1)


def delete(doc: Document, question_id: str) -> Question:
    """Remove a question with its answer, its descendants and any lines nested under it."""
    question = doc.get(question_id)
    question.parent.items.remove(question)
    doc.unregister(question)
    return question


def trail(doc: Document, question_id: str) -> list[Question]:
    """The ancestors of a question, root-most first."""
    return doc.get(question_id).ancestors()


def next_open(doc: Document, from_id: str | None = None) -> Question | None:
    """The next open question, finishing the current branch before moving across.

    From the current question, look at its own descendants first. Then widen
    the scope one ancestor at a time: within each ancestor, look at the
    siblings after us, then the ones before us, then the ancestor itself. At
    the root this wraps round the whole document. The current question is never
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
        if not isinstance(container, Question):
            return None
        if container.is_open:
            return container
        node = container


def _check_text(text: str) -> None:
    if not text.strip():
        raise ValueError("question text can't be empty")
    if "\n" in text or "\r" in text:
        raise ValueError("question text must be a single line")


def _child_indent(container: Container) -> str:
    """The indent a new child of `container` should get: match its siblings if it has any."""
    existing = container.children
    if existing:
        return existing[0].indent
    if isinstance(container, Question):
        return container.indent + INDENT_STEP
    return ""


def _insert_at(container: Container, question: Question, index: int) -> None:
    """Insert before the `index`-th child question, or after the last one."""
    children = container.children
    if index < len(children):
        container.items.insert(container.items.index(children[index]), question)
    elif children:
        container.items.insert(container.items.index(children[-1]) + 1, question)
    else:
        container.items.append(question)
