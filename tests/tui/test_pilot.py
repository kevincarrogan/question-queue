"""Drive the real app with Textual's pilot. Each test runs its own event loop."""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from rich.style import Style
from textual.pilot import Pilot

from questionqueue.core import Kind, QueueChoice, Status, parse, queue_in
from questionqueue.tui import app as app_module
from questionqueue.tui.app import QQApp
from questionqueue.tui.editor import ItemText
from questionqueue.tui.modals import (
    ChoiceModal,
    Find,
    HelpModal,
    Jump,
    PaletteModal,
    Problem,
    Replace,
    by_number,
    parse_command,
)
from questionqueue.tui.outline import NEW_ID, OutlineList
from questionqueue.tui.render import outline

TREE = """\
# Trip

- Where should we go in June? <!-- q:a1b2 -->
  Somewhere by the sea.
  - Which stretch of coast? <!-- q:c3d4 -->
  - [x] Book trains early <!-- q:e5f6 -->
    By the end of March.
- Who's coming? <!-- q:g7h8 -->
"""

type Scenario = Callable[[QQApp, Pilot[None]], Awaitable[None]]


@pytest.fixture
def notes(tmp_path: Path) -> Path:
    path = tmp_path / "notes.md"
    path.write_text(TREE)
    return path


def run(path: Path | QueueChoice, scenario: Scenario) -> QQApp:
    app = QQApp(path, watch=False)

    async def main() -> None:
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await scenario(app, pilot)
            await pilot.pause()

    asyncio.run(main())
    return app


async def type_text(pilot: Pilot[None], text: str) -> None:
    keys = {" ": "space", "\n": "enter"}
    await pilot.press(*[keys.get(c, c) for c in text])


def on_disk(path: Path):  # type: ignore[no-untyped-def]
    return parse(path.read_text())


def prompt(app: QQApp, option_id: str) -> str:
    return str(app.outline.get_option(option_id).prompt)


# Read through a function, so mypy doesn't narrow it between key presses.
def mode(app: QQApp) -> str:
    return app.mode


# -- the outline: moving and arranging, never typing ----------------------------


def test_starts_in_the_outline_on_the_first_item(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        assert isinstance(app.focused, OutlineList)
        assert mode(app) == "OUTLINE"
        assert app.current_id == "a1b2"
        assert app.editor.text == "Where should we go in June?\nSomewhere by the sea."

    run(notes, scenario)


def test_letters_in_the_outline_never_type(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("z", "w", "b")
        assert mode(app) == "OUTLINE"

    run(notes, scenario)
    assert notes.read_text() == TREE


def test_arrows_and_j_k_move_and_the_editor_follows(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("down")
        assert app.current_id == "c3d4"
        assert app.editor.text == "Which stretch of coast?"
        await pilot.press("j", "j")
        assert app.current_id == "g7h8"
        await pilot.press("k")
        assert app.current_id == "e5f6"

    run(notes, scenario)


def test_space_ticks_and_t_takes_the_box_away(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("end", "space")
        assert app.file.doc.get("g7h8").status is Status.DONE
        await pilot.press("space")
        assert app.file.doc.get("g7h8").status is Status.OPEN
        assert app.file.doc.get("g7h8").kind is Kind.TODO
        await pilot.press("t")
        assert app.file.doc.get("g7h8").kind is Kind.PLAIN

    run(notes, scenario)
    assert notes.read_text() == TREE


def test_a_partly_ticked_item_shows_a_dash(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("down", "t")  # give c3d4 a box: one of two ticked
        assert prompt(app, "a1b2").startswith("1 • ")  # plain: no say
        await pilot.press("up", "t")
        assert prompt(app, "a1b2").startswith("1 [-] Where should we go")
        await pilot.press("space")  # ticks everything under it
        assert prompt(app, "a1b2").startswith("1 [x] ")
        assert prompt(app, "c3d4").startswith("2   [x] ")
        await pilot.press("down", "space")  # untick one: back to a dash
        assert prompt(app, "a1b2").startswith("1 [-] ")
        assert app.file.doc.get("a1b2").status is Status.OPEN

    run(notes, scenario)


def test_x_deletes_straight_away_when_theres_nothing_to_lose(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("down", "x")
        assert "c3d4" not in app.file.doc
        assert app.current_id == "e5f6"

    run(notes, scenario)


def test_x_asks_first_when_theres_more_to_it(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("x")
        assert isinstance(app.screen, ChoiceModal)
        await pilot.press("n")
        assert "a1b2" in app.file.doc
        await pilot.press("x", "y")
        assert "a1b2" not in app.file.doc
        assert app.current_id == "g7h8"

    run(notes, scenario)
    assert [i.id for i in on_disk(notes).walk()] == ["g7h8"]


# -- the editor: where typing goes --------------------------------------------


def test_ctrl_n_goes_to_the_editor_and_back(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("ctrl+n")
        assert isinstance(app.focused, ItemText)
        assert mode(app) == "EDIT"
        await pilot.press(*["backspace"] * len(" in June?"))
        await type_text(pilot, " first?")
        await pilot.press("ctrl+n")
        assert isinstance(app.focused, OutlineList)
        assert mode(app) == "OUTLINE"

    run(notes, scenario)
    item = on_disk(notes).get("a1b2")
    assert item.subject == "Where should we go first?"
    assert item.body == "Somewhere by the sea."


def test_enter_in_the_editor_is_a_new_line_and_esc_goes_back(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("down", "ctrl+n")
        await type_text(pilot, "\nThe north, with cliffs.\n\n  Or a lake?")
        await pilot.press("escape")
        assert mode(app) == "OUTLINE"

    run(notes, scenario)
    assert on_disk(notes).get("c3d4").text == (
        "Which stretch of coast?\nThe north, with cliffs.\n\n  Or a lake?"
    )


def test_edits_save_when_typing_pauses(
    notes: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "SAVE_DELAY", 0.05)

    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("ctrl+n", "down", "end")
        await type_text(pilot, " More.")
        await pilot.pause(0.2)
        assert on_disk(notes).get("a1b2").body == "Somewhere by the sea. More."

    run(notes, scenario)


def test_a_blank_first_line_is_not_saved(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("down", "ctrl+n")
        await pilot.press(*["backspace"] * len("Which stretch of coast?"))
        await pilot.press("escape")

    run(notes, scenario)
    assert on_disk(notes).get("c3d4").subject == "Which stretch of coast?"


# -- adding -------------------------------------------------------------------


def test_enter_adds_after_this_item_and_its_children(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("enter")
        assert mode(app) == "NEW"
        await type_text(pilot, "How long for?")
        await pilot.press("escape")
        assert mode(app) == "OUTLINE"  # back in the outline, on the new item
        assert app.current is not None
        assert app.current.subject == "How long for?"
        await pilot.press("enter")
        await type_text(pilot, "Packing\ntent\nstove")
        await pilot.press("ctrl+n")

    run(notes, scenario)
    doc = on_disk(notes)
    assert [i.subject for i in doc.children] == [
        "Where should we go in June?",
        "How long for?",
        "Packing",
        "Who's coming?",
    ]
    assert doc.children[2].body == "tent\nstove"


@pytest.mark.parametrize("key", ["alt+enter", "shift+enter"])
def test_alt_or_shift_enter_adds_above(notes: Path, key: str) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press(key)
        await type_text(pilot, "Why go at all?")
        await pilot.press("escape")

    run(notes, scenario)
    assert on_disk(notes).children[0].subject == "Why go at all?"


def test_leaving_a_new_item_empty_adds_nothing(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("enter")
        await type_text(pilot, "\n\n")
        await pilot.press("escape")
        assert mode(app) == "OUTLINE"
        assert app.current_id == "a1b2"
        assert app.editor.text.startswith("Where should we go in June?")

    run(notes, scenario)
    assert notes.read_text() == TREE


def test_empty_file_shows_the_guide_and_enter_starts(tmp_path: Path) -> None:
    path = tmp_path / "new.md"

    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        assert app.current_id is None
        assert "Nothing here yet" in str(app.outline.get_option_at_index(0).prompt)
        await pilot.press("enter")
        await type_text(pilot, "First")
        await pilot.press("escape")
        assert app.current is not None
        assert app.current.subject == "First"

    run(path, scenario)
    assert [i.subject for i in on_disk(path).walk()] == ["First"]


# -- jotting a passing thought ------------------------------------------------------


# -- the file changing underneath ------------------------------------------------


def test_external_change_reloads_when_clean(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        notes.write_text(TREE.replace("Who's coming?", "Who else is coming?"))
        app.on_external_change()
        await pilot.pause()
        assert app.file.doc.get("g7h8").subject == "Who else is coming?"
        assert app.current_id == "a1b2"

    run(notes, scenario)


def test_external_change_with_unsaved_edits_warns(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("ctrl+n", "down", "end")
        await type_text(pilot, " mine")
        changed = TREE.replace("Who's coming?", "Theirs")
        notes.write_text(changed)
        app.on_external_change()
        await pilot.pause()
        assert isinstance(app.screen, ChoiceModal)
        assert notes.read_text() == changed  # not clobbered
        await pilot.press("k")
        await pilot.pause()

    run(notes, scenario)
    doc = on_disk(notes)
    assert doc.get("a1b2").body.endswith(" mine")
    assert doc.get("g7h8").subject == "Who's coming?"


# -- which queue -------------------------------------------------------------------


@pytest.fixture
def choice(tmp_path: Path) -> QueueChoice:
    return QueueChoice(
        here=queue_in(tmp_path / "project"), home=queue_in(tmp_path / "home")
    )


def test_no_queue_asks_first_and_h_starts_one_here(choice: QueueChoice) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        assert isinstance(app.screen, ChoiceModal)
        assert not choice.here.exists()
        await pilot.press("h")
        assert not isinstance(app.screen, ChoiceModal)
        assert app.file.path == choice.here.resolve()
        await pilot.press("enter")
        await type_text(pilot, "First")
        await pilot.press("escape")

    run(choice, scenario)
    assert [i.subject for i in on_disk(choice.here).walk()] == ["First"]
    assert not choice.home.exists()


def test_no_queue_g_uses_the_global_one(choice: QueueChoice) -> None:
    choice.home.parent.mkdir(parents=True)
    choice.home.write_text(TREE)

    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("g")
        assert app.current_id == "a1b2"

    run(choice, scenario)
    assert not choice.here.exists()


@pytest.mark.parametrize("key", ["q", "escape"])
def test_no_queue_quit_creates_nothing(choice: QueueChoice, key: str) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press(key)

    app = run(choice, scenario)
    assert not app.is_running
    assert not choice.here.exists()
    assert not choice.home.exists()


# -- file references -----------------------------------------------------------------


def test_o_opens_the_reference_in_the_editor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    (project / "foo" / "bar").mkdir(parents=True)
    (project / "foo" / "bar" / "core.py").write_text("")
    queue = queue_in(project)
    queue.parent.mkdir()
    queue.write_text(
        "- Where is the function to do X? <!-- q:a1b2 -->\n  foo/bar/core.py:30\n"
    )
    calls: list[list[str]] = []
    monkeypatch.setenv("EDITOR", "vim")
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr("subprocess.run", lambda argv, **_: calls.append(argv))
    monkeypatch.setattr(QQApp, "suspend", lambda self: contextlib.nullcontext())

    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("o")

    run(queue, scenario)
    assert calls == [["vim", "+30", str((project / "foo/bar/core.py").resolve())]]


def test_clicking_a_reference_in_the_outline_opens_it_in_vs_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    (project / "foo" / "bar").mkdir(parents=True)
    (project / "foo" / "bar" / "core.py").write_text("")
    queue = queue_in(project)
    queue.parent.mkdir()
    queue.write_text(
        "- First <!-- q:a1b2 -->\n- It's in foo/bar/core.py:30 <!-- q:c3d4 -->\n"
    )
    calls: list[list[str]] = []
    for name in ("QQ_EDITOR", "VISUAL", "EDITOR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/local/bin/{name}")
    monkeypatch.setattr("subprocess.run", lambda argv, **_: calls.append(argv))

    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        line = prompt(app, "c3d4")
        await pilot.click(
            OutlineList, offset=(3 + line.index("foo"), 2)
        )  # border, padding
        await pilot.pause()
        assert app.current_id == "c3d4"
        assert mode(app) == "OUTLINE"

    run(queue, scenario)
    path = (project / "foo/bar/core.py").resolve()
    assert calls == [["code", "-g", f"{path}:30"]]


def test_o_without_a_reference_says_so(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("o")
        assert any("No file:line" in str(n.message) for n in app._notifications)

    run(notes, scenario)


# -- drawing -------------------------------------------------------------------------


# -- the outline as you see it: numbers, new rows, live typing ----------------------


def test_the_outline_shows_numbered_first_lines() -> None:
    lines = [(text.plain, item_id) for text, item_id in outline(parse(TREE))]
    assert lines == [
        ("1 • Where should we go in June? …", "a1b2"),
        ("2   • Which stretch of coast?", "c3d4"),
        ("3   [x] Book trains early …", "e5f6"),
        ("4 • Who's coming?", "g7h8"),
    ]


def test_references_are_underlined_and_draw(tmp_path: Path) -> None:
    text = "- see foo/bar/core.py:30 <!-- q:a1b2 -->\n"
    line = outline(parse(text))[0][0]
    ref = next(span for span in line.spans if span.start == 8)
    assert ref.end == 26
    assert isinstance(ref.style, Style)
    assert ref.style.underline
    assert ref.style.meta == {"ref": "foo/bar/core.py:30"}  # so a click can open it
    path = tmp_path / "notes.md"
    path.write_text(text)

    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        pass

    run(path, scenario)  # drawing it must not raise


def test_a_new_item_shows_in_the_outline_straight_away(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("enter")
        # A blank row, selected, after a1b2 and the two items under it.
        assert app.outline.get_option_at_index(3).id == NEW_ID
        assert app.outline.highlighted == 3
        assert prompt(app, NEW_ID) == "  • "
        await type_text(pilot, "How long for?")
        assert prompt(app, NEW_ID) == "  • How long for?"
        await type_text(pilot, "\nA week")
        assert prompt(app, NEW_ID) == "  • How long for? …"
        await pilot.press("escape")
        assert app.current is not None
        assert app.outline.highlighted == 3
        assert prompt(app, app.current.id) == "4 • How long for? …"

    run(notes, scenario)


def test_a_new_item_above_shows_above(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("down", "alt+enter")
        assert app.outline.get_option_at_index(1).id == NEW_ID
        assert prompt(app, NEW_ID) == "    • "  # at c3d4's depth

    run(notes, scenario)


def test_the_blank_row_goes_if_nothing_is_typed(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("enter", "escape")
        assert app.outline.option_count == 4
        assert app.outline.highlighted == 0

    run(notes, scenario)


def test_editing_the_first_line_updates_the_outline_as_you_type(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("down", "e")
        await type_text(pilot, " exactly")
        assert prompt(app, "c3d4") == "2   • Which stretch of coast? exactly"

    run(notes, scenario)


# -- n: a new item at the bottom, then back where you were --------------------------


def test_n_adds_at_the_bottom_and_brings_you_back(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("e", "down", "end")
        await type_text(pilot, " Maybe Cornwall.")
        await pilot.press("escape", "n")
        assert mode(app) == "NEW"
        assert app.editor.text == ""
        assert app.outline.get_option_at_index(4).id == NEW_ID
        assert prompt(app, NEW_ID) == "  • "
        await type_text(pilot, "Buy a new tent")
        await pilot.press("escape")
        assert mode(app) == "OUTLINE"
        assert app.current_id == "a1b2"  # back on the item you were on
        assert app.editor.text.endswith("Maybe Cornwall.")

    run(notes, scenario)
    doc = on_disk(notes)
    assert doc.get("a1b2").body == "Somewhere by the sea. Maybe Cornwall."
    assert doc.children[-1].subject == "Buy a new tent"


def test_an_empty_n_adds_nothing(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("down", "n", "escape")
        assert mode(app) == "OUTLINE"
        assert app.current_id == "c3d4"
        assert app.outline.option_count == 4

    run(notes, scenario)
    assert notes.read_text() == TREE


# -- m and shift+arrows: moving items -------------------------------------------------


def test_m_carries_an_item_through_the_outline(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("end", "m")  # pick up "Who's coming?"
        assert mode(app) == "MOVE"
        await pilot.press("up")  # into a1b2, above "Book trains early"
        await pilot.press("up")  # above "Which stretch of coast?"
        await pilot.press("enter")
        assert mode(app) == "OUTLINE"
        assert app.current_id == "g7h8"

    run(notes, scenario)
    assert [c.id for c in on_disk(notes).get("a1b2").children] == [
        "g7h8",
        "c3d4",
        "e5f6",
    ]


def test_m_then_tab_and_shift_tab_change_its_level(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("down", "m", "shift+tab", "enter")

    run(notes, scenario)
    assert [c.id for c in on_disk(notes).children] == ["a1b2", "c3d4", "g7h8"]


def test_escape_puts_a_moving_item_back(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("end", "m", "up", "up", "escape")
        assert mode(app) == "OUTLINE"
        assert app.file.doc.get("g7h8").parent_id is None

    run(notes, scenario)
    assert notes.read_text() == TREE


def test_shift_arrows_nudge_without_m(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("down", "shift+down")  # c3d4 past e5f6
        assert [c.id for c in app.file.doc.get("a1b2").children] == ["e5f6", "c3d4"]
        await pilot.press("shift+up")
        assert app.current_id == "c3d4"

    run(notes, scenario)
    assert notes.read_text() == TREE


def test_tab_and_shift_tab_indent_and_outdent(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("end", "tab")
        assert app.file.doc.get("g7h8").parent_id == "a1b2"
        await pilot.press("shift+tab")
        assert app.file.doc.get("g7h8").parent_id is None
        await pilot.press("shift+right")
        assert app.current_id == "g7h8"

    run(notes, scenario)
    assert "  - Who's coming?" in notes.read_text()


# -- ← and →: folding ----------------------------------------------------------------


def test_left_folds_and_right_unfolds(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("left")
        assert app.outline.option_count == 2
        assert prompt(app, "a1b2") == "1 • Where should we go in June? …  ▸ 2"
        assert prompt(app, "g7h8").startswith("4 ")  # numbers don't change
        await pilot.press("right")
        assert app.outline.option_count == 4

    run(notes, scenario)


def test_right_edits_once_nothing_is_folded(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("left")
        await pilot.press("right")  # unfolds first
        assert mode(app) == "OUTLINE"
        await pilot.press("right")
        assert mode(app) == "EDIT"
        assert app.editor.text_area.cursor_location == (
            0,
            len("Where should we go in June?"),
        )

    run(notes, scenario)


def test_left_goes_to_the_parent(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("down")
        assert app.current_id == "c3d4"
        await pilot.press("left")  # nothing to fold, so up to the parent
        assert app.current_id == "a1b2"

    run(notes, scenario)


# -- u: undo ---------------------------------------------------------------------------


def test_u_undoes_one_change_at_a_time(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("space")  # tick
        await pilot.press("end", "tab")  # indent
        await pilot.press("x")  # delete (nothing under it, so no question)
        assert "g7h8" not in app.file.doc
        await pilot.press("u")
        assert app.file.doc.get("g7h8").parent_id == "a1b2"
        await pilot.press("u")
        assert app.file.doc.get("g7h8").parent_id is None
        await pilot.press("u")
        assert app.file.doc.get("a1b2").status is Status.OPEN

    run(notes, scenario)
    assert notes.read_text() == TREE


def test_u_undoes_a_text_edit_and_a_new_item(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("e")
        await type_text(pilot, "!!")
        await pilot.press("escape", "enter")
        await type_text(pilot, "Extra")
        await pilot.press("escape", "u", "u")

    run(notes, scenario)
    assert notes.read_text() == TREE


# -- : and /: find and go to -----------------------------------------------------------


def test_slash_finds_by_text(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("slash")
        await type_text(pilot, "march")  # in the rest of the text, not the first line
        await pilot.press("enter")
        assert app.current_id == "e5f6"
        await pilot.press("slash")
        await type_text(pilot, "coast")
        await pilot.press("escape")
        assert app.current_id == "e5f6"

    run(notes, scenario)


def test_what_the_palette_understands() -> None:
    assert parse_command(":34") == Jump(34)
    assert parse_command(":") == Jump(None)
    assert isinstance(parse_command(":x"), Problem)
    assert parse_command("tent") == Find("tent", everywhere=True)
    assert parse_command("/tent") == Find("tent", everywhere=False)
    assert parse_command("//tent") == Find("tent", everywhere=True)
    # No closing slash: a search, so paths can be found as they are.
    assert parse_command("/src/app.py") == Find("src/app.py", everywhere=False)
    assert parse_command("/tent/van/") == Replace("tent", "van", False, False, False)
    assert parse_command("//tent/van/gi") == Replace("tent", "van", True, True, True)
    assert parse_command("/a\\/b/c/") == Replace("a/b", "c", False, False, False)
    assert parse_command("/tent//") == Replace("tent", "", False, False, False)
    assert isinstance(parse_command("/tent/van/x"), Problem)


def test_numbers_typed_so_far_put_the_exact_one_first() -> None:
    assert by_number([1, 2, 3, 30, 31], 3) == [3, 30, 31]
    assert by_number([1, 2, 3], None) == [1, 2, 3]


def test_ctrl_p_in_the_outline_goes_to_an_item(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("ctrl+p")
        await type_text(pilot, ":4")
        await pilot.press("enter")
        assert app.current_id == "g7h8"

    run(notes, scenario)


def test_slash_in_the_editor_finds_a_line_in_this_item(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("e", "ctrl+p")
        await type_text(pilot, "/sea")
        await pilot.press("enter")
        assert app.current_id == "a1b2"
        assert isinstance(app.focused, ItemText)
        assert app.editor.text_area.cursor_location == (1, len("Somewhere by the "))

    run(notes, scenario)


def test_double_slash_in_the_editor_finds_any_item(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("e", "ctrl+p")
        await type_text(pilot, "//march")
        await pilot.press("enter")
        assert app.current_id == "e5f6"

    run(notes, scenario)


def test_colon_in_the_editor_goes_to_a_line(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("e", "ctrl+p")
        await type_text(pilot, ":2")
        await pilot.press("enter")
        assert app.editor.text_area.cursor_location == (1, 0)

    run(notes, scenario)


def test_replace_in_the_editor_is_this_item_only(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("e", "ctrl+p")
        await type_text(pilot, "/e/E/g")
        hint = str(app.screen.query_one("#palette-hint").render())
        assert "replaces in 1 item" in hint
        await pilot.press("enter")
        assert isinstance(app.focused, ItemText)

    run(notes, scenario)
    doc = on_disk(notes)
    assert doc.get("a1b2").text == "WhErE should wE go in JunE?\nSomEwhErE by thE sEa."
    assert doc.get("g7h8").subject == "Who's coming?"


def test_replace_in_the_outline_is_every_item_and_u_undoes_it(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("slash")
        await type_text(pilot, " /_/g")
        await pilot.press("enter")
        assert app.file.doc.get("g7h8").subject == "Who's_coming?"
        assert app.file.doc.get("e5f6").body == "By_the_end_of_March."
        await pilot.press("u")

    run(notes, scenario)
    assert notes.read_text() == TREE


def test_without_g_only_the_first_match_on_each_line(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("e", "ctrl+p")
        await type_text(pilot, "/e/E/")
        await pilot.press("enter")

    run(notes, scenario)
    assert (
        on_disk(notes).get("a1b2").text
        == "WhEre should we go in June?\nSomEwhere by the sea."
    )


def test_a_replace_with_no_matches_stays_open(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("ctrl+p")
        await type_text(pilot, "/zebra/x/")
        await pilot.press("enter")
        assert isinstance(app.screen, PaletteModal)
        await pilot.press("escape")

    run(notes, scenario)
    assert notes.read_text() == TREE


def test_question_mark_shows_every_key(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("question_mark")
        assert isinstance(app.screen, HelpModal)
        await pilot.press("z")
        assert not isinstance(app.screen, HelpModal)
        assert mode(app) == "OUTLINE"

    run(notes, scenario)


def test_colon_goes_to_an_item_folded_out_of_sight(notes: Path) -> None:
    async def scenario(app: QQApp, pilot: Pilot[None]) -> None:
        await pilot.press("left")  # fold a1b2, hiding item 3
        await pilot.press("colon", "3", "enter")
        assert app.current_id == "e5f6"
        assert app.outline.option_count == 4  # unfolded to show it

    run(notes, scenario)
