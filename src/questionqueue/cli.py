import argparse
from pathlib import Path

from .core.store import QueueChoice, find_queue, queue_in


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="qq",
        description="An outliner for your terminal, kept in a markdown file.",
        epilog="With no file, qq opens .qq/questions.md in the nearest folder that "
        "has a .qq folder. If there isn't one, it asks whether to start one here "
        "or use your global queue in ~/.qq.",
    )
    where = parser.add_mutually_exclusive_group()
    where.add_argument(
        "file", type=Path, nargs="?", help="markdown file (created if missing)"
    )
    where.add_argument(
        "--here",
        action="store_true",
        help="use the queue in this folder, starting one if needed",
    )
    where.add_argument(
        "-g",
        "--global",
        dest="global_",
        action="store_true",
        help="use your global queue in ~/.qq",
    )
    args = parser.parse_args()

    target: Path | QueueChoice
    if args.file:
        target = args.file
    elif args.here:
        target = queue_in(Path.cwd())
    elif args.global_:
        target = queue_in(Path.home())
    else:
        target = find_queue()

    # Imported here so `qq --help` doesn't pay for loading Textual.
    from .tui.app import QQApp

    QQApp(target).run()
