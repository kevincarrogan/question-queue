"""The command line: vim's / and : on the bottom line, in place of the key
bar. Nothing opens over the panes; what you type moves you around them as
you type it, and what it finds is marked where it is."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from textual.binding import Binding
from textual.message import Message
from textual.widgets import Input

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


def has_words(text: str, words: str) -> bool:
    """Every word somewhere in `text`, in any order, ignoring case."""
    lowered = text.lower()
    return all(w in lowered for w in words.lower().split())


def words_pattern(words: str) -> re.Pattern[str]:
    """Finds any of the words, ignoring case, for marking them."""
    terms = sorted(set(words.lower().split()), key=len, reverse=True)
    return re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)


def replace_pattern(replace: Replace) -> re.Pattern[str]:
    """Finds what a replace would replace, for marking it."""
    return re.compile(
        re.escape(replace.old), re.IGNORECASE if replace.ignore_case else 0
    )


HINTS: dict[Pane, str] = {
    "outline": "/words find  :34 item 34  :34:12 its line 12  "
    "/old/new/ replace (g every match, i any case)  ↑↓ next/previous  esc back",
    "editor": "/words in this item  //words everywhere  :12 line 12  :34:12 item 34's line 12  "
    "/old/new/ replace here  //old/new/ everywhere  ↑↓ next/previous  esc back",
}


class CommandLine(Input):
    """The line you type a command on. The app does the work as it changes."""

    BINDINGS = [
        Binding("escape", "cancel", show=False),
        Binding("down,tab", "step(1)", show=False, priority=True),
        Binding("up,shift+tab", "step(-1)", show=False, priority=True),
    ]

    class Cancel(Message):
        """esc, or backspace with nothing left: back where you were."""

    class Step(Message):
        """↓ or ↑: the next or previous match."""

        def __init__(self, delta: int) -> None:
            super().__init__()
            self.delta = delta

    def action_cancel(self) -> None:
        self.post_message(self.Cancel())

    def action_step(self, delta: int) -> None:
        self.post_message(self.Step(delta))

    def action_delete_left(self) -> None:
        # As in vim, backspacing past the start closes the line.
        if not self.value:
            self.post_message(self.Cancel())
            return
        super().action_delete_left()
