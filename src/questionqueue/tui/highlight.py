"""Highlighting that Textual's markdown query leaves out: inline markup
(`**bold**`, `*italic*`, `` `code` ``, links, file references) and the code
inside a fenced block, coloured by the block's language.

Highlights are (start byte, end byte or None, style name) per row, as
TextArea keeps them; the style names are ones every TextArea theme has."""

from __future__ import annotations

import re
from collections import defaultdict
from functools import cache
from pathlib import Path

from ..core.refs import REF_RE

type Highlight = tuple[int, int | None, str]

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*([\w+#-]*)")

INLINE: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\*\*[^*\s](?:[^*]*[^*\s])?\*\*|__[^_\s](?:[^_]*[^_\s])?__"), "bold"),
    (re.compile(r"(?<![*\w])\*[^*\s](?:[^*]*[^*\s])?\*(?![*\w])"), "italic"),
    (re.compile(r"(?<![_\w])_[^_\s](?:[^_]*[^_\s])?_(?![_\w])"), "italic"),
    (re.compile(r"~~[^~]+~~"), "strikethrough"),
    (re.compile(r"`[^`]+`"), "inline_code"),
    (re.compile(r"\[[^\]]+\](?=\()"), "link.label"),
    (re.compile(r"(?<=\])\([^)\s]+\)"), "link.uri"),
    (re.compile(r"<https?://[^>\s]+>|(?<![(\w])https?://[^\s)>]+"), "link.uri"),
    (REF_RE, "link.uri"),
]

# What people write after the fence, to the name tree-sitter knows it by.
ALIASES = {
    "py": "python",
    "python3": "python",
    "js": "javascript",
    "jsx": "javascript",
    "mjs": "javascript",
    "sh": "bash",
    "shell": "bash",
    "zsh": "bash",
    "console": "bash",
    "yml": "yaml",
    "rs": "rust",
    "golang": "go",
}


def extra_highlights(text: str) -> dict[int, list[Highlight]]:
    highlights: dict[int, list[Highlight]] = defaultdict(list)
    lines = text.split("\n")
    fence: str | None = None
    language = ""
    code: list[str] = []
    code_start = 0
    for row, line in enumerate(lines):
        match = FENCE_RE.match(line)
        if fence is None:
            if match:
                fence, language = match[1], match[2].lower()
                code, code_start = [], row + 1
                continue
            _inline(line, row, highlights)
        elif match and match[1].startswith(fence) and not match[2]:
            _code(code, code_start, ALIASES.get(language, language), highlights)
            fence = None
        else:
            code.append(line)
    if fence is not None:  # still being typed: colour what there is
        _code(code, code_start, ALIASES.get(language, language), highlights)
    return highlights


def _inline(line: str, row: int, highlights: dict[int, list[Highlight]]) -> None:
    for pattern, name in INLINE:
        for match in pattern.finditer(line):
            start = len(line[: match.start()].encode())
            end = len(line[: match.end()].encode())
            highlights[row].append((start, end, name))


def _code(
    lines: list[str],
    first_row: int,
    language: str,
    highlights: dict[int, list[Highlight]],
) -> None:
    query = _query(language) if language else None
    if query is None or not lines:
        return
    from tree_sitter import Parser, QueryCursor

    parser = Parser(query[0])
    tree = parser.parse("\n".join(lines).encode())
    captures = QueryCursor(query[1]).captures(tree.root_node)
    for name, nodes in captures.items():
        for node in nodes:
            (start_row, start_col), (end_row, end_col) = (
                node.start_point,
                node.end_point,
            )
            if start_row == end_row:
                highlights[first_row + start_row].append((start_col, end_col, name))
                continue
            highlights[first_row + start_row].append((start_col, None, name))
            for row in range(start_row + 1, end_row):
                highlights[first_row + row].append((0, None, name))
            highlights[first_row + end_row].append((0, end_col, name))


@cache
def _query(language: str):  # type: ignore[no-untyped-def]
    """The tree-sitter language and Textual's highlight query for it, or None."""
    try:
        from textual._tree_sitter import get_language
        from tree_sitter import Query
    except ImportError:
        return None
    import textual

    ts_language = get_language(language)
    path = (
        Path(textual.__file__).parent / "tree-sitter" / "highlights" / f"{language}.scm"
    )
    if ts_language is None or not path.exists():
        return None
    return ts_language, Query(ts_language, path.read_text())
