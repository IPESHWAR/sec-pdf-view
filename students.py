"""Student access codes for the protected viewer.

students.json is the roster. Each student has a display name, a 6-digit code
they type into the viewer, and a random token stored only in the server
session. The token is not an extra password.
"""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path

CODE_PATTERN = re.compile(r"\d{6}\Z")
MAX_NAME_LENGTH = 80
MAX_STUDENTS = 5000


class StudentFileError(ValueError):
    """The roster file is missing a required field or has a duplicate code."""


def normalize_name(value: object, label: str) -> str:
    """Keep a single-line display name that can be stamped onto a page."""
    if not isinstance(value, str):
        raise StudentFileError(f"{label} must be text.")
    name = " ".join(value.split())
    if name == "":
        raise StudentFileError(f"{label} is empty.")
    if len(name) > MAX_NAME_LENGTH:
        raise StudentFileError(f"{label} is longer than {MAX_NAME_LENGTH} characters.")
    if any(ord(character) < 32 for character in name):
        raise StudentFileError(f"{label} contains a control character.")
    return name


def normalize_code(value: object) -> str:
    """Return a 6-digit code, or raise if the value is not one."""
    if not isinstance(value, str):
        raise StudentFileError("An access code must be a 6-digit string.")
    code = "".join(value.split())
    if CODE_PATTERN.fullmatch(code) is None:
        raise StudentFileError("An access code must be exactly 6 digits.")
    return code


def _new_code(used: set[str]) -> str:
    if len(used) >= 1_000_000:
        raise StudentFileError("Every 6-digit code is already in use.")
    while True:
        code = f"{secrets.randbelow(1_000_000):06d}"
        if code not in used:
            used.add(code)
            return code


def _new_token(used: set[str]) -> str:
    while True:
        token = secrets.token_urlsafe(32)
        if token not in used:
            used.add(token)
            return token


def load_students(path: Path) -> list[dict[str, str]]:
    """Read the roster. An unreadable file fails closed as an empty roster."""
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return validate_students(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, StudentFileError):
        return []


def validate_students(payload: object) -> list[dict[str, str]]:
    """Check the on-disk shape and reject duplicate codes or tokens."""
    if not isinstance(payload, dict):
        raise StudentFileError("students.json must be an object with a students list.")
    rows = payload.get("students")
    if not isinstance(rows, list):
        raise StudentFileError("students.json must contain a students list.")
    if len(rows) > MAX_STUDENTS:
        raise StudentFileError(f"The roster cannot contain more than {MAX_STUDENTS} students.")

    students: list[dict[str, str]] = []
    codes: set[str] = set()
    tokens: set[str] = set()
    for index, row in enumerate(rows, start=1):
        label = f"Student {index}"
        if not isinstance(row, dict):
            raise StudentFileError(f"{label} must be an object.")
        name = normalize_name(row.get("name"), f"{label} name")
        code = normalize_code(row.get("code"))
        token = row.get("token")
        if not isinstance(token, str) or len(token) < 32:
            raise StudentFileError(f"{label} is missing a secure token.")
        if code in codes:
            raise StudentFileError(f"{label} reuses an access code.")
        if token in tokens:
            raise StudentFileError(f"{label} reuses a token.")
        codes.add(code)
        tokens.add(token)
        students.append({"name": name, "code": code, "token": token})
    return students


def save_students(path: Path, students: list[dict[str, str]]) -> None:
    """Replace the roster atomically."""
    payload = {"students": students}
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def generate_students(names: list[str], existing: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    """Append new students with unique codes and tokens."""
    students = list(existing or [])
    used_codes = {student["code"] for student in students}
    used_tokens = {student["token"] for student in students}
    if len(students) + len(names) > MAX_STUDENTS:
        raise StudentFileError(f"The roster cannot contain more than {MAX_STUDENTS} students.")
    for name in names:
        students.append(
            {
                "name": normalize_name(name, "Student name"),
                "code": _new_code(used_codes),
                "token": _new_token(used_tokens),
            }
        )
    return students
