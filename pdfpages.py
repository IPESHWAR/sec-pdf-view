"""Render PDF pages to PNG in memory.

The original PDF stays on disk. Nothing in this module writes a page image
to a file, and the bytes it returns do not include the PDF's path.
"""

from __future__ import annotations

import io
import threading
from collections import OrderedDict
from pathlib import Path

from PIL import Image


def _encode_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=6)
    return buffer.getvalue()


def _decrypt_with_pypdf(path: Path, password: str) -> bytes:
    """Unlock a PDF into memory when MuPDF rejects the encryption."""
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(str(path))
    status = reader.decrypt(password or "")
    if not status:
        raise RuntimeError("The PDF could not be unlocked.")
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def open_pdf(path: Path, password: str):
    """Open the configured PDF. The decrypted copy is not written to disk."""
    import pymupdf as fitz

    if not path.is_file():
        raise FileNotFoundError("The PDF is not available.")
    document = fitz.open(str(path))
    if not document.is_encrypted:
        return document
    if document.authenticate(password or ""):
        return document
    document.close()
    payload = _decrypt_with_pypdf(path, password)
    opened = fitz.open(stream=payload, filetype="pdf")
    if opened.is_encrypted and not opened.authenticate(password or ""):
        opened.close()
        raise RuntimeError("The PDF could not be unlocked.")
    return opened


class PageLibrary:
    """One open PDF and a small memory cache of rendered RGB pages."""

    def __init__(self, path: Path, password: str, max_edge: int = 1600) -> None:
        self.path = path
        self.password = password
        self.max_edge = max_edge
        self._lock = threading.Lock()
        self._document = None
        self._signature: tuple[int, int] | None = None
        self._cache: OrderedDict[int, tuple[int, int, bytes]] = OrderedDict()

    def close(self) -> None:
        with self._lock:
            self._reset_locked()

    def _reset_locked(self) -> None:
        if self._document is not None:
            self._document.close()
            self._document = None
        self._signature = None
        self._cache.clear()

    def _file_signature(self) -> tuple[int, int]:
        stat = self.path.stat()
        return (stat.st_mtime_ns, stat.st_size)

    def _document_locked(self):
        signature = self._file_signature()
        if self._document is not None and self._signature == signature:
            return self._document
        self._reset_locked()
        self._document = open_pdf(self.path, self.password)
        self._signature = signature
        return self._document

    def _zoom(self, rect) -> float:
        long_edge = max(float(rect.width), float(rect.height))
        if long_edge <= 0:
            return 1.0
        return min(3.0, self.max_edge / long_edge)

    def describe(self) -> list[dict[str, int]]:
        """Page sizes the browser should reserve. No file paths."""
        with self._lock:
            document = self._document_locked()
            pages: list[dict[str, int]] = []
            for index, page in enumerate(document):
                zoom = self._zoom(page.rect)
                pages.append(
                    {
                        "index": index,
                        "width": max(1, int(page.rect.width * zoom)),
                        "height": max(1, int(page.rect.height * zoom)),
                    }
                )
            return pages

    def render_png(self, index: int) -> bytes:
        """Render one page to PNG. The canvas watermark is drawn in the browser."""
        rgb = self._render_rgb(index)
        image = Image.frombytes("RGB", (rgb[0], rgb[1]), rgb[2])
        try:
            return _encode_png(image)
        finally:
            image.close()

    def _render_rgb(self, index: int) -> tuple[int, int, bytes]:
        import pymupdf as fitz

        with self._lock:
            document = self._document_locked()
            if index < 0 or index >= document.page_count:
                raise IndexError(index)
            cached = self._cache.get(index)
            if cached is not None:
                self._cache.move_to_end(index)
                return cached
            page = document[index]
            matrix = fitz.Matrix(self._zoom(page.rect), self._zoom(page.rect))
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            try:
                raw = (pixmap.width, pixmap.height, bytes(pixmap.samples))
            finally:
                pixmap = None
            self._cache[index] = raw
            while len(self._cache) > 4:
                self._cache.popitem(last=False)
            return raw
