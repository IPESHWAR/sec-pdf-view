"""Find, orient, and flatten the images shared by the PDF builder and the viewer."""

from __future__ import annotations

import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

# Registered once. HEIC and HEIF are included because phone exports use them
# and this project's images folder contains those files. JPG, PNG, and WEBP
# are always requested from Pillow directly.
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

_HEIF_READY = False


def register_formats() -> bool:
    """Enable HEIC/HEIF when pillow-heif is installed. Safe to call more than once."""
    global _HEIF_READY
    if _HEIF_READY:
        return True
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return False
    register_heif_opener()
    _HEIF_READY = True
    return True


def natural_key(path: Path) -> list[int | str]:
    """Sort IMG_2 before IMG_10 without losing the original filename."""
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def list_images(folder: Path) -> list[Path]:
    """Return supported images in the top level of `folder`, in natural order."""
    register_formats()
    if not folder.is_dir():
        return []
    files = [
        path
        for path in folder.iterdir()
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in IMAGE_SUFFIXES
    ]
    files.sort(key=natural_key)
    return files


def open_rgb(path: Path) -> Image.Image:
    """Open one image as an RGB copy with EXIF orientation applied.

    The caller owns the returned image and should close it. Transparency is
    flattened onto white because PDF pages in this project are opaque.
    """
    register_formats()
    try:
        with Image.open(path) as source:
            source.seek(0)
            source.load()
            transposed = ImageOps.exif_transpose(source)
            working = transposed if transposed is not None else source
            try:
                if _has_alpha(working, source):
                    rgba = working.convert("RGBA")
                    flat = Image.new("RGB", rgba.size, (255, 255, 255))
                    flat.paste(rgba, mask=rgba.getchannel("A"))
                    if rgba is not flat:
                        rgba.close()
                    return flat
                converted = working.convert("RGB")
                # convert() may return the same object, which the with-block closes.
                if converted is working:
                    return converted.copy()
                return converted
            finally:
                if transposed is not None and transposed is not source:
                    transposed.close()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise RuntimeError(f"Could not read {path.name}: {exc}") from exc


def _has_alpha(image: Image.Image, source: Image.Image) -> bool:
    if image.mode in ("RGBA", "LA"):
        return True
    return image.mode == "P" and "transparency" in source.info


def oriented_size(path: Path) -> tuple[int, int]:
    """Read pixel size after the EXIF orientation tag, without keeping the pixels."""
    register_formats()
    with Image.open(path) as source:
        source.seek(0)
        width, height = source.size
        orientation = 1
        try:
            orientation = int(source.getexif().get(274, 1))
        except (AttributeError, OSError, TypeError, ValueError):
            orientation = 1
    if orientation in (5, 6, 7, 8):
        return height, width
    return width, height


def save_jpeg_preview(source: Path, destination: Path, max_edge: int, quality: int) -> None:
    """Write a screen-sized JPEG next to `destination`, then move it into place."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.part")
    image = open_rgb(source)
    try:
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        image.save(
            temporary,
            format="JPEG",
            quality=quality,
            subsampling=0,
            optimize=True,
            progressive=True,
        )
        temporary.replace(destination)
    finally:
        image.close()
        if temporary.exists():
            temporary.unlink()


def _watermark_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """Prefer a real outline font so the repeated name stays sharp when scaled."""
    candidates = (
        Path(r"C:\Windows\Fonts\segoeuil.ttf"),
        Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/Library/Fonts/Arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default(size=size)


def _paste_clamped(base: Image.Image, sprite: Image.Image, left: int, top: int) -> None:
    """Alpha-composite `sprite` onto `base`, clipping anything outside the page."""
    if left >= base.width or top >= base.height:
        return
    if left + sprite.width <= 0 or top + sprite.height <= 0:
        return
    src_left = max(0, -left)
    src_top = max(0, -top)
    dest_x = max(0, left)
    dest_y = max(0, top)
    src_right = min(sprite.width, src_left + base.width - dest_x)
    src_bottom = min(sprite.height, src_top + base.height - dest_y)
    if src_right <= src_left or src_bottom <= src_top:
        return
    piece = sprite.crop((src_left, src_top, src_right, src_bottom))
    try:
        base.alpha_composite(piece, (dest_x, dest_y))
    finally:
        piece.close()


def stamp_watermark(image: Image.Image, text: str) -> Image.Image:
    """Return a new RGB image with a faint diagonal name on the page.

    The text is light gray at about 10% opacity, in a thin face, on an even
    diagonal grid. It stays light enough to leave the picture readable.
    """
    label = text.strip() or "Rebin"
    font_size = max(22, min(image.size) // 14)
    font = _watermark_font(font_size)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = probe.textbbox((0, 0), label, font=font)
    text_w = max(1, bbox[2] - bbox[0])
    text_h = max(1, bbox[3] - bbox[1])
    sprite = Image.new("RGBA", (text_w + 8, text_h + 8), (0, 0, 0, 0))
    ImageDraw.Draw(sprite).text(
        (4 - bbox[0], 4 - bbox[1]),
        label,
        font=font,
        fill=(176, 176, 176, 26),
    )
    rotated = sprite.rotate(-28, expand=True, resample=Image.Resampling.BICUBIC)
    sprite.close()

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    step_x = rotated.width + font_size * 2
    step_y = rotated.height + font_size * 2
    row = 0
    top = -rotated.height
    try:
        while top < image.height + rotated.height:
            left = -rotated.width + (step_x // 2 if row % 2 else 0)
            while left < image.width + rotated.width:
                _paste_clamped(overlay, rotated, left, top)
                left += step_x
            top += step_y
            row += 1
        base = image.convert("RGBA")
        try:
            return Image.alpha_composite(base, overlay).convert("RGB")
        finally:
            if base is not image:
                base.close()
    finally:
        overlay.close()
        rotated.close()


def fitted_size(width: int, height: int, max_edge: int) -> tuple[int, int]:
    """Scale so the longer side is at most `max_edge`, preserving aspect ratio."""
    long_edge = max(width, height, 1)
    scale = min(1.0, max_edge / float(long_edge))
    return max(1, round(width * scale)), max(1, round(height * scale))
