import argparse
import sys
from pathlib import Path

from .pack_loader import load_packs
from .storage import Storage

HOME = Path.home() / ".french-lingo"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="french-lingo")
    parser.add_argument("--data", type=Path, default=HOME, help="folder for progress and packs")
    parser.add_argument("--list-packs", action="store_true", help="check language packs and exit")
    args = parser.parse_args(argv)
    packs, problems = load_packs(args.data / "packs")
    for problem in problems:
        print(f"pack skipped: {problem}", file=sys.stderr)
    if args.list_packs:
        for pack in packs.values():
            print(f"{pack.name}: {len(pack.lessons)} lessons, {len(pack.words())} words")
        return 0
    try:
        from .gui import App
    except ImportError:
        print("error: this Python was installed without Tkinter", file=sys.stderr)
        return 1
    storage = Storage(args.data / "progress.db")
    try:
        App(storage, packs).mainloop()
    finally:
        storage.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
