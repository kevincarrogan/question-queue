from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
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
from textual.widgets import OptionList, Static, TextArea

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
from .editor import Back, ItemEditor, Place
from .modals import (
    Choice,
    ChoiceModal,
    Entry,
    GoToItem,
    GoToLine,
    HelpModal,
    PaletteModal,
    Pane,
    Replace,
)
from .outline import NEW_ID, OutlineList
from .render import draw_line, gutter_width, item_line

keys.install()

# How long typing has to pause before it's saved.
SAVE_DELAY = 1.0

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
        ("→ e", "edit"),
        ("m", "move"),
        ("space", "tick"),
        ("u", "undo"),
        ("^p", "find"),
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
        ("tab", "in"),
        ("shift+tab", "out"),
        ("enter", "drop it here"),
        ("esc", "put it back"),
    ],
}


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
        # An item picked up with `m`.
        self.moving_id: str | None = None
        # Where to go back to after `n`.
        self.return_focus: Widget | None = None
        self.return_cursor: tuple[int, int] | None = None
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
            action in MAIN_SCREEN_ACTIONS and isinstance(self.screen, ModalScreen)
        )

    # -- drawing --------------------------------------------------------------

    def refresh_outline(self) -> None:
        self.folded &= self.file.doc.ids()
        self.outline.show_doc(
            self.file.doc,
            self.moving_id or self.current_id,
            folded=self.folded,
            new_row=self.new_row() if self.editor.adding else None,
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
        self.refresh_keys()

    def numbering(self, item: Item) -> tuple[int, int]:
        """An item's number (its place in file order) and the gutter's width."""
        number = next(
            n for n, each in enumerate(self.file.doc.walk(), 1) if each is item
        )
        return number, gutter_width(self.file.doc)

    # -- undo -------------------------------------------------------------------

    def snapshot(self) -> None:
        """Remember the file as it is, before a change."""
        self.undo_stack.append(serialise(self.file.doc))
        del self.undo_stack[:-UNDO_LIMIT]

    def undo(self) -> None:
        if not self.undo_stack:
            self.notify("Nothing to undo", timeout=1.5)
            return
        self.file.doc = parse(self.undo_stack.pop())
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
            editor.head(
                "The first line is what the outline shows, so it can't be blank."
            )
            return
        self.undo_stack.append(before)
        del self.undo_stack[:-UNDO_LIMIT]
        editor.head("")

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
            first, _, rest = self.editor.text.partition("\n")
            self.outline.redraw_line(
                NEW_ID,
                draw_line(
                    self.new_row()[1],
                    first,
                    more=bool(rest.strip()),
                    width=gutter_width(self.file.doc),
                ),
            )
            return
        item = self.current
        if item is not None and self.editor.shown_id == item.id:
            number, width = self.numbering(item)
            self.outline.redraw_line(
                item.id, item_line(item, self.editor.text, number=number, width=width)
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
                self.left(item)
            case "right" if item is not None:
                self.right(item)
            case "nudge_up" | "nudge_down" if item is not None:
                self.change(lambda: self.step(item, down=event.action == "nudge_down"))
            case "indent" | "outdent" if item is not None:
                self.change(lambda: self.shift(item, outdent=event.action == "outdent"))
            case "move" if item is not None:
                self.pick_up(item)
            case "tick" if item is not None:
                # A plain item is always open, so space gives it a ticked box.
                if item.is_open:
                    self.change(lambda: ops.mark_done(self.file.doc, item.id))
                else:
                    self.change(lambda: ops.reopen(self.file.doc, item.id))
            case "toggle_box" if item is not None:
                kind = Kind.PLAIN if item.kind is Kind.TODO else Kind.TODO
                self.change(lambda: ops.set_kind(self.file.doc, item.id, kind))
            case "delete" if item is not None:
                self.delete(item)
            case "undo":
                self.undo()
            case "find":
                self.action_find("/")
            case "goto":
                self.action_find(":")
            case "help":
                self.push_screen(HelpModal())
            case "open_ref":
                self.action_open_ref()
            case "quit":
                self.call_next(self.action_quit)

    def change(self, apply: Callable[[], object]) -> None:
        """Make a structural change: remember the file first, so `u` can undo
        it, then save and redraw. A move with nowhere to go just beeps."""
        self.commit_edits()
        before = serialise(self.file.doc)
        try:
            apply()
        except InvalidMove:
            self.bell()
            return
        if serialise(self.file.doc) == before:
            return
        self.undo_stack.append(before)
        del self.undo_stack[:-UNDO_LIMIT]
        self.autosave()
        self.refresh_outline()
        self.editor.show(self.current)

    def step(self, item: Item, *, down: bool) -> None:
        ops.step(self.file.doc, item.id, down=down, folded=self.folded)

    def shift(self, item: Item, *, outdent: bool) -> None:
        if outdent:
            ops.outdent(self.file.doc, item.id)
        else:
            ops.indent(self.file.doc, item.id)
            # Tucked under a folded item, it would vanish: open that up.
            self.folded.discard(item.parent_id or "")

    def left(self, item: Item) -> None:
        """Fold this item, or if it's folded or has nothing under it, go to its parent."""
        if item.children and item.id not in self.folded:
            self.folded.add(item.id)
            self.refresh_outline()
        elif item.parent_id is not None:
            self.select(item.parent_id)
        else:
            self.bell()

    def right(self, item: Item) -> None:
        """Unfold this item, or if there's nothing folded, edit it: the
        editor is the pane to the right. (↓ already goes to the first child.)"""
        if item.children and item.id in self.folded:
            self.folded.discard(item.id)
            self.refresh_outline()
        else:
            self.edit_current()

    def delete(self, item: Item) -> None:
        def confirmed(choice: str | None) -> None:
            if choice != "y":
                return
            rows = ops.visible(self.file.doc, self.folded)
            index = rows.index(item)
            gone = {item.id, *(each.id for each in item.descendants())}
            later = [each for each in rows[index + 1 :] if each.id not in gone]
            earlier = rows[:index]
            neighbour = later[0] if later else (earlier[-1] if earlier else None)
            self.change(lambda: ops.delete(self.file.doc, item.id))
            self.select(neighbour.id if neighbour else None)

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
            confirmed("y")

    # -- finding --------------------------------------------------------------------

    def action_find(self, start: str = "") -> None:
        """ctrl+p: the palette. In the outline it works on items; in the
        editor on the item being edited, with // for every item."""
        if self.moving_id is not None or self.editor.adding:
            return
        area = self.editor.text_area
        pane: Pane = "editor" if self.focused is area else "outline"
        self.save_edits()
        entries = [
            Entry(number, item.text, item.id)
            for number, item in enumerate(self.file.doc.walk(), 1)
        ]

        def chosen(choice: Choice | None) -> None:
            match choice:
                case GoToItem(item_id) if item_id in self.file.doc:
                    # Open up whatever it's folded inside.
                    for ancestor in self.file.doc.get(item_id).ancestors():
                        self.folded.discard(ancestor.id)
                    self.select(item_id)
                case GoToLine(row, column):
                    area.focus()
                    area.move_cursor((row, column))
                case Replace():
                    self.replace_text(choice, pane)

        self.push_screen(
            PaletteModal(entries, pane=pane, start=start, current_id=self.current_id),
            chosen,
        )

    def replace_text(self, replace: Replace, pane: Pane) -> None:
        doc = self.file.doc
        if replace.everywhere or pane == "outline":
            ids = [item.id for item in doc.walk()]
        else:
            ids = [self.current_id] if self.current_id is not None else []
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
        if pane == "editor":
            area.focus()
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
                item = ops.add(doc, text)
            elif self.editor.place == "under":
                item = ops.add(doc, text, parent_id=anchor.id)
            else:
                item = ops.add(doc, text, as_sibling_of=anchor.id)
                if self.editor.place == "before":
                    ops.reorder(doc, item.id, anchor.parent.children.index(anchor))
        except ValueError:
            # Nothing typed (or only blank lines): no item, and the blank row goes.
            item = None
        if item is not None:
            self.undo_stack.append(before)
            del self.undo_stack[:-UNDO_LIMIT]
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

    # -- moving -----------------------------------------------------------------------

    def pick_up(self, item: Item) -> None:
        """m: carry an item (and everything under it) with the arrow keys."""
        self.commit_edits()
        self.snapshot()
        self.moving_id = item.id
        self.refresh_outline()

    def move_key(self, action: str) -> None:
        assert self.moving_id is not None
        item = self.file.doc.get(self.moving_id)
        try:
            match action:
                case "nudge_up" | "nudge_down":
                    self.step(item, down=action == "nudge_down")
                case "indent" | "outdent":
                    self.shift(item, outdent=action == "outdent")
                case "new_here" | "move":
                    self.drop()
                    return
                case "escape":
                    self.put_back()
                    return
                case _:
                    self.bell()
                    return
        except InvalidMove:
            self.bell()
            return
        self.autosave()
        self.refresh_outline()

    def drop(self) -> None:
        moved = self.moving_id
        self.moving_id = None
        if self.undo_stack and self.undo_stack[-1] == serialise(self.file.doc):
            self.undo_stack.pop()  # it didn't move after all
        self.current_id = moved
        self.refresh_outline()
        self.editor.show(self.current)

    def put_back(self) -> None:
        """esc while moving: back where it was picked up from."""
        self.moving_id = None
        self.undo()

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

    async def action_quit(self) -> None:
        if not self.loaded:
            self.exit()
            return
        if self.editor.adding:
            self.finish_new()
        if self.moving_id is not None:
            self.drop()
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
        if self.current_id not in self.file.doc:
            first = next(self.file.doc.walk(), None)
            self.current_id = first.id if first else None
        if self.moving_id not in self.file.doc:
            self.moving_id = None
        self.editor.shown_id = None
        self.refresh_outline()
        self.editor.show(self.current)
        self.notify("Reloaded: the file changed on disk", timeout=2)
