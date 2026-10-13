"""File references like `foo/bar/core.py:30` in item text, and opening them in an editor."""

from __future__ import annotations

import re
import shlex
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from .store import QUEUE_DIR

# A path with an extension, then :line and an optional :column. Requiring the
# extension keeps times like 12:30 out; the lookbehind keeps URLs out.
REF_RE = re.compile(
    r"(?<![\w/.~:-])"
    r"(?P<path>(?:~|\.{1,2})?/?(?:[\w.-]+/)*[\w-][\w.-]*\.\w+)"
    r":(?P<line>\d+)(?::\d+)?\b"
)

# Editors that take `path:line` as one argument, by executable name. The rest
# get `+line path`, which vi, vim, nvim, nano, emacs, micro and kak accept.
GOTO_FLAG = {"code", "code-insiders", "codium", "cursor", "windsurf"}
PATH_COLON_LINE = {"subl", "zed", "hx", "helix"}
# Editors with their own window: qq keeps running while they open.
WINDOWED = GOTO_FLAG | {"subl", "zed"}


@dataclass(frozen=True)
class FileRef:
    path: str
    line: int
    row: int  # which line of the text it's on


def find_refs(text: str) -> list[FileRef]:
    return [
        FileRef(m["path"], int(m["line"]), row)
        for row, line in enumerate(text.split("\n"))
        for m in REF_RE.finditer(line)
    ]


def ref_at(text: str, row: int) -> FileRef | None:
    """The first reference on line `row`, else the first in the text."""
    refs = find_refs(text)
    on_row = [ref for ref in refs if ref.row == row]
    candidates = on_row or refs
    return candidates[0] if candidates else None


def project_folder(queue_path: Path) -> Path:
    """Where relative references start: the folder holding `.qq`, else the file's folder."""
    folder = queue_path.parent
    return folder.parent if folder.name == QUEUE_DIR else folder


def resolve(ref: FileRef, base: Path) -> Path:
    path = Path(ref.path).expanduser()
    return path if path.is_absolute() else base / path


def choose_editor(
    env: Mapping[str, str], which: Callable[[str], str | None] = shutil.which
) -> str:
    """$QQ_EDITOR, else $VISUAL, else $EDITOR, else VS Code if it's
    installed, else vi."""
    for name in ("QQ_EDITOR", "VISUAL", "EDITOR"):
        if env.get(name):
            return env[name]
    return "code" if which("code") else "vi"


def windowed(editor: str) -> bool:
    return Path(shlex.split(editor)[0]).name in WINDOWED


def editor_command(editor: str, path: Path, line: int) -> list[str]:
    argv = shlex.split(editor)
    name = Path(argv[0]).name
    if name in GOTO_FLAG:
        return [*argv, "-g", f"{path}:{line}"]
    if name in PATH_COLON_LINE:
        return [*argv, f"{path}:{line}"]
    return [*argv, f"+{line}", str(path)]
