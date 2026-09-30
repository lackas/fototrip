"""An overview page in front of several built trips.

A built trip is a self-contained directory: `photos.json` plus the page and
its assets, all referenced relatively. Putting several of them side by side
under one web root therefore needs no configuration and no process -- only a
page linking into them, which is what this builds.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

MANIFEST_NAME = "photos.json"


@dataclass(frozen=True, slots=True)
class Trip:
    title: str
    href: str
    cover: str
    first_day: str
    last_day: str
    photos: int
    days: int
    subtitle: str = ""


def _read_trip(folder: Path) -> Trip | None:
    """Describe one built trip, or None if this is not one we can list.

    Deliberately forgiving: a directory that is not a built site, or one whose
    manifest cannot be read, is skipped rather than raised over. One unreadable
    trip should not cost you the overview of all the others.
    """
    try:
        manifest = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(manifest, dict):
        return None

    photos = manifest.get("photos")
    days = manifest.get("days")
    if not isinstance(photos, list) or not photos or not isinstance(days, list) or not days:
        return None

    day_values = [d.get("day") for d in days if isinstance(d, dict) and d.get("day")]
    if not day_values:
        return None

    # The middle photo, not the first. Photos are ordered by capture time, so
    # the first is whatever was shot on the way out -- an airport, a boarding
    # pass, the first meal. The middle of the trip is where the trip is.
    middle = photos[len(photos) // 2]
    # The lightbox image, not the thumbnail: thumbnails are 96 px square and a
    # card is several hundred wide, so a thumbnail here is visibly soft. The
    # template loads these lazily, so trips below the fold cost nothing.
    cover = ""
    if isinstance(middle, dict):
        cover = middle.get("web") or middle.get("thumb") or ""

    return Trip(
        # `title` was added to the manifest after the first sites were built, so
        # fall back to the folder name rather than dropping an older trip.
        title=manifest.get("title") or folder.name,
        subtitle=manifest.get("subtitle") or "",
        href=f"{folder.name}/",
        cover=f"{folder.name}/{cover}" if cover else "",
        first_day=min(day_values),
        last_day=max(day_values),
        photos=len(photos),
        days=len(day_values),
    )


def find_trips(root: Path) -> list[Trip]:
    """Every built trip directly under `root`, newest first."""
    trips = [
        trip
        for folder in sorted(root.iterdir())
        if folder.is_dir() and (trip := _read_trip(folder)) is not None
    ]
    return sorted(trips, key=lambda t: (t.last_day, t.title), reverse=True)


def render_overview(trips: list[Trip], out_dir: Path, *, title: str) -> None:
    """Write `index.html` listing `trips` into `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(["html", "j2"]),
    )
    html = env.get_template("overview.html.j2").render(title=title, trips=trips)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
