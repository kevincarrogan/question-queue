import re
from pathlib import Path

import pytest

from questionqueue.core import Document, Question, RawLine, Status, parse, serialise

FIXTURES = Path(__file__).parent.parent / "fixtures"


def read(name: str) -> str:
    with (FIXTURES / name).open(encoding="utf-8", newline="") as f:
        return f.read()


def ids_in(doc: Document) -> list[str]:
    return [q.id for q in doc.walk()]


@pytest.mark.parametrize("name", ["spec_example.md", "messy.md", "crlf_tabs.md"])
def test_files_with_ids_round_trip_byte_for_byte(name: str) -> None:
    text = read(name)
    doc = parse(text)
    assert not doc.ids_assigned
    assert serialise(doc) == text


def test_missing_ids_are_the_only_change() -> None:
    text = read("missing_ids.md")
    doc = parse(text)
    assert doc.ids_assigned
    out = serialise(doc)
    before, after = text.split("\n"), out.split("\n")
    assert len(before) == len(after)
    changed = [(b, a) for b, a in zip(before, after, strict=True) if b != a]
    for b, a in changed:
        if "<!-- q:beef -->" in b:
            # The second copy of a duplicate ID gets a fresh one in place.
            assert re.fullmatch(re.escape(b).replace("beef", "[0-9a-f]{4}"), a)
        else:
            assert re.fullmatch(re.escape(b.rstrip()) + r" <!-- q:[0-9a-f]{4} -->", a)
    assert len(changed) == 5
    assert len(set(ids_in(doc))) == len(ids_in(doc)) == 7
    # A second load is stable.
    again = parse(out)
    assert not again.ids_assigned
    assert serialise(again) == out


def test_spec_example_structure() -> None:
    doc = parse(read("spec_example.md"))
    assert [q.id for q in doc.children] == ["a1b2", "g7h8"]
    opening = doc.get("a1b2")
    assert opening.text == "How should the essay open?"
    assert opening.answer == "Start with the story, it's concrete."
    assert [q.id for q in opening.children] == ["c3d4", "e5f6"]
    background = doc.get("e5f6")
    assert background.status is Status.ANSWERED
    assert background.answer == "No, link out instead."
    assert background.parent is opening
    assert doc.get("c3d4").answer == ""
    assert doc.get("g7h8").parent_id is None


def test_messy_structure() -> None:
    doc = parse(read("messy.md"))
    assert ids_in(doc) == [
        "0a0a",
        "0b0b",
        "0c0c",
        "0d0d",
        "0e0e",
        "0f0f",
        "1a1a",
        "1b1b",
    ]

    drag = doc.get("0a0a")
    assert drag.answer == (
        "Because it starts with definitions.\n"
        "\n"
        "  Indented second paragraph,  with  odd   spacing.  \n"
        "> a nested quote inside the answer"
    )
    # A question under a plain sub-bullet still nests under the nearest question.
    assert doc.get("0b0b").parent is drag
    assert [q.id for q in drag.children] == ["0b0b", "0c0c", "0d0d"]
    # The code fence, with its blank line and fake question, stays with 0a0a.
    raw = [item.text for item in drag.items if isinstance(item, RawLine)]
    assert "  - ? this is code, not a question" in raw
    cut = doc.get("0c0c")
    assert cut.answer == "Yes."
    assert [item.text for item in cut.items if isinstance(item, RawLine)] == [
        "",
        "    > This quote is after a blank line, so it is not an answer.",
    ]

    assert doc.get("0f0f").parent is doc.get("0e0e")
    assert doc.get("0f0f").answer == "Deep answer"
    assert doc.get("1a1a").parent is doc.get("0f0f")
    assert doc.get("1b1b").parent is doc

    texts = [item.text for item in doc.items if isinstance(item, RawLine)]
    for not_a_question in [
        "- ?not a question (no space)",
        "- ?? also not a question",
        "- ?xylophone is not answered syntax",
        "-  ? two spaces before the mark",
        "- ?   ",
        "- ? tilde fenced",
        "> a top-level blockquote that is not an answer",
    ]:
        assert not_a_question in texts


def test_crlf_and_tabs() -> None:
    doc = parse(read("crlf_tabs.md"))
    assert doc.newline == "\r\n"
    assert doc.get("7a7a").answer == "tab-indented answer"
    assert doc.get("7b7b").parent is doc.get("7a7a")
    assert doc.get("7c7c").parent is doc.get("7b7b")
    assert doc.get("7d7d").parent is doc


def test_answer_whitespace_is_verbatim() -> None:
    doc = parse("- ? Q <!-- q:aaaa -->\n  >   leading\n  > trailing   \n  >\n  >  \n")
    assert doc.get("aaaa").answer == "  leading\ntrailing   \n\n "


@pytest.mark.parametrize(
    "answer",
    [
        "one line",
        "two\nlines",
        "  indented\n\n  blank between  ",
        "trailing newline\n",
        "\nleading newline",
        "> looks like a quote",
        " ",
    ],
)
def test_changed_answers_round_trip(answer: str) -> None:
    doc = parse("- ? Q <!-- q:aaaa -->\n")
    doc.get("aaaa").answer = answer
    assert parse(serialise(doc)).get("aaaa").answer == answer


def test_editing_one_question_leaves_others_untouched() -> None:
    text = read("messy.md")
    doc = parse(text)
    doc.get("0c0c").answer = "Changed."
    out = serialise(doc)
    assert out == text.replace("    > Yes.", "    > Changed.")


def test_rendered_question_line() -> None:
    doc = parse("  * ? Q   <!-- q:aaaa -->\n")
    q = doc.get("aaaa")
    q.status = Status.ANSWERED
    assert serialise(doc) == "  * ?x Q <!-- q:aaaa -->\n"


def test_empty_and_whitespace_only_documents() -> None:
    assert serialise(parse("")) == ""
    assert serialise(parse("\n\n")) == "\n\n"
    assert serialise(parse("no newline")) == "no newline"


def test_id_comment_is_only_recognised_at_the_end() -> None:
    doc = parse("- ? Is <!-- q:aaaa --> mid-line? <!-- q:bbbb -->\n")
    assert doc.get("bbbb").text == "Is <!-- q:aaaa --> mid-line?"


def test_questions_are_plain_objects() -> None:
    doc = parse(read("spec_example.md"))
    assert all(isinstance(q, Question) for q in doc.walk())
    assert len(doc) == 4
    assert "a1b2" in doc
