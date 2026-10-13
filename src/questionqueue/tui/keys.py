"""Teach Textual's key parser alt+enter.

Terminals send alt+enter (and, in Terminal.app set up for it, shift+enter) as
ESC then a carriage return. Textual names the carriage return `enter` and
drops the alt, so the two keys can't be told apart. This wraps the parser so
ESC + enter arrives as `alt+enter`. It touches a private method, so
tests/tui/test_keys.py feeds the raw bytes through the parser to catch a
Textual upgrade that changes it.
"""

from __future__ import annotations

from collections.abc import Iterable

from textual import events
from textual._xterm_parser import XTermParser

_original = XTermParser._sequence_to_key_events


def _keep_alt_on_enter(
    self: XTermParser, sequence: str, alt: bool = False
) -> Iterable[events.Key]:
    for event in _original(self, sequence, alt):
        if alt and event.key == "enter":
            yield events.Key("alt+enter", event.character)
        else:
            yield event


def install() -> None:
    XTermParser._sequence_to_key_events = _keep_alt_on_enter  # type: ignore[method-assign]
