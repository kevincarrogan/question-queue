import pytest

from questionqueue.core import parse
from questionqueue.core.model import Document
from questionqueue.core.ops import mark_answered, next_open

# P has three children; C2 is answered by the time we leave it.
TREE = """\
- ? P <!-- q:p -->
  - ? C1 <!-- q:c1 -->
  - ? C2 <!-- q:c2 -->
  - ? C3 <!-- q:c3 -->
- ? Q <!-- q:q -->
"""


def nxt(doc: Document, from_id: str | None) -> str | None:
    q = next_open(doc, from_id)
    return q.id if q else None


def test_finishes_the_branch_then_returns_to_the_parent() -> None:
    doc = parse(TREE)
    order = []
    current: str | None = "c2"
    while current is not None:
        mark_answered(doc, current)
        current = nxt(doc, current)
        if current:
            order.append(current)
    assert order == ["c3", "c1", "p", "q"]


def test_descendants_come_first() -> None:
    doc = parse(TREE)
    assert nxt(doc, "p") == "c1"


def test_from_none_is_first_open_in_document_order() -> None:
    doc = parse(TREE)
    assert nxt(doc, None) == "p"
    mark_answered(doc, "p")
    assert nxt(doc, None) == "c1"


def test_wraps_round_at_root() -> None:
    doc = parse(TREE)
    for done in ["c1", "c2", "c3"]:
        mark_answered(doc, done)
    assert nxt(doc, "q") == "p"


def test_never_returns_the_current_question() -> None:
    doc = parse("- ? Only <!-- q:only -->\n")
    assert nxt(doc, "only") is None


def test_none_when_everything_is_answered() -> None:
    doc = parse("- ?x A <!-- q:a -->\n  - ?x B <!-- q:b -->\n")
    assert nxt(doc, None) is None
    assert nxt(doc, "b") is None


DEEP = """\
- ? R1 <!-- q:r1 -->
  - ?x X <!-- q:x -->
    - ? X1 <!-- q:x1 -->
      - ? X1a <!-- q:x1a -->
    - ?x X2 <!-- q:x2 -->
      - ? X2a <!-- q:x2a -->
  - ? Y <!-- q:y -->
- ?x R2 <!-- q:r2 -->
  - ? R2a <!-- q:r2a -->
- ? R3 <!-- q:r3 -->
"""


@pytest.mark.parametrize(
    ("from_id", "expected"),
    [
        (None, "r1"),
        ("r1", "x1"),  # pre-order into descendants, skipping answered X
        ("x1", "x1a"),
        ("x1a", "x1"),  # no siblings: back up to the open parent
        ("x2", "x2a"),
        ("x2a", "x1"),  # earlier sibling's subtree before the answered parent
        ("x", "x1"),
        ("y", "x1"),  # earlier siblings (inside answered X) before the parent R1
        ("r2a", "r3"),  # R2 answered, so move across
        ("r3", "r1"),  # wrap round
        ("r2", "r2a"),
    ],
)
def test_deep_tree(from_id: str | None, expected: str) -> None:
    assert nxt(parse(DEEP), from_id) == expected


def test_deep_tree_full_drain() -> None:
    doc = parse(DEEP)
    order = []
    current = nxt(doc, None)
    while current is not None:
        order.append(current)
        mark_answered(doc, current)
        current = nxt(doc, current)
    assert order == ["r1", "x1", "x1a", "x2a", "y", "r2a", "r3"]
