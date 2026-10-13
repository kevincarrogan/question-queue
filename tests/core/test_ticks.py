"""Ticks cascade: down to the boxes under an item, and up to the boxes above it."""

import pytest

from questionqueue.core import Kind, Status, ops, parse, serialise
from questionqueue.core.model import Document

TREE = """\
- [ ] Pack <!-- q:pack -->
  - [ ] Tent <!-- q:tent -->
  - [ ] Stove <!-- q:stov -->
    - [ ] Gas <!-- q:gas0 -->
    - [ ] Lighter <!-- q:lite -->
  - Ask about a fire ban? <!-- q:fire -->
    - [ ] Ring the ranger <!-- q:rang -->
- [ ] Go <!-- q:go00 -->
"""


@pytest.fixture
def doc() -> Document:
    return parse(TREE)


def done(doc: Document, item_id: str) -> bool:
    return doc.get(item_id).status is Status.DONE


def test_ticking_the_last_box_ticks_its_parents(doc: Document) -> None:
    ops.mark_done(doc, "gas0")
    assert not done(doc, "stov")
    assert doc.get("stov").mixed
    assert doc.get("pack").mixed  # mixed below means mixed here
    ops.mark_done(doc, "lite")
    assert done(doc, "stov")
    assert not doc.get("stov").mixed
    ops.mark_done(doc, "tent")
    assert done(doc, "pack")


def test_unticking_one_box_unticks_its_parents(doc: Document) -> None:
    ops.mark_done(doc, "pack")
    ops.reopen(doc, "lite")
    assert not done(doc, "stov")
    assert not done(doc, "pack")
    assert doc.get("pack").mixed
    assert "- [ ] Pack" in serialise(doc)  # in the file it's simply not done


def test_ticking_a_parent_ticks_the_boxes_under_it(doc: Document) -> None:
    ops.mark_done(doc, "pack")
    assert all(done(doc, i) for i in ("tent", "stov", "gas0", "lite"))
    ops.reopen(doc, "pack")
    assert not any(done(doc, i) for i in ("tent", "stov", "gas0", "lite"))


def test_a_plain_item_stops_the_cascade(doc: Document) -> None:
    ops.mark_done(doc, "pack")
    assert not done(doc, "rang")  # under a plain item, so not one of Pack's boxes
    ops.reopen(doc, "rang")
    assert done(doc, "pack")


def test_adding_an_open_box_unticks_its_parent(doc: Document) -> None:
    ops.mark_done(doc, "stov")
    ops.add(doc, "Matches", parent_id="stov", kind=Kind.TODO)
    assert not done(doc, "stov")
    assert doc.get("stov").mixed


def test_moving_and_deleting_settle_both_places(doc: Document) -> None:
    ops.mark_done(doc, "gas0")
    ops.move(doc, "lite", "go00")
    assert done(doc, "stov")  # only Gas left, and it's ticked
    assert not done(doc, "go00")
    ops.mark_done(doc, "tent")
    assert done(doc, "pack")
    ops.delete(doc, "gas0")
    assert done(doc, "stov")  # no boxes left under it: it keeps its tick


def test_boxes_come_and_go(doc: Document) -> None:
    ops.mark_done(doc, "tent")
    ops.mark_done(doc, "stov")
    ops.set_kind(doc, "fire", Kind.TODO)  # now Ring the ranger counts, and isn't done
    assert not done(doc, "fire")
    assert doc.get("pack").mixed
    ops.set_kind(doc, "fire", Kind.PLAIN)
    assert done(doc, "pack")


def test_a_file_that_already_agrees_is_left_as_it_is(doc: Document) -> None:
    ops.mark_done(doc, "go00")
    assert serialise(doc) == TREE.replace("- [ ] Go", "- [x] Go")
