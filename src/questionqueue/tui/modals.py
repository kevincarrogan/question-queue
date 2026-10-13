from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from ..core import ops
from .render import MUTED

# How many matches the palette lists at once.
MATCH_LIMIT = 50


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


@dataclass(frozen=True)
class Entry:
    """One item as the palette sees it."""

    number: int
    text: str  # the whole text, which is what's searched
    item_id: str

    @property
    def subject(self) -> str:
        return self.text.split("\n", 1)[0]


type Pane = Literal["outline", "editor"]

# -- what can be typed ---------------------------------------------------------------


@dataclass(frozen=True)
class Find:
    words: str
    everywhere: bool  # // (or plain words): every item; / in the editor: this item


@dataclass(frozen=True)
class Jump:
    number: int | None  # None while only `:` is typed
    line: int | None = None  # :34:12, line 12 of item 34


@dataclass(frozen=True)
class Replace:
    old: str
    new: str
    everywhere: bool
    every: bool  # g: every match, not just the first on each line
    ignore_case: bool  # i


@dataclass(frozen=True)
class Problem:
    message: str


type Command = Find | Jump | Replace | Problem

# old/new/ with optional g and i after the closing slash; \/ is a slash
# inside either part. Without the closing slash it's a search, so a path
# like /src/app.py can be found as it is.
REPLACE_RE = re.compile(
    r"^(?P<old>(?:\\.|[^/\\])+)/(?P<new>(?:\\.|[^/\\])*)/(?P<flags>[A-Za-z]*)$"
)


# :34, or :34:12 for line 12 of item 34.
JUMP_RE = re.compile(r"^:\s*(?P<number>\d*)\s*(?::\s*(?P<line>\d*))?\s*$")


def parse_command(query: str) -> Command:
    """`:34` jump (`:34:12` to a line of it); `/words` or `//words` find; `/old/new/` or `//old/new/`
    replace, with g and i flags; anything else finds in every item."""
    if query.startswith(":"):
        m = JUMP_RE.match(query)
        if m is None:
            return Problem("After : type a number, or item:line like :34:12")
        number = int(m["number"]) if m["number"] else None
        line = int(m["line"]) if m["line"] else None
        return Jump(number, line)
    if query.startswith("//"):
        everywhere, rest = True, query[2:]
    elif query.startswith("/"):
        everywhere, rest = False, query[1:]
    else:
        return Find(query.strip(), everywhere=True)
    m = REPLACE_RE.match(rest)
    if m is None:
        return Find(rest.replace("\\/", "/").strip(), everywhere)
    flags = m["flags"]
    if set(flags) - set("gi"):
        return Problem("The flags are g (every match) and i (ignore case)")
    return Replace(
        m["old"].replace("\\/", "/"),
        m["new"].replace("\\/", "/"),
        everywhere,
        every="g" in flags,
        ignore_case="i" in flags,
    )


def matches(entries: list[Entry], words: str) -> list[Entry]:
    """Items with every word somewhere in their text, in any order, ignoring case."""
    terms = words.lower().split()
    return [e for e in entries if all(w in e.text.lower() for w in terms)][:MATCH_LIMIT]


def by_number(numbers: list[int], number: int | None) -> list[int]:
    """`3` puts 3 first, then 30 to 39 and so on, so the one you mean is on
    top by the time you've typed it."""
    if number is None:
        return numbers[:MATCH_LIMIT]
    typed = str(number)
    exact = [n for n in numbers if n == number]
    rest = [n for n in numbers if str(n).startswith(typed) and n != number]
    return (exact + rest)[:MATCH_LIMIT]


# -- what the palette returns -----------------------------------------------------------


@dataclass(frozen=True)
class GoToItem:
    item_id: str
    line: int | None = None  # and into the editor at this line


@dataclass(frozen=True)
class GoToLine:
    row: int
    column: int


type Choice = GoToItem | GoToLine | Replace

HINTS: dict[Pane, str] = {
    "outline": "/words find    :34 item 34    :34:12 its line 12    "
    "/old/new/ replace in every item (g every match, i any case)",
    "editor": "/words in this item    //words everywhere    :12 line 12    :34:12 item 34's line 12    "
    "/old/new/ replace here    //old/new/ everywhere",
}


class PaletteModal(ModalScreen[Choice | None]):
    """ctrl+p: VS Code's quick open with vim's command line in it, and what it
    works on depends on the pane it was opened from. In the outline it works
    on items; in the editor, on the item being edited (`//` for every item)."""

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("up", "move(-1)", show=False, priority=True),
        Binding("down", "move(1)", show=False, priority=True),
    ]

    def __init__(
        self,
        entries: list[Entry],
        *,
        pane: Pane,
        start: str = "",
        current_id: str | None = None,
    ) -> None:
        super().__init__()
        self.entries = entries
        self.pane = pane
        self.start = start
        self.current = next((e for e in entries if e.item_id == current_id), None)
        self.number_width = len(str(max((e.number for e in entries), default=1)))
        self.command: Command = Find("", everywhere=True)

    def compose(self) -> ComposeResult:
        with Vertical(classes="palette"):
            yield Input(
                value=self.start,
                placeholder="Find an item…" if self.pane == "outline" else "Find…",
                id="palette-input",
                select_on_focus=False,
            )
            yield Label(id="palette-hint", markup=False)
            yield OptionList(id="palette-results")

    def on_mount(self) -> None:
        self.query_one(Input).cursor_position = len(self.start)
        self.list_matches(self.start)

    # -- listing -------------------------------------------------------------------

    def list_matches(self, query: str) -> None:
        self.command = command = parse_command(query)
        hint = ""
        options: list[Option] = []
        lines_here = self.pane == "editor" and self.current is not None
        match command:
            case Problem(message):
                hint = message
            case Jump(number, None) if lines_here:
                options = self.line_options(by_number(self.line_numbers(), number))
            case Jump(number, _):
                numbers = by_number([e.number for e in self.entries], number)
                by_n = {e.number: e for e in self.entries}
                options = [self.item_option(by_n[n]) for n in numbers]
            case Find(words, everywhere) if lines_here and not everywhere:
                options = self.find_in_text(words)
            case Find(words, _):
                options = [self.item_option(e) for e in matches(self.entries, words)]
            case Replace():
                options = self.preview(command)
                count = len(options)
                if count:
                    plural = "s" if count > 1 else ""
                    hint = f"enter replaces in {count} item{plural} (u undoes it)"
                else:
                    hint = f"Nothing in {self.scope_words(command)} matches"
        if not query.strip():
            hint = HINTS[self.pane]
        self.query_one("#palette-hint", Label).update(hint)
        results = self.query_one(OptionList)
        results.set_options(options)
        if options:
            results.highlighted = 0

    def item_option(self, entry: Entry) -> Option:
        line = Text(f"{entry.number:>{self.number_width}} ", style=MUTED)
        line.append(entry.subject)
        return Option(line, id=f"item:{entry.item_id}")

    def text_lines(self) -> list[str]:
        return self.current.text.split("\n") if self.current else []

    def line_numbers(self) -> list[int]:
        return list(range(1, len(self.text_lines()) + 1))

    def line_options(
        self, numbers: list[int], columns: dict[int, int] | None = None
    ) -> list[Option]:
        lines = self.text_lines()
        width = len(str(len(lines)))
        options = []
        for n in numbers:
            line = Text(f"{n:>{width}} ", style=MUTED)
            line.append(lines[n - 1] or " ")
            column = (columns or {}).get(n, 0)
            options.append(Option(line, id=f"line:{n - 1}:{column}"))
        return options

    def find_in_text(self, words: str) -> list[Option]:
        """Lines of the item being edited with every word in them."""
        terms = words.lower().split()
        found: dict[int, int] = {}
        for n, line in enumerate(self.text_lines(), 1):
            lowered = line.lower()
            if all(w in lowered for w in terms):
                found[n] = lowered.find(terms[0]) if terms else 0
        return self.line_options(list(found), found)

    def scope(self, replace: Replace) -> list[Entry]:
        if replace.everywhere or self.pane == "outline" or self.current is None:
            return self.entries
        return [self.current]

    def scope_words(self, replace: Replace) -> str:
        return "any item" if len(self.scope(replace)) > 1 else "this item"

    def preview(self, replace: Replace) -> list[Option]:
        """The items a replace would change, each shown as it would end up."""
        options = []
        for entry in self.scope(replace):
            text = ops.replaced(
                entry.text,
                replace.old,
                replace.new,
                every=replace.every,
                ignore_case=replace.ignore_case,
            )
            if text == entry.text:
                continue
            line = Text(f"{entry.number:>{self.number_width}} ", style=MUTED)
            new_subject = text.split("\n", 1)[0]
            if new_subject != entry.subject:
                line.append(entry.subject, style="strike " + MUTED)
                line.append(" → ")
                line.append(new_subject)
            else:
                line.append(entry.subject)
                line.append("  (further down)", style=MUTED)
            options.append(Option(line, id=f"item:{entry.item_id}", disabled=True))
        return options

    # -- choosing ------------------------------------------------------------------

    @on(Input.Changed)
    def changed(self, event: Input.Changed) -> None:
        self.list_matches(event.value)

    @on(Input.Submitted)
    def submit(self, event: Input.Submitted) -> None:
        event.stop()
        if isinstance(self.command, Replace):
            if self.query_one(OptionList).option_count:
                self.dismiss(self.command)
            else:
                self.app.bell()
            return
        option = self.query_one(OptionList).highlighted_option
        self.choose(option.id if option is not None else None)

    @on(OptionList.OptionSelected)
    def picked(self, event: OptionList.OptionSelected) -> None:
        if not isinstance(self.command, Replace):
            self.choose(event.option.id)

    def choose(self, option_id: str | None) -> None:
        if option_id is None:
            self.app.bell()
            return
        kind, _, rest = option_id.partition(":")
        if kind == "line":
            row, column = rest.split(":")
            self.dismiss(GoToLine(int(row), int(column)))
        else:
            line = self.command.line if isinstance(self.command, Jump) else None
            self.dismiss(GoToItem(rest, line))

    def action_move(self, delta: int) -> None:
        results = self.query_one(OptionList)
        if results.option_count:
            current = results.highlighted or 0
            results.highlighted = max(0, min(results.option_count - 1, current + delta))

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
  n               new item at the bottom, then back where you were
  m               pick it up: ↑ ↓ carry it, ← → out / in a level,
                  m or enter drops it, esc puts it back
  shift+↑ ↓       move it (and what's under it) without picking it up
  shift+← →       out / in a level
  space           tick or untick, and the boxes under it; [-] is partly done
  t               add or remove the box
  x               delete                    u   undo (a run of moves is one)
  ctrl+p  /  :    the palette: /words find, :34 item 34, :34:12 its line 12,
                  /old/new/ replace in every item (g every match, i any case)
  o  click        open the file:line in the item in your editor

In the editor (where you type)
  the first line is what the outline shows; enter is a new line
  esc  ctrl+n     back to the outline       ctrl+o  open the file:line here
  ctrl+p          /words in this item, //words in every item, :12 line 12,
                  :34:12 line 12 of item 34,
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
