from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label


class ChoiceModal(ModalScreen[str | None]):
    """A message with single-key choices, e.g. {"y": "delete", "n": "cancel"}."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, message: str, choices: dict[str, str]) -> None:
        super().__init__()
        self.message = message
        self.choices = choices

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.message, markup=False)
            yield Label(
                "   ".join(
                    f"[b]{key}[/b] {label}" for key, label in self.choices.items()
                ),
                classes="choices",
            )

    def on_key(self, event: events.Key) -> None:
        if event.key in self.choices:
            event.stop()
            self.dismiss(event.key)

    def action_cancel(self) -> None:
        self.dismiss(None)


KEYS = """\
In the outline (keys are commands, nothing types; w a s d are the arrows)
  ↑ ↓  j k        move between items
  ←               to the parent
  →  ctrl+n       edit the selected item
  tab             fold or unfold it
  shift+tab       everything: top level only → one level open → all open
  enter           new item here          alt+enter   new item above
  b               new item at the bottom, then back where you were
  m               pick it up: ↑ ↓ carry it, ← → out / in a level,
                  m or enter drops it, esc puts it back
  shift+↑ ↓       move it (and what's under it) without picking it up
  shift+← →       out / in a level
  space           tick or untick, and the boxes under it; [-] is partly done;
                  clicking the box does it too
  t               add or remove the box
  x               delete                    u   undo (a run of moves is one)
  backspace       twice: delete without asking (the first one warns)
  /  :  ctrl+p    the command line, as in vim, moving you as you type:
                  /words find, :34 item 34, :34:12 its line 12,
                  /old/new/ replace in every item (g every match, i any case);
                  ↑ ↓ next or previous match, enter stays, esc goes back
  n  N            next or previous match of the last find; esc unmarks
  o  click        open the file:line in the item in your editor

In the editor (where you type)
  the first line is what the outline shows; enter is a new line
  esc  ctrl+n     back to the outline       ctrl+o  open the file:line here
  ctrl+p          the command line: /words in this item, //words in every item,
                  :12 line 12, :34:12 line 12 of item 34,
                  /old/new/ replace here, //old/new/ in every item

Anywhere
  ctrl+d ctrl+d   quit (the first one warns)"""


class HelpModal(ModalScreen[None]):
    """Every key. Any key closes it."""

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog help"):
            yield Label(KEYS, markup=False)

    def on_key(self, event: events.Key) -> None:
        event.stop()
        self.dismiss(None)
