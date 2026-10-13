"""The editor: the selected item's whole text, where you type. Its first
line is the subject the outline shows; the rest is the body."""

from __future__ import annotations

from typing import Literal

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import TextArea

from ..core import Item
from .highlight import extra_highlights

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
            show_line_numbers=True,
            language="markdown",
        )

    def _build_highlight_map(self) -> None:
        # Textual's markdown highlighting, then inline markup and fenced code
        # (highlight.py), then the first line, the subject the outline
        # shows, in bold.
        super()._build_highlight_map()
        for row, extra in extra_highlights(self.text).items():
            self._highlights[row].extend(extra)
        self._highlights[0].append((0, None, "bold"))

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
        yield ItemText()

    @property
    def text_area(self) -> ItemText:
        return self.query_one(ItemText)

    @property
    def text(self) -> str:
        return self.text_area.text

    def show(self, item: Item | None) -> None:
        """Show an item (without moving the focus)."""
        self.adding = False
        self.jotting = False
        self.text_area.display = item is not None
        if item is None:
            self.shown_id = None
            return
        if self.shown_id != item.id or self.text_area.text != item.text:
            with self.text_area.prevent(TextArea.Changed):
                self.text_area.load_text(item.text)
        self.shown_id = item.id

    def start_new(self, anchor: Item | None, place: Place) -> None:
        """Flip to a blank item and put the focus in it."""
        self.adding = True
        self.place = place
        self.text_area.display = True
        with self.text_area.prevent(TextArea.Changed):
            self.text_area.load_text("")
        self.text_area.focus()
