from __future__ import annotations

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label


class ParkModal(ModalScreen[str | None]):
    """A one-line input: Enter parks the question, Escape cancels."""

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, prompt: str) -> None:
        super().__init__()
        self.prompt = prompt

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.prompt)
            yield Input(placeholder="Question…", id="park-input")

    @on(Input.Submitted)
    def submit(self, event: Input.Submitted) -> None:
        self.dismiss(event.value if event.value.strip() else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


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
