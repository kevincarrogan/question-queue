"""Markdown → Document.

Recognised lines:
- a question: a list item (`-`, `*` or `+`) whose text starts with `? ` or
  `?x `, optionally ending in an ID comment `<!-- q:7f3a -->`
- an answer line: a `>` line directly under a question (or under another
  answer line of the same question), indented further than the question

Everything else becomes a RawLine. A non-blank raw line belongs to the
innermost question indented less than it, so it travels with that question if
the question moves. Blank lines belong to the container of the next non-blank
line, and fenced code blocks are kept whole in the container they open in.
"""

from __future__ import annotations

import re

from .ids import new_id
from .model import (
    Container,
    Document,
    Question,
    RawLine,
    Status,
    indent_width,
)

QUESTION_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[-*+]) \?(?P<x>x?) (?P<rest>.*)$"
)
ID_RE = re.compile(r"[ \t]*<!--[ \t]*q:(?P<id>[A-Za-z0-9_-]+)[ \t]*-->[ \t]*$")
ANSWER_RE = re.compile(r"^(?P<indent>[ \t]*)>(?P<rest>.*)$")
FENCE_RE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})")


def parse(text: str) -> Document:
    doc = Document()
    if "\r\n" in text:
        doc.newline = "\r\n"
    lines = text.split(doc.newline)
    if lines[-1] == "":
        lines.pop()
    else:
        doc.trailing_newline = False

    stack: list[Question] = []
    pending_blanks: list[str] = []
    answer_target: Question | None = None
    fence: tuple[Container, str] | None = None

    def container() -> Container:
        return stack[-1] if stack else doc

    for line in lines:
        if fence is not None:
            fence_container, fence_mark = fence
            fence_container.items.append(RawLine(line))
            m = FENCE_RE.match(line)
            if (
                m
                and m["fence"][0] == fence_mark[0]
                and len(m["fence"]) >= len(fence_mark)
                and not line[m.end() :].strip()
            ):
                fence = None
            continue

        if not line.strip():
            pending_blanks.append(line)
            answer_target = None
            continue

        width = indent_width(line[: len(line) - len(line.lstrip(" \t"))])

        if answer_target is not None:
            m = ANSWER_RE.match(line)
            if m and indent_width(m["indent"]) > indent_width(answer_target.indent):
                assert answer_target.source_answer is not None
                if answer_target.answer_indent is None:
                    answer_target.answer_indent = m["indent"]
                answer_target.source_answer.append(line)
                rest = m["rest"]
                content = rest[1:] if rest.startswith(" ") else rest
                existing = answer_target.answer
                answer_target._answer = (
                    content
                    if not answer_target.source_answer[:-1]
                    else f"{existing}\n{content}"
                )
                continue
            answer_target = None

        while stack and indent_width(stack[-1].indent) >= width:
            stack.pop()
        parent = container()
        parent.items.extend(RawLine(b) for b in pending_blanks)
        pending_blanks.clear()

        question = _parse_question(line, parent)
        if question is not None:
            parent.items.append(question)
            stack.append(question)
            answer_target = question
            continue

        parent.items.append(RawLine(line))
        m = FENCE_RE.match(line)
        if m:
            fence = (parent, m["fence"])

    doc.items.extend(RawLine(b) for b in pending_blanks)
    _assign_ids(doc)
    return doc


def _parse_question(line: str, parent: Container) -> Question | None:
    m = QUESTION_RE.match(line)
    if m is None:
        return None
    rest = m["rest"]
    id_match = ID_RE.search(rest)
    question_id = ""
    if id_match:
        question_id = id_match["id"]
        rest = rest[: id_match.start()]
    text = rest.rstrip()
    if not text.strip():
        return None
    question = Question(
        question_id,
        text,
        parent=parent,
        status=Status.ANSWERED if m["x"] else Status.OPEN,
        indent=m["indent"],
        marker=m["marker"],
    )
    question.source_line = line
    question.source_answer = []
    return question


def _assign_ids(doc: Document) -> None:
    """Give every question a unique ID, touching only the lines that lack one."""
    questions = list(doc.walk())
    taken = {q.id for q in questions if q.id}
    seen: set[str] = set()
    for q in questions:
        if q.id and q.id not in seen:
            seen.add(q.id)
            continue
        fresh = new_id(taken)
        taken.add(fresh)
        seen.add(fresh)
        assert q.source_line is not None
        if q.id:
            # A duplicate, usually from copy-paste: swap the ID inside the comment.
            m = ID_RE.search(q.source_line)
            assert m is not None
            start, end = m.span("id")
            q.source_line = q.source_line[:start] + fresh + q.source_line[end:]
        else:
            q.source_line = f"{q.source_line.rstrip()} <!-- q:{fresh} -->"
        q.id = fresh
        doc.ids_assigned = True
    for q in questions:
        doc.register(q)
