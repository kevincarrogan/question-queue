import contextlib

from textual._parser import ParseError
from textual._xterm_parser import XTermParser

from questionqueue.tui import keys


def parse(data: str) -> list[str]:
    keys.install()
    parser = XTermParser()
    found = list(parser.feed(data))
    # An empty feed tells the parser the input has ended, which flushes a
    # pending ESC sequence. It then raises, having nothing left to read.
    with contextlib.suppress(ParseError):
        found.extend(parser.feed(""))
    return [getattr(event, "key", "") for event in found]


def test_esc_enter_is_alt_enter() -> None:
    assert parse("\x1b\r") == ["alt+enter"]


def test_plain_enter_and_other_alt_keys_are_unchanged() -> None:
    assert parse("\r") == ["enter"]
    assert parse("\x1bx") == ["alt+x"]
    assert parse("\x1b[13;2u") == ["shift+enter"]
