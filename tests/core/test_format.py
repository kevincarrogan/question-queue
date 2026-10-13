"""The file format: what's an item, what's its body, and writing it back unchanged."""

import re
from pathlib import Path

import pytest

from questionqueue.core import Kind, Status, ops, parse, serialise

FIXTURES = Path(__file__).parent.parent / "fixtures"
ID = re.compile(r" <!-- q:\w+ -->")


def read(name: str) -> str:
    return (FIXTURES / name).read_bytes().decode()


@pytest.mark.parametrize("name", ["spec_example.md", "crlf_tabs.md"])
def test_files_with_ids_round_trip_byte_for_byte(name: str) -> None:
    text = read(name)
    assert serialise(parse(text)) == text


@pytest.mark.parametrize("name", ["messy.md", "missing_ids.md"])
def test_adding_ids_is_the_only_change(name: str) -> None:
    text = read(name)
    doc = parse(text)
    assert doc.ids_assigned
    out = serialise(doc)
    before, after = text.split("\n"), out.split("\n")
    assert len(before) == len(after)
    for old, new in zip(before, after, strict=True):
        if old != new:
            # An ID added at the end (trailing spaces trimmed first), or a
            # duplicate ID replaced.
            assert ID.sub("", new) == ID.sub("", old).rstrip()
    # And it's stable from then on.
    assert serialise(parse(out)) == out


def test_an_item_is_any_bullet_with_text() -> None:
    doc = parse(
        "- plain\n* star\n+ plus\n- [ ] open box\n- [x] ticked\n- [X] ticked too\n"
    )
    assert [(i.subject, i.kind, i.status) for i in doc.walk()] == [
        ("plain", Kind.PLAIN, Status.OPEN),
        ("star", Kind.PLAIN, Status.OPEN),
        ("plus", Kind.PLAIN, Status.OPEN),
        ("open box", Kind.TODO, Status.OPEN),
        ("ticked", Kind.TODO, Status.DONE),
        ("ticked too", Kind.TODO, Status.DONE),
    ]


@pytest.mark.parametrize(
    "line",
    [
        "-",
        "- ",
        "-no space",
        "- [ ]",
        "- [ ] ",
        "- [x]",
        "---",
        "- - -",
        "* * *",
        "1. numbered",
    ],
)
def test_not_items(line: str) -> None:
    doc = parse(line + "\n")
    assert len(doc) == 0
    assert serialise(doc) == line + "\n"


def test_the_body_is_the_indented_lines_under_the_subject() -> None:
    doc = parse(
        "- Where is the function to do X? <!-- q:aaaa -->\n"
        "  foo/bar/core.py:30\n"
        "  and the tests are next to it\n"
        "  - A child, not body <!-- q:bbbb -->\n"
        "    its body\n"
        "  Back at the parent's level, after a child: not body.\n"
    )
    a, b = doc.get("aaaa"), doc.get("bbbb")
    assert a.subject == "Where is the function to do X?"
    assert a.body == "foo/bar/core.py:30\nand the tests are next to it"
    assert b.parent is a
    assert b.body == "its body"
    assert "Back at" not in a.text


def test_a_body_can_have_paragraphs_and_code() -> None:
    text = (
        "- Item <!-- q:aaaa -->\n"
        "  First paragraph.\n"
        "\n"
        "  Second paragraph.\n"
        "  ```\n"
        "  - not an item, it's code\n"
        "\n"
        "      indented code\n"
        "  ```\n"
        "\n"
        "- Next <!-- q:bbbb -->\n"
    )
    doc = parse(text)
    assert doc.get("aaaa").body == (
        "First paragraph.\n\nSecond paragraph.\n```\n"
        "- not an item, it's code\n\n    indented code\n```"
    )
    assert len(doc) == 2
    assert serialise(doc) == text


def test_a_blank_line_then_shallower_text_ends_the_body() -> None:
    doc = parse("- Item <!-- q:aaaa -->\n  body\n\nprose\n")
    assert doc.get("aaaa").body == "body"
    assert serialise(doc) == "- Item <!-- q:aaaa -->\n  body\n\nprose\n"


def test_old_question_files_still_open() -> None:
    # The first format marked questions with ? and answers with >. Now the ?
    # is part of the text and the > lines are the body.
    doc = parse(read("spec_example.md"))
    first = doc.get("a1b2")
    assert first.subject == "? Where should we go in June?"
    assert first.body.startswith("> Somewhere by the sea")
    assert [c.subject for c in first.children] == [
        "? Which stretch of coast?",
        "?x Do we need to book trains early?",
    ]


def test_messy_structure() -> None:
    doc = parse(read("messy.md"))
    opening = doc.get("0a0a")
    assert opening.body.split("\n") == [
        "> Because it starts with definitions.",
        ">",
        ">   Indented second paragraph,  with  odd   spacing.  ",
        "> > a nested quote inside the answer",
        "continuation prose that belongs to the question",
    ]
    assert [c.subject for c in opening.children] == [
        "plain sub-bullet",
        "?x Should I cut the definitions?",
        "? After the fence",
    ]
    # Inside a fence nothing is an item.
    assert not any("this is code" in i.subject for i in doc.walk())
    assert doc.get("0f0f").parent is doc.get("0e0e")
    assert doc.get("1a1a").parent is doc.get("0f0f")


def test_crlf_and_tabs() -> None:
    doc = parse(read("crlf_tabs.md"))
    assert doc.newline == "\r\n"
    assert doc.get("7a7a").body == "> tab-indented answer"
    assert doc.get("7c7c").parent is doc.get("7b7b")


def test_editing_one_item_leaves_the_others_untouched() -> None:
    doc = parse(read("messy.md"))
    before = serialise(doc).split("\n")
    ops.set_text(doc, "0e0e", "Renamed")
    after = serialise(doc).split("\n")
    changed = [(b, a) for b, a in zip(before, after, strict=True) if b != a]
    assert changed == [
        ("* ? Star marker question <!-- q:0e0e -->", "* Renamed <!-- q:0e0e -->")
    ]


def test_rendered_subject_line() -> None:
    doc = parse("")
    item = ops.add(doc, "Pack")
    ops.mark_done(doc, item.id)
    assert serialise(doc) == f"- [x] Pack <!-- q:{item.id} -->\n"


def test_empty_and_whitespace_only_documents() -> None:
    for text in ["", "\n", "   \n\n"]:
        doc = parse(text)
        assert len(doc) == 0
        assert serialise(doc) == text


def test_id_comment_is_only_recognised_at_the_end() -> None:
    doc = parse("- has <!-- q:abcd --> in the middle\n")
    (item,) = doc.walk()
    assert item.id != "abcd"
    assert item.subject == "has <!-- q:abcd --> in the middle"
