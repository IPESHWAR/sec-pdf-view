#!/usr/bin/env python3
"""Build one encrypted PDF from the images in images/.

The file is AES-256 encrypted. The user password opens it. Printing, copying,
and editing stay off for that password. The owner password is different on
purpose: readers that honor PDF permissions lift those limits only for the
owner password.

Run from this folder:

    python build_pdf.py
    python build_pdf.py --password "123456"
    python build_pdf.py --images images --output protected_document.pdf
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from PIL import Image
from pypdf import PasswordType, PdfReader, PdfWriter
from pypdf.constants import UserAccessPermissions
from pypdf.errors import PdfReadError

from config import (
    IMAGES_DIR,
    OWNER_PASSWORD,
    PDF_JPEG_QUALITY,
    PDF_PATH,
    USER_PASSWORD,
    WATERMARK_TEXT,
    same_secret,
    validate_password_pair,
)
from imaging import list_images, open_rgb, stamp_watermark


def viewing_only_permissions() -> UserAccessPermissions:
    """Permission integer that grants viewing and denies the other named rights.

    Reserved bits stay at the values the PDF spec requires. Passing an empty
    map is how this pypdf version says "do not grant print, copy, or edit".
    """
    return UserAccessPermissions.from_dict({})


def write_pdf_page(image: Image.Image, destination: Path) -> None:
    """Embed one RGB image as a single PDF page, fitted to an 11-inch long edge."""
    long_edge = max(image.width, image.height, 1)
    dpi = max(72.0, long_edge / 11.0)
    # subsampling=0 is 4:4:4, so the JPEG keeps full color detail.
    image.save(
        destination,
        format="PDF",
        resolution=float(dpi),
        quality=PDF_JPEG_QUALITY,
        subsampling=0,
    )


def build_protected_pdf(
    images_dir: Path,
    output: Path,
    user_password: str,
    owner_password: str,
) -> int:
    """Write `output` and return the page count. Raises RuntimeError on failure."""
    validate_password_pair(user_password, owner_password)
    images = list_images(images_dir)
    if not images:
        raise RuntimeError(
            f"No supported images in {images_dir}. "
            "Add JPG, JPEG, PNG, WEBP, HEIC, or HEIF files and run this again."
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".part")
    page_count = len(images)

    try:
        with tempfile.TemporaryDirectory(prefix="protected-pdf-") as temp_name:
            temp_dir = Path(temp_name)
            page_paths: list[Path] = []
            for index, source in enumerate(images, start=1):
                print(f"[{index:>3}/{page_count}] {source.name}", flush=True)
                page_path = temp_dir / f"page-{index:04d}.pdf"
                image = open_rgb(source)
                try:
                    # Burn the name into the pixels before encryption so it
                    # survives viewers that ignore optional PDF layers.
                    stamped = stamp_watermark(image, WATERMARK_TEXT)
                    try:
                        write_pdf_page(stamped, page_path)
                    finally:
                        stamped.close()
                finally:
                    image.close()
                page_paths.append(page_path)

            print("Encrypting the PDF...", flush=True)
            writer = PdfWriter()
            try:
                for page_path in page_paths:
                    writer.append(str(page_path))
                writer.add_metadata(
                    {
                        "/Title": "Protected document",
                        "/Creator": "MySec protected PDF",
                        "/Producer": "MySec protected PDF",
                    }
                )
                writer.encrypt(
                    user_password=user_password,
                    owner_password=owner_password,
                    permissions_flag=viewing_only_permissions(),
                    algorithm="AES-256",
                )
                with partial.open("wb") as handle:
                    writer.write(handle)
            finally:
                writer.close()

        verify_protected_pdf(partial, user_password, owner_password, page_count)
        partial.replace(output)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    return page_count


def verify_protected_pdf(
    path: Path,
    user_password: str,
    owner_password: str,
    page_count: int,
) -> None:
    """Fail the build if the file is readable without the password or the flags are loose."""
    bogus = "wrong-password-7c1e0a"
    try:
        with PdfReader(str(path)) as wrong:
            wrong_status = wrong.decrypt(bogus)
        with PdfReader(str(path)) as user_reader:
            user_status = user_reader.decrypt(user_password)
            rights = user_reader.user_access_permissions
            permissions_valid = user_reader.are_permissions_valid
            actual_pages = len(user_reader.pages)
        with PdfReader(str(path)) as owner_reader:
            owner_status = owner_reader.decrypt(owner_password)
    except PdfReadError as exc:
        raise RuntimeError(f"Could not read the encrypted PDF back: {exc}") from exc

    if wrong_status != PasswordType.NOT_DECRYPTED:
        raise RuntimeError("The PDF opened with a password that should have been rejected.")
    if user_status != PasswordType.USER_PASSWORD:
        raise RuntimeError(
            "The user password did not open the PDF as the restricted user. "
            "Refusing to keep a file whose permission flags would not apply."
        )
    if owner_status != PasswordType.OWNER_PASSWORD:
        raise RuntimeError("The owner password did not open the PDF as the owner.")
    if actual_pages != page_count:
        raise RuntimeError(f"Expected {page_count} pages, and the encrypted file has {actual_pages}.")
    if rights is None:
        raise RuntimeError("The encrypted PDF did not store permission flags.")
    if permissions_valid is False:
        raise RuntimeError("The PDF permission integrity check failed.")

    granted = rights.to_dict()
    denied = (
        "print",
        "modify",
        "extract",
        "extract_text_and_graphics",
        "add_or_modify",
        "assemble_doc",
        "print_to_representation",
        "fill_form_fields",
    )
    still_open = [name for name in denied if granted.get(name)]
    if still_open:
        raise RuntimeError("These permissions are still enabled: " + ", ".join(still_open))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an AES-256 PDF from images and disable print, copy, and edit."
    )
    parser.add_argument(
        "--images",
        type=Path,
        default=IMAGES_DIR,
        help="Folder of source images (default: images)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PDF_PATH,
        help="Where to write the encrypted PDF (default: protected_document.pdf)",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Password required to open the PDF (default: USER_PASSWORD in config.py)",
    )
    parser.add_argument(
        "--owner-password",
        default=None,
        help="Password that can lift the PDF restrictions (default: OWNER_PASSWORD in config.py)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    user_password = USER_PASSWORD if args.password is None else args.password
    owner_password = OWNER_PASSWORD if args.owner_password is None else args.owner_password
    images_dir = args.images.resolve()
    output = args.output.resolve()

    try:
        count = build_protected_pdf(images_dir, output, user_password, owner_password)
    except (RuntimeError, ValueError, OSError) as exc:
        print(exc)
        raise SystemExit(1) from exc

    print(f"Wrote {output}")
    print(f"Pages: {count}")
    print("Encryption: AES-256")
    print("User password: required to open the file")
    print("Printing, copying, and modifying: off for the user password")
    print("Owner password: removes those limits in readers that honor them")
    if not same_secret(user_password, USER_PASSWORD):
        print("Warning: this PDF password is not USER_PASSWORD in config.py.")
        print("The web viewer checks config.py. Update it, or the viewer will reject this password.")


if __name__ == "__main__":
    main()
