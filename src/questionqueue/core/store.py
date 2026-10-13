"""Reading, writing and watching the markdown file."""

from __future__ import annotations

import asyncio
import contextlib
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from watchfiles import awatch

from .errors import ExternalChange
from .model import Document
from .parser import parse
from .serialise import serialise


def read_text(path: Path) -> str:
    # newline="" keeps \r\n as written, so the serialiser can write it back.
    with path.open(encoding="utf-8", newline="") as f:
        return f.read()


def atomic_write(path: Path, text: str) -> None:
    """Write via a temp file in the same directory and rename it over the target."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        with contextlib.suppress(FileNotFoundError):
            os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


class DocumentFile:
    """A Document bound to its file, remembering what was last read or written.

    That memory is how a save tells our own writes apart from someone else's:
    if the disk no longer holds what we last saw, someone else changed it.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.doc = Document()
        self._known_text: str | None = None

    @classmethod
    def open(cls, path: Path | str) -> DocumentFile:
        """Load the file, creating it if it doesn't exist."""
        document_file = cls(path)
        if not document_file.path.exists():
            document_file.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(document_file.path, "")
        document_file.reload()
        return document_file

    def reload(self) -> Document:
        """Re-read the file. If parsing had to add IDs, they're saved straight away."""
        text = read_text(self.path)
        self._known_text = text
        self.doc = parse(text)
        if self.doc.ids_assigned:
            self.save()
        return self.doc

    def disk_text(self) -> str | None:
        try:
            return read_text(self.path)
        except FileNotFoundError:
            return None

    def changed_on_disk(self) -> bool:
        """True if someone else has written to the file. A missing file doesn't count."""
        disk = self.disk_text()
        return disk is not None and disk != self._known_text

    @property
    def unsaved(self) -> bool:
        return serialise(self.doc) != self._known_text

    def save(self, *, force: bool = False) -> bool:
        """Write the document. Returns False if there was nothing to write.

        Raises ExternalChange rather than overwrite edits made by someone
        else since we last read the file, unless `force` is set.
        """
        if not force and self.changed_on_disk():
            raise ExternalChange(str(self.path))
        text = serialise(self.doc)
        if text == self._known_text:
            return False
        atomic_write(self.path, text)
        self._known_text = text
        return True

    async def watch(
        self, stop_event: asyncio.Event | None = None
    ) -> AsyncIterator[None]:
        """Yield each time the file's content changes to something we didn't write."""
        async for changes in awatch(
            self.path.parent, stop_event=stop_event, recursive=False
        ):
            if (
                any(Path(p).name == self.path.name for _, p in changes)
                and self.changed_on_disk()
            ):
                yield
