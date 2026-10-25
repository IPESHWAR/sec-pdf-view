#!/usr/bin/env python3
"""Create unique 6-digit student access codes.

Examples, from this folder:

    python generate_students.py --count 50
    python generate_students.py --count 100 --force
    python generate_students.py --names roster.txt --append

The script prints each student's name and code. Tokens stay in students.json
and are only used by the server after a code is accepted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from students import StudentFileError, generate_students, load_students, save_students


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate unique student access codes.")
    parser.add_argument("--count", type=int, default=None, help="How many students to add (default: 50).")
    parser.add_argument("--names", type=Path, help="UTF-8 text file with one student name per line.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("students.json"),
        help="Roster file to write (default: students.json).",
    )
    parser.add_argument("--append", action="store_true", help="Add to an existing roster instead of replacing it.")
    parser.add_argument("--force", action="store_true", help="Replace an existing roster file.")
    return parser.parse_args()


def read_names(path: Path) -> list[str]:
    rows: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        name = " ".join(line.split())
        if name and not name.startswith("#"):
            rows.append(name)
    if not rows:
        raise StudentFileError(f"{path} does not contain any names.")
    return rows


def placeholder_names(count: int, start: int) -> list[str]:
    width = max(3, len(str(start + count - 1)))
    return [f"Student {index:0{width}d}" for index in range(start, start + count)]


def main() -> None:
    args = parse_args()
    output = args.output
    if output.exists() and not args.append and not args.force:
        print(f"{output} already exists. Run again with --force to replace it, or --append to add students.")
        raise SystemExit(1)

    existing = load_students(output) if args.append else []
    if args.append and output.exists() and not existing:
        print(f"{output} could not be read, so nothing was added.")
        raise SystemExit(1)

    if args.names is not None:
        names = read_names(args.names)
        if args.count is not None and args.count != len(names):
            print("--count has to match the number of names in the file, or be left out.")
            raise SystemExit(1)
    else:
        count = 50 if args.count is None else args.count
        if count < 1:
            print("--count must be at least 1.")
            raise SystemExit(1)
        names = placeholder_names(count, len(existing) + 1)

    try:
        students = generate_students(names, existing)
    except StudentFileError as exc:
        print(exc)
        raise SystemExit(1) from exc

    save_students(output, students)
    created = students[len(existing) :]
    print(f"Wrote {len(created)} student(s) to {output}. The roster now has {len(students)}.")
    print()
    for student in created:
        print(f"{student['code']}  {student['name']}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
