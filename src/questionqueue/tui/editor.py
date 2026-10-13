"""The editor: the selected item's whole text, where you type. Its first
line is the subject the outline shows; the rest is the body."""

from __future__ import annotations

from typing import Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Static, TextArea

from ..core import Item
from .render import MUTED

# Where a new item will go, relative to the selected one.
type Place = Literal["after", "before", "under", "end"]


class Back(Message):
    """esc: back to the outline."""


class ItemText(TextArea):
    """An ordinary text box: enter is a new line, tab indents (for code)."""

    def __init__(self) -> None:
        super().__init__(
            id="text",
            soft_wrap=True,
            tab_behavior="indent",
            show_line_numbers=False,
            placeholder="The first line is what the outline shows.\n"
            "Anything after it is the rest of the item.",
        )

    async def _on_key(self, event: events.Key) -> None:
        # TextArea handles escape itself (moving the focus on), so catch it first.
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self.post_message(Back())
            return
        await super()._on_key(event)


class ItemEditor(Vertical):
    """Shows one item's text for editing, or a blank one being added."""

    adding: bool = False
    # A jot: a passing thought, placed afterwards, then back where you were.
    jotting: bool = False
    place: Place = "after"
    shown_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="editor-head")
        yield ItemText()

    @property
    def text_area(self) -> ItemText:
        return self.query_one(ItemText)

    @property
    def text(self) -> str:
        return self.text_area.text

    def head(self, words: str) -> None:
        """A line above the text, for the odd thing worth saying; hidden when empty."""
        head = self.query_one("#editor-head", Static)
        head.update(Text(words, style=MUTED))
        head.display = bool(words)

    def show(self, item: Item | None) -> None:
        """Show an item (without moving the focus)."""
        self.adding = False
        self.jotting = False
        self.text_area.display = item is not None
        if item is None:
            self.shown_id = None
            self.head("Nothing selected.")
            return
        self.head("")
        if self.shown_id != item.id or self.text_area.text != item.text:
            with self.text_area.prevent(TextArea.Changed):
                self.text_area.load_text(item.text)
        self.shown_id = item.id

    def start_new(self, anchor: Item | None, place: Place) -> None:
        """Flip to a blank item and put the focus in it."""
        self.adding = True
        self.place = place
        self.text_area.display = True
        # No heading: the blank row in the outline shows where it will go.
        self.head("")
        with self.text_area.prevent(TextArea.Changed):
            self.text_area.load_text("")
        self.text_area.focus()
