from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from ..core import Document, Question


class OutlineTree(Tree[str]):
    """The whole question tree. Node data is the question ID."""

    BINDINGS = [
        Binding("enter", "open_question", show=False),
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("d", "request('delete')", show=False),
        Binding("K", "request('move_up')", show=False),
        Binding("J", "request('move_down')", show=False),
        Binding("greater_than_sign", "request('indent')", show=False),
        Binding("less_than_sign", "request('outdent')", show=False),
    ]

    class Request(Message):
        """Ask the app to do something to the highlighted question."""

        def __init__(self, action: str, question_id: str) -> None:
            super().__init__()
            self.action = action
            self.question_id = question_id

    def __init__(self) -> None:
        super().__init__("questions", id="outline")
        self.show_root = False
        self._by_id: dict[str, TreeNode[str]] = {}
        # Expanded/collapsed choices the user made, so a rebuild keeps them.
        self._expanded: dict[str, bool] = {}

    @property
    def highlighted_id(self) -> str | None:
        node = self.cursor_node
        return node.data if node is not None else None

    def rebuild(
        self, doc: Document, current_id: str | None, cursor_id: str | None
    ) -> None:
        self.clear()
        self._by_id.clear()
        for question in doc.children:
            self._add(self.root, question, current_id)
        target = self._by_id.get(cursor_id or "") or self._by_id.get(current_id or "")
        if target is not None:
            self.reveal(target)

    def reveal(self, node: TreeNode[str]) -> None:
        parent = node.parent
        while parent is not None and parent is not self.root:
            parent.expand()
            parent = parent.parent
        self.call_after_refresh(self.move_cursor, node)

    def _add(
        self, parent: TreeNode[str], question: Question, current_id: str | None
    ) -> None:
        label = self._label(question, question.id == current_id)
        if question.children:
            node = parent.add(
                label, data=question.id, expand=self._should_expand(question)
            )
            for child in question.children:
                self._add(node, child, current_id)
        else:
            node = parent.add_leaf(label, data=question.id)
        self._by_id[question.id] = node

    def _should_expand(self, question: Question) -> bool:
        if question.id in self._expanded:
            return self._expanded[question.id]
        # Answered branches start collapsed, unless something under them is still open.
        return question.is_open or any(q.is_open for q in question.descendants())

    @staticmethod
    def _label(question: Question, is_current: bool) -> Text:
        mark = (
            Text("? ", style="bold") if question.is_open else Text("✓ ", style="green")
        )
        text = Text(question.text, style="dim" if not question.is_open else "")
        if is_current:
            text.stylize("bold underline")
        return Text.assemble(mark, text)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[str]) -> None:
        if event.node.data is not None:
            self._expanded[event.node.data] = True

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed[str]) -> None:
        if event.node.data is not None:
            self._expanded[event.node.data] = False

    def action_open_question(self) -> None:
        self.action_request("open")

    def action_request(self, action: str) -> None:
        question_id = self.highlighted_id
        if question_id is not None:
            self.post_message(self.Request(action, question_id))
