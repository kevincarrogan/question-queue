"""Drive the real app with Textual's pilot. Each test runs its own event loop."""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from textual.pilot import Pilot

from questionqueue.core import Status, parse
from questionqueue.tui.app import QQApp
from questionqueue.tui.focus import AnswerArea, FocusView
from questionqueue.tui.modals import ChoiceModal
from questionqueue.tui.outline import OutlineTree

TREE = """\
# Essay

- ? How should the essay open? <!-- q:a1b2 -->
  > Start with the story.
  - ? Which anecdote exactly? <!-- q:c3d4 -->
  - ?x Does it need background? <!-- q:e5f6 -->
    > No, link out instead.
- ? Who's the audience? <!-- q:g7h8 -->
"""

type Scenario = Callable[[QQApp, Pilot[None]], Awaitable[None]]


@pytest.fixture
def notes(tmp_path: Path) -> Path:
    path = tmp_path / "notes.md"
    path.write_text(TREE)
    return path


def run(path: Path, scenario: Scenario) -> QQApp:
    app = QQApp(path, watch=False)

    async def main() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await scenario(app, pilot)
            await pilot.pause()

    asyncio.run(main())
    return app


async def type_text(pilot: Pilot[None], text: str) -> None:
    await pilot.press(*["space" if c == " " else c for c in text])


def on_disk(path: Path):  # type: ignore[no-untyped-def]
    return parse(path.read_text())


def test_starts_on_first_open_question_in_the_editor(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        assert app.current_id == "a1b2"
        assert isinstance(app.focused, AnswerArea)
        assert app.focused.text == "Start with the story."

    run(notes, scenario)


def test_letters_type_into_the_editor_and_escape_saves_them(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("end")
        await type_text(pilot, " nq ru")
        assert app.current_id == "a1b2"  # no command fired
        await pilot.press("escape")
        assert isinstance(app.focused, FocusView)

    run(notes, scenario)
    assert on_disk(notes).get("a1b2").answer == "Start with the story. nq ru"


def test_park_child(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("escape", "n")
        await type_text(pilot, "What about the ending?")
        await pilot.press("enter")
        assert app.current_id == "a1b2"
        assert isinstance(app.focused, FocusView)

    run(notes, scenario)
    doc = on_disk(notes)
    children = doc.get("a1b2").children
    assert [q.text for q in children][-1] == "What about the ending?"
    assert children[-1].status is Status.OPEN


def test_park_sibling(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("escape", "N")
        await type_text(pilot, "Sibling")
        await pilot.press("enter")

    run(notes, scenario)
    assert [q.text for q in on_disk(notes).children] == [
        "How should the essay open?",
        "Sibling",
        "Who's the audience?",
    ]


def test_park_root(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("ctrl+n")  # to c3d4, two levels down
        assert app.current_id == "c3d4"
        await pilot.press("escape", "r")
        await type_text(pilot, "Root level")
        await pilot.press("enter")
        assert app.current_id == "c3d4"

    run(notes, scenario)
    assert [q.text for q in on_disk(notes).children][-1] == "Root level"


def test_escape_cancels_parking(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("escape", "n")
        await type_text(pilot, "Never mind")
        await pilot.press("escape")

    run(notes, scenario)
    assert notes.read_text() == TREE


def test_next_open(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("ctrl+n")
        assert app.current_id == "c3d4"
        assert isinstance(app.focused, AnswerArea)
        await pilot.press("ctrl+n")
        assert app.current_id == "a1b2"  # back to the open parent
        await pilot.press("ctrl+n")
        assert app.current_id == "c3d4"

    run(notes, scenario)


def test_mark_answered_moves_on(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("ctrl+n")
        await type_text(pilot, "The first one")
        await pilot.press("ctrl+d")
        assert app.current_id == "a1b2"
        await pilot.press("ctrl+d")
        assert app.current_id == "g7h8"

    run(notes, scenario)
    doc = on_disk(notes)
    assert doc.get("c3d4").status is Status.ANSWERED
    assert doc.get("c3d4").answer == "The first one"
    assert doc.get("a1b2").status is Status.ANSWERED
    assert doc.get("g7h8").status is Status.OPEN


def test_up_goes_to_parent(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("ctrl+n", "escape", "u")
        assert app.current_id == "a1b2"

    run(notes, scenario)


def test_outline_open_and_reorder(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("tab")
        await pilot.pause()
        assert isinstance(app.focused, OutlineTree)
        assert app.outline.highlighted_id == "a1b2"
        await pilot.press("j")
        assert app.outline.highlighted_id == "c3d4"
        await pilot.press("J")  # move below its answered sibling
        await pilot.pause()
        assert app.outline.highlighted_id == "c3d4"
        await pilot.press("enter")
        assert app.current_id == "c3d4"
        assert isinstance(app.focused, AnswerArea)

    run(notes, scenario)
    assert [q.id for q in on_disk(notes).get("a1b2").children] == ["e5f6", "c3d4"]


def test_answered_branches_start_collapsed(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text(
        "- ?x Done <!-- q:done -->\n  - ?x Also done <!-- q:dun2 -->\n"
        "- ?x Done, open inside <!-- q:dop -->\n  - ? Open <!-- q:open -->\n"
    )

    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("tab")
        await pilot.pause()
        nodes = {n.data: n for n in app.outline.root.children}
        assert not nodes["done"].is_expanded
        assert nodes["dop"].is_expanded

    run(path, scenario)


def test_delete_with_children_asks_first(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("tab")
        await pilot.pause()
        await pilot.press("d")
        assert isinstance(app.screen, ChoiceModal)
        await pilot.press("n")
        assert "a1b2" in app.file.doc
        await pilot.press("d", "y")
        assert "a1b2" not in app.file.doc
        assert app.current_id == "g7h8"

    run(notes, scenario)
    assert [q.id for q in on_disk(notes).walk()] == ["g7h8"]


def test_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "new.md"

    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        assert app.current_id is None
        assert isinstance(app.focused, FocusView)
        await pilot.press("n")  # nothing to nest under, so it goes to the root
        await type_text(pilot, "First")
        await pilot.press("enter")
        assert app.current is not None
        assert app.current.text == "First"

    run(path, scenario)
    assert [q.text for q in on_disk(path).walk()] == ["First"]


def test_external_change_reloads_when_clean(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        notes.write_text(TREE.replace("Who's the audience?", "Who reads this?"))
        app.on_external_change()
        await pilot.pause()
        assert app.file.doc.get("g7h8").text == "Who reads this?"
        assert app.current_id == "a1b2"

    run(notes, scenario)


def test_external_change_with_unsaved_edits_warns(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await type_text(pilot, "mine ")
        changed = TREE.replace("Who's the audience?", "Theirs")
        notes.write_text(changed)
        app.on_external_change()
        await pilot.pause()
        assert isinstance(app.screen, ChoiceModal)
        assert notes.read_text() == changed  # not clobbered
        await pilot.press("k")
        await pilot.pause()

    run(notes, scenario)
    doc = on_disk(notes)
    assert doc.get("a1b2").answer.startswith("mine ")
    assert doc.get("g7h8").text == "Who's the audience?"
