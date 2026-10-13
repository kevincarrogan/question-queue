import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="qq",
        description="Work through a queue of nested questions kept in a markdown file.",
    )
    parser.add_argument("file", type=Path, help="markdown file (created if missing)")
    args = parser.parse_args()

    # Imported here so `qq --help` doesn't pay for loading Textual.
    from .tui.app import QQApp

    QQApp(args.file).run()
