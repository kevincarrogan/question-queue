from pathlib import Path

import pytest

from questionqueue.core.refs import (
    FileRef,
    choose_editor,
    editor_command,
    find_refs,
    project_folder,
    ref_at,
    resolve,
    windowed,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("foo/bar/core.py:30", [("foo/bar/core.py", 30)]),
        ("It's in `src/app.ts:7:3`.", [("src/app.ts", 7)]),
        ("see ./x.py:1 and ../y.rs:22", [("./x.py", 1), ("../y.rs", 22)]),
        ("~/notes/todo.md:4", [("~/notes/todo.md", 4)]),
        ("/etc/hosts.conf:2", [("/etc/hosts.conf", 2)]),
        (".github/ci.yml:9", [(".github/ci.yml", 9)]),
        ("meet at 12:30", []),
        ("https://example.com:8080/a.py:3", []),
        ("core.py without a line", []),
    ],
)
def test_find_refs(text: str, expected: list[tuple[str, int]]) -> None:
    assert [(r.path, r.line) for r in find_refs(text)] == expected


def test_ref_at_prefers_the_cursor_line() -> None:
    text = "first a.py:1\nnothing here\nthen b.py:2"
    assert ref_at(text, 2) == FileRef("b.py", 2, 2)
    assert ref_at(text, 1) == FileRef("a.py", 1, 0)
    assert ref_at("no refs", 0) is None


def test_project_folder(tmp_path: Path) -> None:
    assert (
        project_folder(tmp_path / "proj" / ".qq" / "questions.md") == tmp_path / "proj"
    )
    assert project_folder(tmp_path / "notes.md") == tmp_path


def test_resolve(tmp_path: Path) -> None:
    assert resolve(FileRef("a/b.py", 1, 0), tmp_path) == tmp_path / "a" / "b.py"
    assert resolve(FileRef("/x/y.py", 1, 0), tmp_path) == Path("/x/y.py")
    assert resolve(FileRef("~/y.py", 1, 0), tmp_path) == Path.home() / "y.py"


@pytest.mark.parametrize(
    ("editor", "expected"),
    [
        ("vim", ["vim", "+30", "/p/core.py"]),
        ("nvim", ["nvim", "+30", "/p/core.py"]),
        ("code --wait", ["code", "--wait", "-g", "/p/core.py:30"]),
        ("/usr/local/bin/subl", ["/usr/local/bin/subl", "/p/core.py:30"]),
        ("hx", ["hx", "/p/core.py:30"]),
    ],
)
def test_editor_command(editor: str, expected: list[str]) -> None:
    assert editor_command(editor, Path("/p/core.py"), 30) == expected


@pytest.mark.parametrize(
    ("env", "installed", "expected"),
    [
        ({"QQ_EDITOR": "zed", "EDITOR": "vim"}, True, "zed"),
        ({"VISUAL": "nvim", "EDITOR": "vim"}, True, "nvim"),
        ({"EDITOR": "vim"}, True, "vim"),
        ({}, True, "code"),
        ({}, False, "vi"),
    ],
)
def test_choose_editor(env: dict[str, str], installed: bool, expected: str) -> None:
    assert choose_editor(env, lambda _: "/bin/x" if installed else None) == expected


def test_windowed_editors_open_alongside() -> None:
    assert windowed("code")
    assert windowed("/usr/local/bin/cursor --reuse-window")
    assert not windowed("nvim")
