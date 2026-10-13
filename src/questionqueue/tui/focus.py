from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static, TextArea

from ..core import Question

TRAIL_SEPARATOR = "  \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK}  "


class AnswerArea(TextArea):
    """The answer editor. Escape hands control back to the command keys."""

    BINDINGS = [Binding("escape", "leave", show=False)]

    class Left(Message):
        """Focus left the editor, so its text should be committed."""

    def __init__(self) -> None:
        super().__init__(
            id="answer",
            soft_wrap=True,
            tab_behavior="focus",
            show_line_numbers=False,
        )
        self.border_subtitle = "enter to edit"

    def action_leave(self) -> None:
        if isinstance(self.parent, Widget):
            self.parent.focus()

    def on_focus(self) -> None:
        self.border_subtitle = "esc for commands"

    def on_blur(self) -> None:
        self.border_subtitle = "enter to edit"
        self.post_message(self.Left())


class FocusView(Vertical, can_focus=True):
    """Breadcrumb trail, the active question, and its answer. Nothing else."""

    BINDINGS = [Binding("enter,i", "edit", show=False)]

    shown_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="trail")
        yield Static(id="question")
        yield AnswerArea()

    def show(self, question: Question | None, trail: list[Question]) -> None:
        trail_widget = self.query_one("#trail", Static)
        question_widget = self.query_one("#question", Static)
        editor = self.query_one(AnswerArea)
        if question is None:
            self.shown_id = None
            trail_widget.update("")
            question_widget.update(Text("Nothing here yet. Press r to add a question."))
            question_widget.add_class("empty")
            editor.display = False
            return
        trail_widget.update(Text(TRAIL_SEPARATOR.join(q.text for q in trail)))
        mark = "✓ " if not question.is_open else ""
        question_widget.update(Text(mark + question.text))
        question_widget.remove_class("empty")
        question_widget.set_class(not question.is_open, "answered")
        editor.display = True
        # A fresh load resets the cursor and undo history, which only makes
        # sense when the question changes or its answer changed underneath us.
        if self.shown_id != question.id or editor.text != question.answer:
            editor.load_text(question.answer)
        self.shown_id = question.id

    @property
    def editor(self) -> AnswerArea:
        return self.query_one(AnswerArea)

    def action_edit(self) -> None:
        editor = self.editor
        if editor.display:
            editor.focus()
