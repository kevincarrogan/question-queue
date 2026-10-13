import asyncio
import re
from pathlib import Path

import pytest

from questionqueue.core import DocumentFile, ExternalChange, ops


def test_open_creates_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "new.md"
    f = DocumentFile.open(path)
    assert path.read_text() == ""
    assert len(f.doc) == 0


def test_open_saves_assigned_ids_immediately(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("# Notes\n- No id yet\n")
    f = DocumentFile.open(path)
    assert re.fullmatch(
        r"# Notes\n- No id yet <!-- q:[0-9a-f]{4} -->\n", path.read_text()
    )
    assert not f.unsaved


def test_save_writes_and_reports_whether_anything_changed(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    f = DocumentFile.open(path)
    assert f.save() is False
    q = ops.add(f.doc, "First")
    assert f.unsaved
    assert f.save() is True
    assert path.read_text() == f"- First <!-- q:{q.id} -->\n"
    assert not f.unsaved


def test_save_refuses_to_clobber_external_edits(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    f = DocumentFile.open(path)
    ops.add(f.doc, "Mine")
    path.write_text("- Theirs <!-- q:abcd -->\n")
    assert f.changed_on_disk()
    with pytest.raises(ExternalChange):
        f.save()
    assert "Theirs" in path.read_text()
    f.save(force=True)
    assert "Mine" in path.read_text()
    assert not f.changed_on_disk()


def test_atomic_save_leaves_no_temp_files_and_keeps_mode(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_text("")
    path.chmod(0o600)
    f = DocumentFile.open(path)
    ops.add(f.doc, "q")
    f.save()
    assert [p.name for p in tmp_path.iterdir()] == ["notes.md"]
    assert path.stat().st_mode & 0o777 == 0o600


def test_crlf_survives_a_save(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_bytes(b"- A <!-- q:aaaa -->\r\n")
    f = DocumentFile.open(path)
    ops.add(f.doc, "B")
    f.save()
    assert path.read_bytes().count(b"\r\n") == 2


def test_writes_through_symlinks(tmp_path: Path) -> None:
    real = tmp_path / "real.md"
    real.write_text("")
    link = tmp_path / "link.md"
    link.symlink_to(real)
    f = DocumentFile.open(link)
    ops.add(f.doc, "q")
    f.save()
    assert link.is_symlink()
    assert "q" in real.read_text()


def test_reload(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    f = DocumentFile.open(path)
    path.write_text("- External <!-- q:abcd -->\n")
    f.reload()
    assert f.doc.get("abcd").text == "External"
    assert not f.changed_on_disk()


def test_watch_sees_external_writes_but_not_our_own(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    f = DocumentFile.open(path)

    async def scenario() -> int:
        stop = asyncio.Event()
        seen = 0

        async def consume() -> None:
            nonlocal seen
            async for _ in f.watch(stop):
                seen += 1
                f.reload()

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.3)
        ops.add(f.doc, "ours")
        f.save()
        await asyncio.sleep(0.5)
        assert seen == 0
        path.write_text("- theirs <!-- q:abcd -->\n")
        for _ in range(50):
            if seen:
                break
            await asyncio.sleep(0.1)
        stop.set()
        await task
        return seen

    assert asyncio.run(scenario()) == 1
    assert f.doc.get("abcd").text == "theirs"


def test_a_deleted_file_is_recreated_on_save(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    f = DocumentFile.open(path)
    path.unlink()
    assert not f.changed_on_disk()
    ops.add(f.doc, "back")
    f.save()
    assert "back" in path.read_text()
