"""Document → markdown."""

from __future__ import annotations

from .model import Container, Document, Item


def serialise(doc: Document) -> str:
    lines: list[str] = []
    _emit(doc, lines)
    text = doc.newline.join(lines)
    if lines and doc.trailing_newline:
        text += doc.newline
    return text


def _emit(container: Container, out: list[str]) -> None:
    for item in container.items:
        if isinstance(item, Item):
            out.extend(item.own_lines())
            _emit(item, out)
        else:
            out.append(item.text)
