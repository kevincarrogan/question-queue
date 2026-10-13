import pytest

from questionqueue.core import (
    InvalidMove,
    ItemNotFound,
    Kind,
    Status,
    ops,
    parse,
    serialise,
)
from questionqueue.core.model import Document

TREE = """\
# Heading

- A <!-- q:aaaa -->
  > answer A
  - A1 <!-- q:aa01 -->
    note under A1
  - A2 <!-- q:aa02 -->
- B <!-- q:bbbb -->

Closing prose.
"""


@pytest.fixture
def doc() -> Document:
    return parse(TREE)


def child_ids(doc: Document, item_id: str | None) -> list[str]:
    container = doc if item_id is None else doc.get(item_id)
    return [q.id for q in container.children]


def test_add_child_goes_last_under_parent(doc: Document) -> None:
    q = ops.add(doc, "A3", parent_id="aaaa")
    assert child_ids(doc, "aaaa") == ["aa01", "aa02", q.id]
    assert q.parent is doc.get("aaaa")
    assert q.status is Status.OPEN
    assert f"  - A3 <!-- q:{q.id} -->\n- B" in serialise(doc)


def test_add_child_to_leaf_indents_two_more(doc: Document) -> None:
    q = ops.add(doc, "B1", parent_id="bbbb")
    assert f"- B <!-- q:bbbb -->\n  - B1 <!-- q:{q.id} -->\n" in serialise(doc)


def test_add_at_root_goes_after_last_root_item_not_after_prose(
    doc: Document,
) -> None:
    q = ops.add(doc, "C")
    assert child_ids(doc, None) == ["aaaa", "bbbb", q.id]
    assert serialise(doc).endswith(
        f"- B <!-- q:bbbb -->\n- C <!-- q:{q.id} -->\n\nClosing prose.\n"
    )


def test_add_to_empty_document() -> None:
    doc = parse("")
    q = ops.add(doc, "First")
    assert serialise(doc) == f"- First <!-- q:{q.id} -->\n"


def test_add_as_sibling_goes_straight_after(doc: Document) -> None:
    q = ops.add(doc, "A1b", as_sibling_of="aa01")
    assert child_ids(doc, "aaaa") == ["aa01", q.id, "aa02"]
    # After A1's whole subtree, including the note under it.
    assert f"    note under A1\n  - A1b <!-- q:{q.id} -->\n" in serialise(doc)


def test_add_matches_sibling_indent_style() -> None:
    doc = parse("- P <!-- q:pppp -->\n    - C <!-- q:cccc -->\n")
    q = ops.add(doc, "D", parent_id="pppp")
    assert f"    - D <!-- q:{q.id} -->" in serialise(doc)


def test_add_rejects_bad_input(doc: Document) -> None:
    with pytest.raises(ValueError):
        ops.add(doc, "   ")
    with pytest.raises(ValueError):
        ops.add(doc, "\nthe first line is the subject, so it can't be blank")
    with pytest.raises(ValueError):
        ops.add(doc, "x", parent_id="aaaa", as_sibling_of="bbbb")
    with pytest.raises(ItemNotFound):
        ops.add(doc, "x", parent_id="nope")


def test_new_ids_are_unique(doc: Document) -> None:
    ids = {ops.add(doc, f"q{i}").id for i in range(200)}
    assert len(ids) == 200
    assert not ids & {"aaaa", "aa01", "aa02", "bbbb"}


def test_an_item_can_have_a_body(doc: Document) -> None:
    q = ops.add(
        doc, "Where is the function to do X?\nfoo/bar/core.py:30", parent_id="bbbb"
    )
    assert (q.subject, q.body) == (
        "Where is the function to do X?",
        "foo/bar/core.py:30",
    )
    assert (
        f"- B <!-- q:bbbb -->\n  - Where is the function to do X? <!-- q:{q.id} -->\n"
        "    foo/bar/core.py:30\n"
    ) in serialise(doc)


def test_body_is_verbatim(doc: Document) -> None:
    text = "B\n  My own words,  spaced  oddly.\n\nSecond para. \n```\n  code\n\n```"
    ops.set_text(doc, "bbbb", text)
    assert doc.get("bbbb").text == text
    assert parse(serialise(doc)).get("bbbb").text == text


def test_trailing_blank_lines_are_dropped(doc: Document) -> None:
    ops.set_text(doc, "bbbb", "  B  \nbody\n\n  \n")
    assert doc.get("bbbb").text == "B\nbody"


def test_dropping_the_body_removes_its_lines(doc: Document) -> None:
    ops.set_text(doc, "aaaa", "A")
    assert "answer A" not in serialise(doc)
    assert "  - A1 <!-- q:aa01 -->\n    note under A1" in serialise(doc)


def test_mark_done_gives_a_plain_item_a_box(doc: Document) -> None:
    ops.mark_done(doc, "aa02")
    assert "  - [x] A2 <!-- q:aa02 -->" in serialise(doc)
    ops.reopen(doc, "aa02")
    assert "  - [ ] A2 <!-- q:aa02 -->" in serialise(doc)
    ops.set_kind(doc, "aa02", Kind.PLAIN)
    assert serialise(doc) == TREE


def test_a_plain_item_is_never_done(doc: Document) -> None:
    ops.mark_done(doc, "aa02")
    ops.set_kind(doc, "aa02", Kind.PLAIN)
    assert doc.get("aa02").status is Status.OPEN


def test_set_text(doc: Document) -> None:
    ops.set_text(doc, "bbbb", "B renamed")
    assert "- B renamed <!-- q:bbbb -->" in serialise(doc)


def test_move_reindents_whole_subtree(doc: Document) -> None:
    ops.move(doc, "aaaa", "bbbb")
    assert doc.get("aaaa").parent is doc.get("bbbb")
    assert (
        serialise(doc)
        == """\
# Heading

- B <!-- q:bbbb -->
  - A <!-- q:aaaa -->
    > answer A
    - A1 <!-- q:aa01 -->
      note under A1
    - A2 <!-- q:aa02 -->

Closing prose.
"""
    )


def test_move_to_root_outdents(doc: Document) -> None:
    ops.move(doc, "aa01", None, index=0)
    assert child_ids(doc, None) == ["aa01", "aaaa", "bbbb"]
    assert serialise(doc).startswith(
        "# Heading\n\n- A1 <!-- q:aa01 -->\n  note under A1\n- A"
    )


def test_move_rejects_cycles(doc: Document) -> None:
    with pytest.raises(InvalidMove):
        ops.move(doc, "aaaa", "aaaa")
    with pytest.raises(InvalidMove):
        ops.move(doc, "aaaa", "aa01")


def test_move_rejects_bad_index_without_side_effects(doc: Document) -> None:
    with pytest.raises(IndexError):
        ops.move(doc, "aa01", "bbbb", index=5)
    assert serialise(doc) == TREE


def test_reorder(doc: Document) -> None:
    ops.reorder(doc, "aa02", 0)
    assert child_ids(doc, "aaaa") == ["aa02", "aa01"]
    ops.reorder(doc, "aa02", 1)
    assert serialise(doc) == TREE


def test_indent_and_outdent(doc: Document) -> None:
    ops.indent(doc, "bbbb")
    assert doc.get("bbbb").parent is doc.get("aaaa")
    assert child_ids(doc, "aaaa") == ["aa01", "aa02", "bbbb"]
    ops.outdent(doc, "bbbb")
    assert serialise(doc) == TREE
    with pytest.raises(InvalidMove):
        ops.indent(doc, "aaaa")
    with pytest.raises(InvalidMove):
        ops.outdent(doc, "aaaa")


def test_delete_removes_subtree_and_its_lines(doc: Document) -> None:
    ops.delete(doc, "aaaa")
    assert serialise(doc) == "# Heading\n\n- B <!-- q:bbbb -->\n\nClosing prose.\n"
    for gone in ["aaaa", "aa01", "aa02"]:
        assert gone not in doc
    with pytest.raises(ItemNotFound):
        ops.delete(doc, "aaaa")


def test_trail(doc: Document) -> None:
    q = ops.add(doc, "deep", parent_id="aa01")
    assert [a.id for a in ops.trail(doc, q.id)] == ["aaaa", "aa01"]
    assert ops.trail(doc, "aaaa") == []
