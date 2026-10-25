#!/usr/bin/env python3
"""Seal the existing course PDF with a strict permissions lock.

The pages are copied as they already are, including the Rebin watermark
burned into them. The password that opens the file is 123456. A separate
owner password is what seals the restrictions. A PDF has one opening
password, so the student codes in students.json stay on the web viewer.

Printing, high-resolution printing, copying, text and graphics extraction,
editing, and annotating are all turned off for the user password.

    python lock_pdf_permissions.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pypdf import PasswordType, PdfReader, PdfWriter
from pypdf.constants import UserAccessPermissions
from pypdf.errors import PdfReadError
from config import OWNER_PASSWORD, PDF_PATH, USER_PASSWORD, validate_password_pair

OUTPUT_NAME = "Protected_Course_Locked.pdf"
# The password typed to open Protected_Course_Locked.pdf.
OPENING_PASSWORD = "123456"

# Bits a viewer may grant. All of them stay off.
# Printing is bit 3 (value 4). High-resolution printing, copying, extraction,
# editing, and annotating are the other named bits. None of them are set.
_DENIED = (
    "print",
    "print_to_representation",
    "modify",
    "extract",
    "extract_text_and_graphics",
    "add_or_modify",
    "assemble_doc",
    "fill_form_fields",
)


def locked_permissions() -> UserAccessPermissions:
    """Permission value with every user grant cleared.

    The PDF standard also has reserved bits that must stay at fixed values.
    Those are not permissions. Clearing them (a literal integer of 0) makes
    many readers ignore the lock. This value leaves only those reserved bits,
    so printing and the other operations above are denied.
    """
    return UserAccessPermissions.from_dict({})


def page_bytes(page) -> bytes:
    """Decoded content of one page, used to confirm the copy was not rewritten."""
    contents = page.get_contents()
    if contents is None:
        return b""
    if isinstance(contents, list):
        return b"".join(item.get_data() for item in contents)
    return contents.get_data()


def open_source(path: Path, passwords: list[str]) -> PdfReader:
    """Open the existing PDF with the first password that actually unlocks it."""
    if not path.is_file():
        raise RuntimeError(f"Could not find the PDF at {path.name}.")
    reader = PdfReader(str(path))
    if not reader.is_encrypted:
        return reader
    for password in passwords:
        status = reader.decrypt(password)
        if status != PasswordType.NOT_DECRYPTED:
            return reader
    reader.close()
    raise RuntimeError("None of the known passwords opened the existing PDF.")


def lock_pdf(
    source: Path,
    output: Path,
    user_password: str,
    owner_password: str,
) -> int:
    """Copy `source` to `output` and return the page count."""
    validate_password_pair(user_password, owner_password)
    permissions = locked_permissions()
    partial = output.with_suffix(output.suffix + ".part")
    reader = open_source(source, [user_password, USER_PASSWORD])
    original_pages = [page_bytes(page) for page in reader.pages]
    if not original_pages:
        raise RuntimeError("The existing PDF has no pages.")

    try:
        writer = PdfWriter()
        try:
            writer.clone_document_from_reader(reader)
            writer.encrypt(
                user_password=user_password,
                owner_password=owner_password,
                permissions_flag=permissions,
                algorithm="AES-256",
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            with partial.open("wb") as handle:
                writer.write(handle)
        finally:
            writer.close()
        verify_locked_pdf(partial, original_pages, user_password, owner_password, permissions)
        partial.replace(output)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    finally:
        reader.close()
    return len(original_pages)


def verify_locked_pdf(
    path: Path,
    original_pages: list[bytes],
    user_password: str,
    owner_password: str,
    permissions: UserAccessPermissions,
) -> None:
    """Refuse the output unless the pages match and the lock holds."""
    bogus = "wrong-password-7c1e0a"
    try:
        with PdfReader(str(path)) as wrong:
            wrong_status = wrong.decrypt(bogus)
        with PdfReader(str(path)) as user_reader:
            user_status = user_reader.decrypt(user_password)
            rights = user_reader.user_access_permissions
            permissions_valid = user_reader.are_permissions_valid
            copied_pages = [page_bytes(page) for page in user_reader.pages]
        with PdfReader(str(path)) as owner_reader:
            owner_status = owner_reader.decrypt(owner_password)
    except PdfReadError as exc:
        raise RuntimeError(f"Could not read the locked PDF back: {exc}") from exc

    if wrong_status != PasswordType.NOT_DECRYPTED:
        raise RuntimeError("The PDF opened with a password that should have been rejected.")
    if user_status != PasswordType.USER_PASSWORD:
        raise RuntimeError(
            "The user password did not open the PDF as the restricted user. "
            "The permission lock would not apply."
        )
    if owner_status != PasswordType.OWNER_PASSWORD:
        raise RuntimeError("The owner password did not open the PDF as the owner.")
    if len(copied_pages) != len(original_pages):
        raise RuntimeError(
            f"Expected {len(original_pages)} pages, and the locked file has {len(copied_pages)}."
        )
    if copied_pages != original_pages:
        raise RuntimeError("A page changed while the permissions were applied.")
    if rights is None:
        raise RuntimeError("The locked PDF did not store permission flags.")
    if permissions_valid is False:
        raise RuntimeError("The PDF permission integrity check failed.")
    if int(rights) != int(permissions):
        raise RuntimeError("The stored permissions do not match the requested lock.")

    granted = rights.to_dict()
    still_open = [name for name in _DENIED if granted.get(name)]
    if still_open:
        raise RuntimeError("These permissions are still enabled: " + ", ".join(still_open))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy the existing PDF and turn off print, copy, extraction, and editing."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=PDF_PATH,
        help="Existing PDF (default: protected_document.pdf)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(OUTPUT_NAME),
        help="Locked PDF to write (default: Protected_Course_Locked.pdf)",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Password that opens the locked file (default: 123456)",
    )
    parser.add_argument(
        "--owner-password",
        default=None,
        help="Owner password that seals the restrictions (default: OWNER_PASSWORD in config.py)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    user_password = OPENING_PASSWORD if args.password is None else args.password
    owner_password = OWNER_PASSWORD if args.owner_password is None else args.owner_password
    source = args.input.resolve()
    output = args.output.resolve()
    permissions = locked_permissions()

    try:
        count = lock_pdf(source, output, user_password, owner_password)
    except (RuntimeError, ValueError, OSError) as exc:
        print(exc)
        raise SystemExit(1) from exc

    print(f"Wrote {output.name}")
    print(f"Pages: {count}")
    print("Encryption: AES-256")
    print(f"Opening password: {user_password}")
    print("Owner password: different from the opening password, so printing, copying, and editing stay off")
    granted = permissions.to_dict()
    print(
        "Permission grants: "
        + ", ".join(f"{name}=0" for name in _DENIED if not granted[name])
    )


if __name__ == "__main__":
    main()
