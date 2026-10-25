"""Shared settings for the PDF builder and the local viewer.

Change USER_PASSWORD before you rely on this project. The sample value is
only there so the first run matches the documented example.
"""

import hashlib
import hmac
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMAGES_DIR = ROOT / "images"
PDF_PATH = ROOT / "protected_document.pdf"
STUDENTS_FILE = ROOT / "students.json"
PREVIEW_DIR = ROOT / "cache" / "previews"
INDEX_FILE = ROOT / "index.html"

# Password that opens the encrypted PDF on the server. Students never see
# this. They sign in with the 6-digit codes in students.json.
USER_PASSWORD = "123456"

# Separate secret. A viewer that honors PDF permission flags keeps printing,
# copying, and editing turned off for USER_PASSWORD. OWNER_PASSWORD removes
# those restrictions, so it has to stay different and private.
OWNER_PASSWORD = "owner-9f3c2a7e-keep-private"

# Listen on every network interface of this computer, port 5000.
HOST = "0.0.0.0"
PORT = 5000

WATERMARK_TEXT = "Rebin"

# Longest side of a page rendered for the browser. The render stays in
# memory; the original PDF is not sent to the browser.
VIEW_MAX_EDGE = 1600

# Longest side of the JPEG the browser is allowed to fetch. The PDF keeps
# the original pixel dimensions; the viewer does not hand out that file.
PREVIEW_MAX_EDGE = 2000
PREVIEW_JPEG_QUALITY = 90

# Embedded JPEG quality for PDF pages. 95 keeps full color detail (4:4:4).
PDF_JPEG_QUALITY = 95

# PDF passwords are limited to 127 UTF-8 bytes.
PDF_PASSWORD_MAX_BYTES = 127


def same_secret(left: str, right: str) -> bool:
    """Compare two strings without leaking which one is longer."""
    left_hash = hashlib.sha256(left.encode("utf-8")).digest()
    right_hash = hashlib.sha256(right.encode("utf-8")).digest()
    return hmac.compare_digest(left_hash, right_hash)


def validate_pdf_password(password: str, label: str) -> None:
    """Reject empty passwords and values the PDF format cannot store."""
    if password == "":
        raise ValueError(f"{label} is empty.")
    size = len(password.encode("utf-8"))
    if size > PDF_PASSWORD_MAX_BYTES:
        raise ValueError(
            f"{label} is {size} bytes. PDF passwords must be {PDF_PASSWORD_MAX_BYTES} bytes or fewer."
        )


def validate_password_pair(user_password: str, owner_password: str) -> None:
    """Permissions are ignored when both PDF passwords are the same."""
    validate_pdf_password(user_password, "User password")
    validate_pdf_password(owner_password, "Owner password")
    if same_secret(user_password, owner_password):
        raise ValueError(
            "The user password and the owner password must be different. "
            "If they match, a reader treats the opener as the owner and the "
            "print, copy, and edit restrictions do not apply."
        )
