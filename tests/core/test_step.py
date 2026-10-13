"""Moving an item one row at a time through the outline as it's shown."""

import pytest

from questionqueue.core import InvalidMove, ops, parse
from questionqueue.core.model import Document

TREE = """\
- A <!-- q:a -->
  - A1 <!-- q:a1 -->
  - A2 <!-- q:a2 -->
- B <!-- q:b -->
- C <!-- q:c -->
  - C1 <!-- q:c1 -->
"""


def order(doc: Document) -> list[str]:
    return [f"{'  ' * i.depth}{i.id}" for i in doc.walk()]


def test_down_past_a_sibling() -> None:
    doc = parse(TREE)
    ops.step(doc, "b", down=True)
    # B goes past C, which has children showing, so it becomes C's first child.
    assert order(doc) == ["a", "  a1", "  a2", "c", "  b", "  c1"]


def test_down_out_of_a_branch() -> None:
    doc = parse(TREE)
    ops.step(doc, "a2", down=True)
    # Past B, which has no children: A2 becomes B's next sibling, at the top level.
    assert order(doc) == ["a", "  a1", "b", "a2", "c", "  c1"]


def test_up_into_a_branch() -> None:
    doc = parse(TREE)
    ops.step(doc, "b", down=False)
    # Above B is A2, so B goes just before it, inside A.
    assert order(doc) == ["a", "  a1", "  b", "  a2", "c", "  c1"]


def test_up_out_of_a_branch() -> None:
    doc = parse(TREE)
    ops.step(doc, "a1", down=False)
    assert order(doc) == ["a1", "a", "  a2", "b", "c", "  c1"]


def test_the_subtree_travels() -> None:
    doc = parse(TREE)
    ops.step(doc, "a", down=True)
    assert order(doc) == ["b", "a", "  a1", "  a2", "c", "  c1"]


def test_folded_branches_are_stepped_over() -> None:
    doc = parse(TREE)
    ops.step(doc, "b", down=True, folded={"c"})
    assert order(doc) == ["a", "  a1", "  a2", "c", "  c1", "b"]
    ops.step(doc, "b", down=False, folded={"a", "c"})
    assert order(doc) == ["a", "  a1", "  a2", "b", "c", "  c1"]


def test_ends_raise() -> None:
    doc = parse(TREE)
    with pytest.raises(InvalidMove):
        ops.step(doc, "a", down=False)
    with pytest.raises(InvalidMove):
        ops.step(doc, "c", down=True)


def test_visible_leaves_out_folded_children() -> None:
    doc = parse(TREE)
    assert [i.id for i in ops.visible(doc, {"a"})] == ["a", "b", "c", "c1"]
