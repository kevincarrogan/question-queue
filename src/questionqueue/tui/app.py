from __future__ import annotations

import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from rich.text import Text
from textual import events, on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Input, OptionList, Static, TextArea

from ..core import (
    DocumentFile,
    ExternalChange,
    InvalidMove,
    Item,
    Kind,
    QueueChoice,
    ops,
    parse,
    serialise,
)
from ..core.refs import (
    FileRef,
    choose_editor,
    editor_command,
    find_refs,
    project_folder,
    ref_at,
    resolve,
    windowed,
)
from . import keys
from .command import (
    HINTS,
    Command,
    CommandLine,
    Find,
    Jump,
    Pane,
    Problem,
    Replace,
    has_words,
    parse_command,
    replace_pattern,
    words_pattern,
)
from .editor import Back, ItemEditor, Place
from .modals import ChoiceModal, HelpModal
from .outline import NEW_ID, OutlineList
from .render import Found, draw_line, gutter_width, item_line

keys.install()

# How long typing has to pause before it's saved.
SAVE_DELAY = 1.0

# Keys pressed twice to be sure, as ctrl+d quits in Claude Code: the second
# press has to come within this many seconds.
TWICE_WINDOW = 2.0

# How many changes `u` can undo.
UNDO_LIMIT = 200

# Bindings that make no sense while a dialog is open.
MAIN_SCREEN_ACTIONS = {"switch", "open_ref", "find"}

type Mode = Literal["OUTLINE", "EDIT", "NEW", "MOVE"]

# The key bar for each mode. The mode name leads, so you always know which
# side you're on.
KEY_HINTS: dict[Mode, list[tuple[str, str]]] = {
    "OUTLINE": [
        ("enter", "new"),
        ("→", "edit"),
        ("m", "move"),
        ("space", "tick"),
        ("u", "undo"),
        ("/", "find"),
        ("?", "keys"),
    ],
    "EDIT": [
        ("esc", "outline"),
        ("^p", "/find //everywhere :line /old/new/"),
        ("^o", "open ref"),
    ],
    "NEW": [
        ("esc", "done"),
        ("first line", "shows in the outline"),
    ],
    "MOVE": [
        ("↑↓", "carry it"),
        ("←→", "out / in"),
        ("m enter", "drop it"),
        ("esc", "put it back"),
    ],
}


@dataclass(frozen=True)
class Origin:
    """Where you were when the command line opened, for esc to go back to."""

    pane: Pane
    current_id: str | None
    folded: frozenset[str]
    cursor: tuple[int, int]


def tilde(path: Path) -> str:
    """`path` with the home folder shortened to ~."""
    try:
        return str(Path("~") / path.relative_to(Path.home()))
    except ValueError:
        return str(path)


class QQApp(App[None]):
    CSS_PATH = "app.tcss"
    ENABLE_COMMAND_PALETTE = False
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (90, "-wide")]

    BINDINGS = [
        Binding("ctrl+n", "switch", show=False, priority=True),
        Binding("ctrl+o", "open_ref", show=False, priority=True),
        # VS Code's quick open is cmd+p, which terminals can't receive; this is
        # its Linux and Windows key. A terminal can map cmd+p to send it.
        Binding("ctrl+p", "find", show=False, priority=True),
        # Over the editor's own ctrl+d (delete forward), so it works anywhere.
        Binding("ctrl+d", "quit_twice", show=False, priority=True),
        Binding("ctrl+q", "quit", show=False, priority=True),
    ]

    file: DocumentFile
    current_id: str | None

    def __init__(self, path: Path | str | QueueChoice, *, watch: bool = True) -> None:
        """Open `path`, or with a QueueChoice, ask which file first."""
        super().__init__()
        self.watch_enabled = watch
        self.choice: QueueChoice | None = None
        self.save_timer: Timer | None = None
        # Items whose children are hidden. Only for this session.
        self.folded: set[str] = set()
        # The file's text before each change, newest last, for `u`.
        self.undo_stack: list[str] = []
        # Counts changes to the undo stack. With it, the item last moved with
        # shift+arrows: moving it again, straight after, is the same undo step.
        self.undo_count = 0
        # Whether we've said a blank first line can't be saved, so it's said once.
        self.warned_blank = False
        # When ctrl+d was last pressed.
        self.quit_pressed = -TWICE_WINDOW
        # The item backspace was last pressed on, and when.
        self.delete_pressed: tuple[str, float] | None = None
        self.carried: tuple[str, int] | None = None
        # An item picked up with `m`, and the undo count when it was.
        self.moving_id: str | None = None
        self.picked_at = 0
        # Where to go back to after `n`.
        self.return_focus: Widget | None = None
        self.return_cursor: tuple[int, int] | None = None
        # While the command line is open, where you were when it opened, and
        # what's typed on it.
        self.origin: Origin | None = None
        self.command: Command = Find("", everywhere=True)
        # Whether it points at something, so enter has something to do.
        self.on_target = False
        # The last words found, for n and N, and whether they're still marked.
        self.last_words = ""
        self.marking = False
        if isinstance(path, QueueChoice):
            self.choice = path
        else:
            self.load(path)

    def load(self, path: Path | str) -> None:
        self.file = DocumentFile.open(path)
        first = next(self.file.doc.walk(), None)
        self.current_id = first.id if first else None
        self.title = f"‽ {self.file.path.name}"

    @property
    def loaded(self) -> bool:
        return hasattr(self, "file")

    # -- layout -------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(id="where")
        with Horizontal(id="panes"):
            yield OutlineList(id="outline")
            yield ItemEditor(id="editor")
        yield Static(id="keys")
        with Horizontal(id="command"):
            yield CommandLine(id="command-line", select_on_focus=False)
            yield Static(id="command-hint", markup=False)

    def on_mount(self) -> None:
        if self.choice is None:
            self.start()
        else:
            self.ask_which_queue(self.choice)

    def start(self) -> None:
        self.query_one("#where", Static).update(f"‽ {tilde(self.file.path)}")
        self.refresh_outline()
        self.editor.show(self.current)
        self.outline.focus()
        if self.watch_enabled:
            self.watch_file()

    def ask_which_queue(self, choice: QueueChoice) -> None:
        def chosen(key: str | None) -> None:
            if key not in ("h", "g"):
                self.exit()
                return
            self.load(choice.here if key == "h" else choice.home)
            self.start()

        self.push_screen(
            ChoiceModal(
                f"No queue in {tilde(choice.here.parent.parent)} yet.",
                {
                    "h": "start one here",
                    "g": f"use your global one ({tilde(choice.home)})",
                    "q": "quit",
                },
            ),
            chosen,
        )

    @property
    def outline(self) -> OutlineList:
        return self.query_one(OutlineList)

    @property
    def editor(self) -> ItemEditor:
        return self.query_one(ItemEditor)

    @property
    def current(self) -> Item | None:
        if self.current_id is None or self.current_id not in self.file.doc:
            return None
        return self.file.doc.get(self.current_id)

    @property
    def mode(self) -> Mode:
        if self.moving_id is not None:
            return "MOVE"
        if self.focused is not None and self.editor in self.focused.ancestors_with_self:
            return "NEW" if self.editor.adding else "EDIT"
        return "OUTLINE"

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return not (
            action in MAIN_SCREEN_ACTIONS
            and (isinstance(self.screen, ModalScreen) or self.origin is not None)
        )

    # -- drawing --------------------------------------------------------------

    def refresh_outline(self) -> None:
        self.folded &= self.file.doc.ids()
        self.outline.show_doc(
            self.file.doc,
            self.current_id,
            folded=self.folded,
            new_row=self.new_row() if self.editor.adding else None,
            found=self.found(),
        )
        self.outline.set_class(self.moving_id is not None, "-moving")
        self.refresh_keys()

    def refresh_keys(self) -> None:
        mode = self.mode
        bar = Text()
        bar.append(f" {mode} ", style="bold reverse")
        for key, does in KEY_HINTS[mode]:
            bar.append("  ")
            bar.append(key, style="bold")
            bar.append(f" {does}")
        self.query_one("#keys", Static).update(bar)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        # A click elsewhere closes the command line, staying where it took you.
        if self.origin is not None and not isinstance(event.widget, CommandLine):
            self.close_command_line()
        self.refresh_keys()

    def numbering(self, item: Item) -> tuple[int, int]:
        """An item's number (its place in file order) and the gutter's width."""
        number = next(
            n for n, each in enumerate(self.file.doc.walk(), 1) if each is item
        )
        return number, gutter_width(self.file.doc)

    # -- undo -------------------------------------------------------------------

    def remember(self, before: str) -> None:
        """Remember the file as it was before a change, for `u`."""
        self.undo_stack.append(before)
        del self.undo_stack[:-UNDO_LIMIT]
        self.undo_count += 1

    def undo(self) -> None:
        if not self.undo_stack:
            self.notify("Nothing to undo", timeout=1.5)
            return
        self.file.doc = parse(self.undo_stack.pop())
        self.undo_count += 1
        self.autosave()
        if self.current is None:
            first = next(self.file.doc.walk(), None)
            self.current_id = first.id if first else None
        self.editor.shown_id = None
        self.refresh_outline()
        self.editor.show(self.current)

    # -- keeping the document in step with the editor ---------------------------

    def unsaved_edits(self) -> bool:
        editor = self.editor
        if (
            editor.adding
            or editor.shown_id is None
            or editor.shown_id not in self.file.doc
        ):
            return False
        return editor.text != self.file.doc.get(editor.shown_id).text

    def commit_edits(self) -> None:
        """Copy the editor's text into the document, unless its first line is blank."""
        editor = self.editor
        if (
            editor.adding
            or editor.shown_id is None
            or editor.shown_id not in self.file.doc
        ):
            return
        item = self.file.doc.get(editor.shown_id)
        if editor.text == item.text:
            return
        before = serialise(self.file.doc)
        try:
            ops.set_text(self.file.doc, item.id, editor.text)
        except ValueError:
            if not self.warned_blank:
                self.warned_blank = True
                self.notify(
                    "The first line is what the outline shows, so it can't be blank.",
                    severity="warning",
                    timeout=3,
                )
            return
        self.warned_blank = False
        self.remember(before)

    def autosave(self) -> None:
        try:
            self.file.save()
        except ExternalChange:
            self.on_external_change()
        except OSError as error:
            self.notify(f"Couldn't save: {error}", severity="error")

    def save_edits(self) -> None:
        self.commit_edits()
        if self.file.unsaved:
            self.autosave()
            self.refresh_outline()

    @on(TextArea.Changed, "#text")
    def edited(self) -> None:
        # The outline follows the first line as it's typed.
        if self.editor.adding:
            first = self.editor.text.partition("\n")[0]
            self.outline.redraw_line(
                NEW_ID,
                draw_line(
                    self.new_row()[1],
                    first,
                    box="[ ]",
                    width=gutter_width(self.file.doc),
                ),
            )
            return
        item = self.current
        if item is not None and self.editor.shown_id == item.id:
            number, width = self.numbering(item)
            found = self.found()
            self.outline.redraw_line(
                item.id,
                item_line(
                    item,
                    self.editor.text,
                    number=number,
                    width=width,
                    found=found.pattern if found and item.id in found.ids else None,
                ),
            )
        if self.save_timer is not None:
            self.save_timer.stop()
        self.save_timer = self.set_timer(SAVE_DELAY, self.save_edits)

    def select(self, item_id: str | None) -> None:
        """Make an item the selected one on both sides, keeping the focus where it is."""
        self.save_edits()
        self.current_id = item_id
        self.refresh_outline()
        self.editor.show(self.current)

    @on(OptionList.OptionHighlighted, "#outline")
    def highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if self.moving_id is not None or self.editor.adding:
            return
        item_id = event.option.id
        if item_id in self.file.doc and item_id != self.current_id:
            self.save_edits()
            self.current_id = item_id
            self.editor.show(self.current)

    # -- switching sides ----------------------------------------------------------

    def action_switch(self) -> None:
        """ctrl+n: into the editor from the outline, or back out of it."""
        if self.moving_id is not None:
            return
        if self.mode == "OUTLINE":
            if self.current is None:
                self.start_new("after")
            else:
                self.edit_current()
        else:
            self.back()

    def edit_current(self) -> None:
        """Into the editor, with the cursor at the end of the first line."""
        area = self.editor.text_area
        area.focus()
        area.move_cursor((0, len(area.document.get_line(0))))

    @on(Back)
    def back(self) -> None:
        if self.editor.adding:
            self.finish_new()
            return
        self.save_edits()
        self.outline.focus()

    # -- the outline's keys ---------------------------------------------------------

    @on(OutlineList.Request)
    def outline_key(self, event: OutlineList.Request) -> None:
        if self.moving_id is not None:
            self.move_key(event.action)
            return
        item = self.current
        match event.action:
            case "new_here":
                self.start_new("after")
            case "new_above":
                self.start_new("before")
            case "new_at_bottom":
                self.new_at_bottom()
            case "edit" if item is not None:
                self.edit_current()
            case "left" if item is not None:
                if item.parent_id is None:
                    self.bell()
                else:
                    self.select(item.parent_id)
            case "right" if item is not None:
                self.edit_current()
            case "fold" if item is not None:
                self.fold(item)
            case "fold_all":
                self.fold_all()
            case "nudge_up" | "nudge_down" if item is not None:
                down = event.action == "nudge_down"
                self.change(lambda: self.step(item, down=down), carrying=item.id)
            case "indent" | "outdent" if item is not None:
                outdent = event.action == "outdent"
                self.change(lambda: self.shift(item, outdent=outdent), carrying=item.id)
            case "move" if item is not None:
                self.pick_up(item)
            case "tick" if item is not None:
                self.tick(item)
            case "toggle_box" if item is not None:
                kind = Kind.PLAIN if item.kind is Kind.TODO else Kind.TODO
                self.change(lambda: ops.set_kind(self.file.doc, item.id, kind))
            case "delete" if item is not None:
                self.delete(item)
            case "delete_twice" if item is not None:
                self.delete_twice(item)
            case "undo":
                self.undo()
            case "find":
                self.action_find("/")
            case "goto":
                self.action_find(":")
            case "next_match" | "previous_match":
                self.find_again(1 if event.action == "next_match" else -1)
            case "escape" if self.marking:
                # As vim's :noh, the marks go until the next find.
                self.marking = False
                self.refresh_outline()
            case "help":
                self.push_screen(HelpModal())
            case "open_ref":
                self.action_open_ref()

    def change(
        self, apply: Callable[[], object], *, carrying: str | None = None
    ) -> None:
        """Make a structural change: remember the file first, so `u` can undo
        it, then save and redraw. A move with nowhere to go just beeps.

        Moves of the item `carrying`, one after another, are one undo step,
        so `u` puts it back where it started."""
        self.commit_edits()
        before = serialise(self.file.doc)
        try:
            apply()
        except InvalidMove:
            self.bell()
            return
        if serialise(self.file.doc) == before:
            return
        if carrying is None or self.carried != (carrying, self.undo_count):
            self.remember(before)
        self.carried = None if carrying is None else (carrying, self.undo_count)
        self.autosave()
        self.refresh_outline()
        self.editor.show(self.current)

    def tick(self, item: Item) -> None:
        # A plain item is always open, so ticking gives it a ticked box.
        if item.is_open:
            self.change(lambda: ops.mark_done(self.file.doc, item.id))
        else:
            self.change(lambda: ops.reopen(self.file.doc, item.id))

    @on(OutlineList.TickClicked)
    def clicked_box(self, event: OutlineList.TickClicked) -> None:
        if (
            self.moving_id is not None
            or self.editor.adding
            or event.item_id not in self.file.doc
        ):
            return
        self.select(event.item_id)
        self.tick(self.file.doc.get(event.item_id))

    def step(self, item: Item, *, down: bool) -> None:
        ops.step(self.file.doc, item.id, down=down, folded=self.folded)

    def shift(self, item: Item, *, outdent: bool) -> None:
        if outdent:
            ops.outdent(self.file.doc, item.id)
        else:
            ops.indent(self.file.doc, item.id)
            # Tucked under a folded item, it would vanish: open that up.
            self.folded.discard(item.parent_id or "")

    def fold(self, item: Item) -> None:
        """tab, as in org-mode: fold this item, or unfold it."""
        if not item.children:
            self.bell()
            return
        self.folded ^= {item.id}
        self.refresh_outline()

    def fold_all(self) -> None:
        """shift+tab, as in org-mode: the whole outline goes from top level
        only, to one level open, to everything open, and round again."""
        parents = [item for item in self.file.doc.walk() if item.children]
        stages = [
            {item.id for item in parents},
            {item.id for item in parents if item.depth >= 1},
            set(),
        ]
        stages = [stage for i, stage in enumerate(stages) if stage not in stages[:i]]
        if self.folded in stages:
            self.folded = stages[(stages.index(self.folded) + 1) % len(stages)]
        else:
            self.folded = stages[0]
        # Keep the selection on something that's showing.
        item = self.current
        if item is not None:
            hidden = [a for a in item.ancestors() if a.id in self.folded]
            if hidden:
                self.current_id = hidden[0].id
                self.editor.show(self.current)
        self.refresh_outline()

    def delete(self, item: Item) -> None:
        """x: delete it, asking first if there's more to it than its subject."""

        def confirmed(choice: str | None) -> None:
            if choice == "y":
                self.remove(item)

        count = sum(1 for _ in item.descendants())
        if count or item.body:
            under = (
                f" and the {count} item{'s' if count > 1 else ''} under it"
                if count
                else ""
            )
            self.push_screen(
                ChoiceModal(
                    f"Delete “{item.subject}”{under}? (u undoes it)",
                    {"y": "delete", "n": "keep"},
                ),
                confirmed,
            )
        else:
            self.remove(item)

    def delete_twice(self, item: Item) -> None:
        """backspace: the first press warns, a second straight after, on the
        same item, deletes it. Pressing twice is the asking."""
        now = time.monotonic()
        last = self.delete_pressed
        if last is not None and last[0] == item.id and now - last[1] < TWICE_WINDOW:
            self.delete_pressed = None
            self.remove(item)
            return
        self.delete_pressed = (item.id, now)
        self.notify(
            f"Press backspace again to delete “{item.subject}”", timeout=TWICE_WINDOW
        )

    def remove(self, item: Item) -> None:
        """Delete `item` and what's under it, and select the next row."""
        rows = ops.visible(self.file.doc, self.folded)
        index = rows.index(item)
        gone = {item.id, *(each.id for each in item.descendants())}
        later = [each for each in rows[index + 1 :] if each.id not in gone]
        earlier = rows[:index]
        neighbour = later[0] if later else (earlier[-1] if earlier else None)
        self.change(lambda: ops.delete(self.file.doc, item.id))
        self.select(neighbour.id if neighbour else None)

    # -- the command line: finding, going to and replacing ------------------------

    def action_find(self, start: str = "") -> None:
        """ctrl+p, / and :, as in vim: the command line opens on the bottom
        line, and what's typed moves you as you type it. In the outline it
        works on items; in the editor on the item being edited, with // for
        every item."""
        if self.moving_id is not None or self.editor.adding or self.origin is not None:
            return
        area = self.editor.text_area
        pane: Pane = "editor" if self.focused is area else "outline"
        self.save_edits()
        self.origin = Origin(
            pane, self.current_id, frozenset(self.folded), area.cursor_location
        )
        # The last find's marks go; this one marks its own as it's typed.
        self.marking = False
        line = self.query_one(CommandLine)
        with line.prevent(Input.Changed):
            line.value = start
        line.cursor_position = len(start)
        self.query_one("#keys").display = False
        self.query_one("#command").display = True
        line.focus()
        self.preview(start)

    @property
    def in_this_item(self) -> bool:
        """Whether the command works on the lines of the item being edited:
        / and :12 in the editor."""
        origin = self.origin
        if origin is None or origin.pane != "editor" or origin.current_id is None:
            return False
        match self.command:
            case Find(_, everywhere) | Replace(everywhere=everywhere):
                return not everywhere
            case Jump(_, line):
                return line is None
        return False

    def hits(self, words: str) -> list[Item]:
        """Items with every word somewhere in their text, in file order."""
        return [item for item in self.file.doc.walk() if has_words(item.text, words)]

    def replace_scope(self, replace: Replace) -> list[Item]:
        if self.in_this_item:
            return [self.current] if self.current is not None else []
        return list(self.file.doc.walk())

    def would_change(self, replace: Replace) -> list[Item]:
        return [
            item
            for item in self.replace_scope(replace)
            if ops.replaced(
                item.text,
                replace.old,
                replace.new,
                every=replace.every,
                ignore_case=replace.ignore_case,
            )
            != item.text
        ]

    def found(self) -> Found | None:
        """What to mark in the outline: what the command line finds as it's
        typed, and after a find, what it found (until esc)."""
        if self.origin is not None:
            match self.command:
                case Find(words) if words.strip() and not self.in_this_item:
                    ids = frozenset(item.id for item in self.hits(words))
                    return Found(words_pattern(words), ids)
                case Replace() as replace:
                    ids = frozenset(item.id for item in self.would_change(replace))
                    return Found(replace_pattern(replace), ids)
            return None
        if self.marking and self.last_words:
            ids = frozenset(item.id for item in self.hits(self.last_words))
            return Found(words_pattern(self.last_words), ids)
        return None

    def preview(self, query: str) -> None:
        """Show what the command line's text does, as it's typed: from where
        you were, to the first thing it finds."""
        origin = self.origin
        assert origin is not None
        self.command = parse_command(query)
        self.go_back(origin)
        self.on_target, hint = self.aim(1)
        if not query.lstrip("/:").strip():
            hint = HINTS[origin.pane]
        self.query_one("#command-hint", Static).update(hint)

    def go_back(self, origin: Origin) -> None:
        """Back to where the command line opened."""
        self.folded = set(origin.folded)
        self.select(origin.current_id)
        self.editor.text_area.move_cursor(origin.cursor)

    def aim(self, delta: int) -> tuple[bool, str]:
        """Go to what the command points at: the next match on from here, as
        vim's n does, or with `delta` -1 the one before. Whether there's
        anything there, and what to say about it."""
        area = self.editor.text_area
        command = self.command
        match command:
            case Problem(message):
                return False, message
            case Jump(None, _):
                return False, ""
            case Jump(number, None) if number is not None and self.in_this_item:
                if not 1 <= number <= area.document.line_count:
                    return False, f"There's no line {number}"
                self.select_text(number - 1, 0, 0)
                return True, ""
            case Jump(number, line):
                item = next(
                    (
                        each
                        for n, each in enumerate(self.file.doc.walk(), 1)
                        if n == number
                    ),
                    None,
                )
                if item is None:
                    return False, f"There's no item {number}"
                self.reveal(item.id)
                if line is not None:
                    self.select_text(min(line, area.document.line_count) - 1, 0, 0)
                return True, ""
            case Find(words) if not words.strip():
                return False, ""
            case Find(words) if self.in_this_item:
                return self.aim_at_line(words, delta)
            case Find(words):
                hits = self.hits(words)
                hit = self.next_hit(hits, self.current_id, delta)
                if hit is None:
                    return False, "Nothing matches"
                self.reveal(hit.id)
                self.mark_in_editor(words_pattern(words))
                return True, f"{hits.index(hit) + 1} of {len(hits)}"
            case Replace() as replace:
                count = len(self.would_change(replace))
                if not count:
                    where = "this item" if self.in_this_item else "any item"
                    return False, f"Nothing in {where} matches"
                plural = "s" if count > 1 else ""
                return True, f"enter replaces in {count} item{plural} (u undoes it)"

    def next_hit(self, hits: list[Item], after: str | None, delta: int) -> Item | None:
        """The first of `hits` after the item `after` in file order (before
        it, with `delta` -1), round the end if need be."""
        if not hits:
            return None
        order = {item.id: n for n, item in enumerate(self.file.doc.walk())}
        here = order.get(after or "", -1)
        if delta > 0:
            return next((hit for hit in hits if order[hit.id] > here), hits[0])
        return next((hit for hit in reversed(hits) if order[hit.id] < here), hits[-1])

    def aim_at_line(self, words: str, delta: int) -> tuple[bool, str]:
        """The next line of the item being edited with every word in it."""
        area = self.editor.text_area
        terms = words.lower().split()
        spots = [
            (row, line.lower().find(terms[0]))
            for row, line in enumerate(area.text.split("\n"))
            if all(term in line.lower() for term in terms)
        ]
        if not spots:
            return False, "Nothing in this item matches"
        here = min(area.selection.start, area.selection.end)
        if delta > 0:
            spot = next((each for each in spots if each > here), spots[0])
        else:
            spot = next((each for each in reversed(spots) if each < here), spots[-1])
        self.select_text(*spot, len(terms[0]))
        return True, f"{spots.index(spot) + 1} of {len(spots)}"

    def reveal(self, item_id: str) -> None:
        """Select an item, opening up whatever it's folded inside."""
        for ancestor in self.file.doc.get(item_id).ancestors():
            self.folded.discard(ancestor.id)
        self.select(item_id)

    def select_text(self, row: int, column: int, length: int) -> None:
        area = self.editor.text_area
        area.move_cursor((row, column))
        area.move_cursor((row, column + length), select=True)

    def mark_in_editor(self, pattern: re.Pattern[str]) -> None:
        """Select the first thing `pattern` finds in the editor."""
        text = self.editor.text_area.text
        hit = pattern.search(text)
        if hit is None:
            return
        row = text.count("\n", 0, hit.start())
        column = hit.start() - (text.rfind("\n", 0, hit.start()) + 1)
        self.select_text(row, column, hit.end() - hit.start())

    @on(Input.Changed, "#command-line")
    def command_changed(self, event: Input.Changed) -> None:
        if self.origin is not None:
            self.preview(event.value)

    @on(CommandLine.Step)
    def command_step(self, event: CommandLine.Step) -> None:
        """↓ and ↑: the next or previous match."""
        if not isinstance(self.command, Find):
            self.bell()
            return
        found, hint = self.aim(event.delta)
        if found:
            self.query_one("#command-hint", Static).update(hint)
        else:
            self.bell()

    @on(CommandLine.Cancel)
    def command_cancelled(self) -> None:
        """esc: back where you were."""
        origin = self.origin
        if origin is None:
            return
        self.command = Find("", everywhere=True)
        self.go_back(origin)
        self.close_command_line()
        self.focus_pane(origin.pane)
        self.editor.text_area.move_cursor(origin.cursor)

    @on(Input.Submitted, "#command-line")
    def command_entered(self, event: Input.Submitted) -> None:
        """enter: stay where it took you, or do the replace."""
        event.stop()
        origin = self.origin
        if origin is None:
            return
        command = self.command
        if isinstance(command, Find) and not command.words.strip() and self.last_words:
            # As in vim, / on its own finds the last thing again.
            self.command = command = Find(self.last_words, command.everywhere)
            self.go_back(origin)
            self.on_target, _ = self.aim(1)
        if not self.on_target:
            self.bell()
            return
        in_this_item = self.in_this_item
        self.close_command_line()
        area = self.editor.text_area
        match command:
            case Find(words):
                self.last_words = words
                self.marking = not in_this_item
                self.refresh_outline()
            case Replace():
                self.focus_pane(origin.pane)
                self.replace_text(command, in_this_item)
                return
        editing = origin.pane == "editor" or (
            isinstance(command, Jump) and command.line is not None
        )
        self.focus_pane("editor" if editing else "outline")
        if editing:
            area.move_cursor(min(area.selection.start, area.selection.end))

    def close_command_line(self) -> None:
        """Close the command line, staying where it took you."""
        self.origin = None
        self.query_one("#command").display = False
        self.query_one("#keys").display = True
        self.refresh_outline()

    def focus_pane(self, pane: Pane) -> None:
        if pane == "editor" and self.editor.text_area.display:
            self.editor.text_area.focus()
        else:
            self.outline.focus()

    def find_again(self, delta: int) -> None:
        """n and N, as in vim: the next or previous item with the last words found."""
        if not self.last_words:
            self.notify("Nothing found yet: / finds", timeout=1.5)
            return
        hit = self.next_hit(self.hits(self.last_words), self.current_id, delta)
        if hit is None:
            self.notify(f"Nothing matches “{self.last_words}”", timeout=1.5)
            return
        self.marking = True
        self.reveal(hit.id)
        self.mark_in_editor(words_pattern(self.last_words))

    def replace_text(self, replace: Replace, in_this_item: bool) -> None:
        doc = self.file.doc
        if in_this_item:
            ids = [self.current_id] if self.current_id is not None else []
        else:
            ids = [item.id for item in doc.walk()]
        area = self.editor.text_area
        cursor = area.cursor_location
        changed: list[Item] = []
        self.change(
            lambda: changed.extend(
                ops.replace(
                    doc,
                    replace.old,
                    replace.new,
                    ids,
                    every=replace.every,
                    ignore_case=replace.ignore_case,
                )
            )
        )
        if self.focused is area:
            last = area.document.line_count - 1
            row = min(cursor[0], last)
            area.move_cursor((row, min(cursor[1], len(area.document.get_line(row)))))
        plural = "s" if len(changed) != 1 else ""
        self.notify(f"Replaced in {len(changed)} item{plural}", timeout=2)

    # -- adding ---------------------------------------------------------------------

    def start_new(self, place: Place) -> None:
        self.save_edits()
        self.editor.start_new(self.current, place)
        self.refresh_outline()

    def new_at_bottom(self) -> None:
        """n: a new top-level item at the end. Then back on the item you were on."""
        area = self.editor.text_area
        self.return_focus = self.focused
        self.return_cursor = area.cursor_location if self.focused is area else None
        self.save_edits()
        self.editor.start_new(self.current, "end")
        self.editor.jotting = True
        self.refresh_outline()

    def new_row(self) -> tuple[int, int]:
        """Where the blank row for a new item goes in the outline, and its depth."""
        rows = ops.visible(self.file.doc, self.folded)
        anchor = self.current
        if anchor is None or self.editor.place == "end":
            return len(rows), 0
        position = rows.index(anchor)
        if self.editor.place == "before":
            return position, anchor.depth
        position += 1 + sum(1 for row in rows if anchor in row.ancestors())
        depth = anchor.depth + (1 if self.editor.place == "under" else 0)
        return position, depth

    def finish_new(self) -> None:
        """Keep the new item if it has a first line. From enter, land on it;
        from n, go back to where you were."""
        doc = self.file.doc
        anchor = self.current
        text = self.editor.text
        returning = self.editor.jotting
        before = serialise(doc)
        try:
            if anchor is None or self.editor.place == "end":
                item = ops.add(doc, text, kind=Kind.TODO)
            elif self.editor.place == "under":
                item = ops.add(doc, text, parent_id=anchor.id, kind=Kind.TODO)
            else:
                item = ops.add(doc, text, as_sibling_of=anchor.id, kind=Kind.TODO)
                if self.editor.place == "before":
                    ops.reorder(doc, item.id, anchor.parent.children.index(anchor))
        except ValueError:
            # Nothing typed (or only blank lines): no item, and the blank row goes.
            item = None
        if item is not None:
            self.remember(before)
            self.autosave()
        if returning or item is None:
            self.back_where_you_were()
            return
        self.current_id = item.id
        self.editor.show(item)
        self.refresh_outline()
        self.outline.focus()

    def back_where_you_were(self) -> None:
        """The item you were on, with the focus and cursor as they were."""
        self.editor.show(self.current)
        self.refresh_outline()
        target = self.return_focus
        cursor = self.return_cursor
        self.return_focus = self.return_cursor = None
        area = self.editor.text_area
        if target is area and area.display:
            area.focus()
            if cursor is not None:
                area.move_cursor(cursor)
        else:
            self.outline.focus()
        self.refresh_keys()

    # -- m: moving --------------------------------------------------------------------

    def pick_up(self, item: Item) -> None:
        """m: the arrows carry the item (and everything under it) until it's dropped."""
        self.commit_edits()
        self.moving_id = item.id
        self.carried = None  # its moves from here on are one undo step of their own
        self.picked_at = self.undo_count
        self.refresh_outline()

    def move_key(self, action: str) -> None:
        assert self.moving_id is not None
        item = self.file.doc.get(self.moving_id)
        match action:
            case "nudge_up" | "nudge_down":
                down = action == "nudge_down"
                self.change(lambda: self.step(item, down=down), carrying=item.id)
            case "outdent" | "left":
                self.change(lambda: self.shift(item, outdent=True), carrying=item.id)
            case "indent" | "right":
                self.change(lambda: self.shift(item, outdent=False), carrying=item.id)
            case "move" | "new_here":
                self.drop()
            case "escape" | "undo":
                self.put_back()
            case _:
                self.bell()

    def drop(self) -> None:
        self.moving_id = None
        self.refresh_outline()

    def put_back(self) -> None:
        """esc while moving: back where it was picked up."""
        self.moving_id = None
        if self.undo_count != self.picked_at:
            self.undo()
        else:
            self.refresh_outline()

    # -- opening references and quitting ------------------------------------------

    def action_open_ref(self) -> None:
        """Open the file:line reference on the cursor's line (else the first) in an editor."""
        if self.current is None:
            return
        area = self.editor.text_area
        row = area.cursor_location[0] if self.focused is area else 0
        ref = ref_at(area.text, row)
        if ref is None:
            self.notify("No file:line in this item, e.g. src/app.py:30")
            return
        self.open_ref(ref)

    @on(OutlineList.OpenRef)
    def clicked_ref(self, event: OutlineList.OpenRef) -> None:
        self.open_ref(find_refs(event.ref)[0])

    def open_ref(self, ref: FileRef) -> None:
        """Open the file at the line in your editor: one with its own window
        (VS Code and the like) opens alongside; one in the terminal takes
        over until you quit it."""
        path = resolve(ref, project_folder(self.file.path))
        if not path.exists():
            self.notify(f"Can't find {path}", severity="warning")
            return
        self.save_edits()
        editor = choose_editor(os.environ)
        argv = editor_command(editor, path, ref.line)
        try:
            if windowed(editor):
                subprocess.run(argv, check=False, capture_output=True)
            else:
                with self.suspend():
                    subprocess.run(argv, check=False)
        except OSError as error:
            self.notify(f"Couldn't run {editor}: {error}", severity="error")

    async def action_quit_twice(self) -> None:
        """ctrl+d: the first press warns, a second straight after quits."""
        now = time.monotonic()
        if now - self.quit_pressed < TWICE_WINDOW:
            await self.action_quit()
            return
        self.quit_pressed = now
        self.notify("Press ctrl+d again to quit", timeout=TWICE_WINDOW)

    async def action_quit(self) -> None:
        if not self.loaded:
            self.exit()
            return
        if self.editor.adding:
            self.finish_new()
        self.moving_id = None
        self.commit_edits()
        if self.file.unsaved:
            try:
                self.file.save()
            except ExternalChange:
                self.on_external_change()
                return
        self.exit()

    # -- the file changing under us ------------------------------------------

    @work(exclusive=True, group="watch")
    async def watch_file(self) -> None:
        async for _ in self.file.watch():
            self.on_external_change()

    def on_external_change(self) -> None:
        if not self.file.changed_on_disk():
            return
        if isinstance(self.screen, ChoiceModal):
            return
        if not (self.unsaved_edits() or self.file.unsaved):
            self.reload_from_disk()
            return

        def resolve(choice: str | None) -> None:
            if choice == "r":
                self.reload_from_disk()
            elif choice == "k":
                self.commit_edits()
                self.file.save(force=True)
                self.notify("Kept your version")

        self.push_screen(
            ChoiceModal(
                f"{self.file.path.name} changed on disk, and you have unsaved edits.",
                {"r": "reload (discard mine)", "k": "keep mine (overwrite)"},
            ),
            resolve,
        )

    def reload_from_disk(self) -> None:
        self.file.reload()
        self.undo_stack.clear()
        self.undo_count += 1
        if self.moving_id not in self.file.doc:
            self.moving_id = None
        self.picked_at = self.undo_count
        if self.current_id not in self.file.doc:
            first = next(self.file.doc.walk(), None)
            self.current_id = first.id if first else None
        self.editor.shown_id = None
        self.refresh_outline()
        self.editor.show(self.current)
        self.notify("Reloaded: the file changed on disk", timeout=2)
