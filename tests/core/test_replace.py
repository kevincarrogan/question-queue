import pytest

from questionqueue.core import ops, parse, serialise

TEXT = """\
- Pack the tent <!-- q:a -->
  tent pegs too, see src/kit.py:3
- Book the tent pitch <!-- q:b -->
- tent <!-- q:c -->
"""


def test_replaces_in_the_items_given() -> None:
    doc = parse(TEXT)
    changed = ops.replace(doc, "tent", "van", ["a", "b"])
    assert [i.id for i in changed] == ["a", "b"]
    assert doc.get("a").text == "Pack the van\nvan pegs too, see src/kit.py:3"
    assert doc.get("c").text == "tent"


def test_the_text_is_literal_not_a_pattern() -> None:
    doc = parse(TEXT)
    ops.replace(doc, "src/kit.py", "lib/kit.py", ["a"])
    assert doc.get("a").body == "tent pegs too, see lib/kit.py:3"
    assert ops.replace(doc, ".*", "x", ["a", "b", "c"]) == []


def test_a_blank_first_line_is_left_alone() -> None:
    doc = parse(TEXT)
    assert ops.replace(doc, "tent", "", ["c"]) == []
    assert serialise(doc) == TEXT


def test_nothing_to_replace() -> None:
    doc = parse(TEXT)
    assert ops.replace(doc, "stove", "x", ["a", "b", "c"]) == []
    with pytest.raises(ValueError):
        ops.replace(doc, "", "x", ["a"])
    assert serialise(doc) == TEXT


def test_first_on_each_line_unless_every() -> None:
    doc = parse("- a a <!-- q:x -->\n  a a\n")
    ops.replace(doc, "a", "b", ["x"])
    assert doc.get("x").text == "b a\nb a"
    ops.replace(doc, "a", "b", ["x"], every=True)
    assert doc.get("x").text == "b b\nb b"


def test_ignore_case() -> None:
    doc = parse("- Tent TENT tent <!-- q:x -->\n")
    ops.replace(doc, "tent", "van", ["x"], every=True)
    assert doc.get("x").text == "Tent TENT van"
    ops.replace(doc, "tent", "van", ["x"], every=True, ignore_case=True)
    assert doc.get("x").text == "van van van"
