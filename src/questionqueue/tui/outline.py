"""The outline: every item by its first line. For moving around and
arranging; keys here never type."""

from __future__ import annotations

from collections.abc import Collection

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option, OptionDoesNotExist

from ..core import Document
from .render import MUTED, draw_line, gutter_width, outline

# The option for an item still being written, before it's in the document.
NEW_ID = "--new--"

GUIDE = """\
Nothing here yet. Press enter to write your first item.

This side is the outline: you move around it and arrange it, and keys
are commands. The other side is where you write; → or e goes there,
and esc comes back.

enter adds an item where you are, n adds one at the bottom, m picks one
up to move it, and u undoes. ← folds, and → unfolds."""


class OutlineList(OptionList):
    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("left", "request('left')", show=False),
        Binding("right", "request('right')", show=False),
        Binding("shift+up", "request('nudge_up')", show=False),
        Binding("shift+down", "request('nudge_down')", show=False),
        Binding("tab,shift+right", "request('indent')", show=False),
        Binding("shift+tab,shift+left", "request('outdent')", show=False),
        Binding("enter", "request('new_here')", show=False),
        # alt+enter reaches us everywhere (see keys.py); shift+enter only
        # where the terminal reports it as its own key.
        Binding("alt+enter,shift+enter", "request('new_above')", show=False),
        Binding("n", "request('new_at_bottom')", show=False),
        Binding("e,i", "request('edit')", show=False),
        Binding("m", "request('move')", show=False),
        Binding("space", "request('tick')", show=False),
        Binding("t", "request('toggle_box')", show=False),
        Binding("x", "request('delete')", show=False),
        Binding("u", "request('undo')", show=False),
        Binding("slash", "request('find')", show=False),
        Binding("colon", "request('goto')", show=False),
        Binding("question_mark", "request('help')", show=False),
        Binding("o", "request('open_ref')", show=False),
        Binding("q", "request('quit')", show=False),
        Binding("escape", "request('escape')", show=False),
    ]

    class Request(Message):
        """An outline key was pressed; the app does the work."""

        def __init__(self, action: str) -> None:
            super().__init__()
            self.action = action

    class OpenRef(Message):
        """A file:line in the outline was clicked."""

        def __init__(self, ref: str) -> None:
            super().__init__()
            self.ref = ref

    def action_request(self, action: str) -> None:
        self.post_message(self.Request(action))

    async def _on_click(self, event: events.Click) -> None:
        # OptionList selects the row as well, after this.
        ref = event.style.meta.get("ref")
        if ref is not None:
            self.post_message(self.OpenRef(ref))

    # While an item is picked up, up and down carry it, not the cursor.

    def action_cursor_up(self) -> None:
        if self.has_class("-moving"):
            self.action_request("nudge_up")
        else:
            super().action_cursor_up()

    def action_cursor_down(self) -> None:
        if self.has_class("-moving"):
            self.action_request("nudge_down")
        else:
            super().action_cursor_down()

    def show_doc(
        self,
        doc: Document,
        selected_id: str | None,
        *,
        folded: Collection[str] = (),
        new_row: tuple[int, int] | None = None,
    ) -> None:
        """Draw the items showing. `new_row` is (position, depth) for a blank
        row where an item being written will go; it's selected while it's there."""
        options = [Option(text, id=item_id) for text, item_id in outline(doc, folded)]
        if new_row is not None:
            position, depth = new_row
            blank = draw_line(depth, "", width=gutter_width(doc))
            options.insert(position, Option(blank, id=NEW_ID))
            selected_id = NEW_ID
        if not options:
            options = [Option(Text(GUIDE, style=MUTED), disabled=True)]
        with self.prevent(OptionList.OptionHighlighted):
            self.set_options(options)
            if selected_id is not None and self.has(selected_id):
                self.highlighted = self.get_option_index(selected_id)
        if self.highlighted is not None:
            self.scroll_to_highlight()

    def has(self, option_id: str) -> bool:
        try:
            self.get_option_index(option_id)
        except OptionDoesNotExist:
            return False
        return True

    def redraw_line(self, option_id: str, text: Text) -> None:
        """Replace one line, e.g. while its item is being typed."""
        if self.has(option_id):
            self.replace_option_prompt(option_id, text)
