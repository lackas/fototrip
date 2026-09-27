"""Generate the two derivatives the site uses. Source files are never published."""

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

THUMB_DIR = "thumb"
WEB_DIR = "web"


@dataclass(frozen=True, slots=True)
class Derivatives:
    thumb_rel: str
    web_rel: str
    web_width: int
    web_height: int


def build_derivatives(
    source: Path,
    photo_id: str,
    out_dir: Path,
    *,
    thumb_px: int = 96,
    web_px: int = 1600,
) -> Derivatives:
    """Write `thumb/<id>.jpg` (square crop) and `web/<id>.jpg` (long edge capped)."""
    thumb_path = out_dir / THUMB_DIR / f"{photo_id}.jpg"
    web_path = out_dir / WEB_DIR / f"{photo_id}.jpg"
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    web_path.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGB")

        thumb = ImageOps.fit(image, (thumb_px, thumb_px), method=Image.LANCZOS)
        thumb.save(thumb_path, "JPEG", quality=78, optimize=True)

        web = image.copy()
        web.thumbnail((web_px, web_px), Image.LANCZOS)  # never upscales
        web.save(web_path, "JPEG", quality=85, optimize=True, progressive=True)
        web_width, web_height = web.size

    return Derivatives(
        thumb_rel=f"{THUMB_DIR}/{photo_id}.jpg",
        web_rel=f"{WEB_DIR}/{photo_id}.jpg",
        web_width=web_width,
        web_height=web_height,
    )
