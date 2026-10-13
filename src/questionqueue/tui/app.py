from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.widgets import ContentSwitcher

from ..core import DocumentFile, ExternalChange, InvalidMove, Question, ops
from .focus import AnswerArea, FocusView
from .modals import ChoiceModal, ParkModal
from .outline import OutlineTree

type ParkWhere = Literal["child", "sibling", "root"]

PARK_PROMPTS: dict[ParkWhere, str] = {
    "child": "Park a question under this one",
    "sibling": "Park a question alongside this one",
    "root": "Park a question at the root",
}

# Bindings that make no sense while a dialog is open.
MAIN_SCREEN_ACTIONS = {
    "toggle_view",
    "next_open",
    "done",
    "save",
    "park",
    "up",
    "external_editor",
}


class QQApp(App[None]):
    CSS_PATH = "app.tcss"
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        Binding("tab", "toggle_view", show=False, priority=True),
        Binding("ctrl+n", "next_open", show=False, priority=True),
        Binding("ctrl+d", "done", show=False, priority=True),
        Binding("ctrl+s", "save", show=False, priority=True),
        Binding("n", "park('child')", show=False),
        Binding("N", "park('sibling')", show=False),
        Binding("r", "park('root')", show=False),
        Binding("u", "up", show=False),
        Binding("e", "external_editor", show=False),
        Binding("q", "quit", show=False),
    ]

    def __init__(self, path: Path | str, *, watch: bool = True) -> None:
        super().__init__()
        self.file = DocumentFile.open(path)
        self.watch_enabled = watch
        self.current_id: str | None = self._starting_question()
        self.title = f"‽ {self.file.path.name}"

    # -- layout -------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial="focus"):
            yield FocusView(id="focus")
            yield OutlineTree()

    def on_mount(self) -> None:
        self.refresh_focus()
        self.enter_question()
        if self.watch_enabled:
            self.watch_file()

    @property
    def focus_view(self) -> FocusView:
        return self.query_one(FocusView)

    @property
    def outline(self) -> OutlineTree:
        return self.query_one(OutlineTree)

    @property
    def in_outline(self) -> bool:
        return self.query_one(ContentSwitcher).current == "outline"

    @property
    def current(self) -> Question | None:
        if self.current_id is None or self.current_id not in self.file.doc:
            return None
        return self.file.doc.get(self.current_id)

    def target_id(self) -> str | None:
        """What an action applies to: the highlighted question in the outline, else the current one."""
        if self.in_outline:
            return self.outline.highlighted_id
        return self.current_id

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return not (
            action in MAIN_SCREEN_ACTIONS and isinstance(self.screen, ModalScreen)
        )

    # -- state --------------------------------------------------------------

    def _starting_question(self) -> str | None:
        doc = self.file.doc
        first = ops.next_open(doc) or next(doc.walk(), None)
        return first.id if first else None

    def refresh_focus(self) -> None:
        question = self.current
        trail = question.ancestors() if question else []
        self.focus_view.show(question, trail)

    def refresh_outline(self, cursor_id: str | None = None) -> None:
        if self.in_outline:
            self.outline.rebuild(
                self.file.doc, self.current_id, cursor_id or self.outline.highlighted_id
            )

    def refresh_all(self, cursor_id: str | None = None) -> None:
        self.refresh_focus()
        self.refresh_outline(cursor_id)

    def enter_question(self) -> None:
        """Opening a question puts you straight into its answer."""
        if self.current is not None:
            self.focus_view.editor.focus()
        else:
            self.focus_view.focus()

    def editor_dirty(self) -> bool:
        question = self.current
        return question is not None and self.focus_view.editor.text != question.answer

    def commit_answer(self) -> None:
        question = self.current
        if question is not None and self.focus_view.shown_id == question.id:
            ops.answer(self.file.doc, question.id, self.focus_view.editor.text)

    def autosave(self) -> None:
        try:
            self.file.save()
        except ExternalChange:
            self.on_external_change()
        except OSError as error:
            self.notify(f"Couldn't save: {error}", severity="error")

    def go_to(self, question_id: str | None) -> None:
        """Make a question current and show it in whichever view is up."""
        self.commit_answer()
        self.autosave()
        self.current_id = question_id
        self.refresh_all(cursor_id=question_id)
        if not self.in_outline:
            self.enter_question()

    # -- actions ------------------------------------------------------------

    def action_toggle_view(self) -> None:
        switcher = self.query_one(ContentSwitcher)
        if self.in_outline:
            switcher.current = "focus"
            self.refresh_focus()
            self.enter_question()
        else:
            self.commit_answer()
            self.autosave()
            switcher.current = "outline"
            self.outline.rebuild(self.file.doc, self.current_id, self.current_id)
            self.outline.focus()

    def action_park(self, where: ParkWhere) -> None:
        anchor = self.target_id()
        if anchor is None:
            where = "root"

        def park(text: str | None) -> None:
            if text is None:
                return
            doc = self.file.doc
            if where == "child":
                question = ops.add(doc, text, parent_id=anchor)
            elif where == "sibling":
                question = ops.add(doc, text, as_sibling_of=anchor)
            else:
                question = ops.add(doc, text)
            self.autosave()
            if self.current_id is None:
                # The first question in an empty file becomes the current one.
                self.go_to(question.id)
            else:
                self.refresh_all()
            self.notify(f"Parked: {text}", timeout=1.5)

        self.push_screen(ParkModal(PARK_PROMPTS[where]), park)

    def action_next_open(self) -> None:
        self.commit_answer()
        question = ops.next_open(self.file.doc, self.target_id())
        if question is None:
            self.notify("No other open questions")
            return
        self.go_to(question.id)

    def action_done(self) -> None:
        target = self.target_id()
        if target is None:
            return
        self.commit_answer()
        ops.mark_answered(self.file.doc, target)
        self.autosave()
        question = ops.next_open(self.file.doc, target)
        if question is None:
            self.notify("Nothing left open")
            self.refresh_all()
            return
        self.go_to(question.id)

    def action_up(self) -> None:
        question = self.current
        if question is None or question.parent_id is None:
            self.notify("Already at the top")
            return
        self.go_to(question.parent_id)

    def action_save(self) -> None:
        self.commit_answer()
        try:
            saved = self.file.save()
        except ExternalChange:
            self.on_external_change()
            return
        self.notify("Saved" if saved else "Nothing to save", timeout=1.5)

    async def action_quit(self) -> None:
        self.commit_answer()
        if self.file.unsaved:
            try:
                self.file.save()
            except ExternalChange:
                self.on_external_change()
                return
        self.exit()

    def action_external_editor(self) -> None:
        question = self.current
        if question is None or self.in_outline:
            return
        self.commit_answer()
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        fd, tmp = tempfile.mkstemp(prefix=f"qq-{question.id}-", suffix=".md")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(question.answer)
            with self.suspend():
                subprocess.run([*shlex.split(editor), tmp], check=False)
            with open(tmp, encoding="utf-8", newline="") as f:
                text = f.read()
        finally:
            os.unlink(tmp)
        # Editors add a final newline; that is the only thing taken off.
        text = text.removesuffix("\n")
        ops.answer(self.file.doc, question.id, text)
        self.autosave()
        self.refresh_focus()

    # -- messages -----------------------------------------------------------

    @on(AnswerArea.Left)
    def answer_left(self) -> None:
        self.commit_answer()
        self.autosave()

    @on(OutlineTree.Request)
    def outline_request(self, event: OutlineTree.Request) -> None:
        doc = self.file.doc
        question = doc.get(event.question_id)
        if event.action == "open":
            self.query_one(ContentSwitcher).current = "focus"
            self.go_to(question.id)
            return
        if event.action == "delete":
            self.delete(question)
            return
        siblings = question.parent.children
        position = siblings.index(question)
        try:
            if event.action == "move_up" and position > 0:
                ops.reorder(doc, question.id, position - 1)
            elif event.action == "move_down" and position < len(siblings) - 1:
                ops.reorder(doc, question.id, position + 1)
            elif event.action == "indent":
                ops.indent(doc, question.id)
            elif event.action == "outdent":
                ops.outdent(doc, question.id)
            else:
                return
        except InvalidMove as error:
            self.notify(str(error), severity="warning")
            return
        self.autosave()
        self.refresh_all(cursor_id=question.id)

    def delete(self, question: Question) -> None:
        def confirmed(choice: str | None) -> None:
            if choice != "y":
                return
            parent = question.parent
            position = parent.children.index(question)
            ops.delete(self.file.doc, question.id)
            # Leave the cursor on the next sibling, else the previous, else the parent.
            remaining = parent.children
            fallback: Question | None = None
            if remaining:
                fallback = remaining[min(position, len(remaining) - 1)]
            elif isinstance(parent, Question):
                fallback = parent
            if self.current_id not in self.file.doc:
                replacement = ops.next_open(self.file.doc) or fallback
                self.current_id = replacement.id if replacement else None
            self.autosave()
            self.refresh_all(cursor_id=fallback.id if fallback else None)

        count = sum(1 for _ in question.descendants())
        if count:
            plural = "s" if count > 1 else ""
            self.push_screen(
                ChoiceModal(
                    f"Delete “{question.text}” and the {count} question{plural} under it?",
                    {"y": "delete", "n": "cancel"},
                ),
                confirmed,
            )
        else:
            confirmed("y")

    # -- the file changing under us ------------------------------------------

    @work(exclusive=True, group="watch")
    async def watch_file(self) -> None:
        async for _ in self.file.watch():
            self.on_external_change()

    def on_external_change(self) -> None:
        if not self.file.changed_on_disk():
            return
        if isinstance(self.screen, ChoiceModal):
            return
        if not (self.editor_dirty() or self.file.unsaved):
            self.reload_from_disk()
            return

        def resolve(choice: str | None) -> None:
            if choice == "r":
                self.reload_from_disk()
            elif choice == "k":
                self.commit_answer()
                self.file.save(force=True)
                self.notify("Kept your version")

        self.push_screen(
            ChoiceModal(
                f"{self.file.path.name} changed on disk, and you have unsaved edits.",
                {"r": "reload (discard mine)", "k": "keep mine (overwrite)"},
            ),
            resolve,
        )

    def reload_from_disk(self) -> None:
        self.file.reload()
        if self.current_id not in self.file.doc:
            self.current_id = self._starting_question()
        self.focus_view.shown_id = None
        self.refresh_all()
        self.notify("Reloaded: the file changed on disk", timeout=2)
