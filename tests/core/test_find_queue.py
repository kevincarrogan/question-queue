from pathlib import Path

import pytest

from questionqueue.core import QueueChoice, find_queue, queue_in


@pytest.fixture
def home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".qq").mkdir(parents=True)
    return home


def test_queue_in_this_folder(home: Path) -> None:
    project = home / "project"
    (project / ".qq").mkdir(parents=True)
    assert find_queue(project, home) == project / ".qq" / "questions.md"


def test_queue_in_a_parent_folder(home: Path) -> None:
    project = home / "project"
    (project / ".qq").mkdir(parents=True)
    deep = project / "src" / "pkg"
    deep.mkdir(parents=True)
    assert find_queue(deep, home) == queue_in(project)


def test_nearest_queue_wins(home: Path) -> None:
    outer = home / "outer"
    inner = outer / "inner"
    (outer / ".qq").mkdir(parents=True)
    (inner / ".qq").mkdir(parents=True)
    assert find_queue(inner, home) == queue_in(inner)


def test_no_queue_offers_a_choice(home: Path) -> None:
    project = home / "new-project"
    project.mkdir()
    assert find_queue(project, home) == QueueChoice(
        here=queue_in(project), home=queue_in(home)
    )


def test_home_folder_uses_the_global_queue_without_asking(tmp_path: Path) -> None:
    # Even before ~/.qq exists.
    assert find_queue(tmp_path, tmp_path) == queue_in(tmp_path)


def test_folder_outside_home_with_no_queue_offers_a_choice(tmp_path: Path) -> None:
    home = tmp_path / "home"
    elsewhere = tmp_path / "srv" / "thing"
    home.mkdir()
    elsewhere.mkdir(parents=True)
    assert find_queue(elsewhere, home) == QueueChoice(
        here=queue_in(elsewhere), home=queue_in(home)
    )


def test_a_file_called_qq_is_not_a_queue(home: Path) -> None:
    project = home / "project"
    project.mkdir()
    (project / ".qq").write_text("")
    assert isinstance(find_queue(project, home), QueueChoice)
