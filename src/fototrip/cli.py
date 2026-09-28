"""Command line entry point: wire the pipeline and report what happened."""

import functools
import http.server
import socketserver
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import click
from PIL import Image

from fototrip.album import (
    ExportRefused,
    _default_osxphotos,
    export_album,
    require_tools,
    run_osxphotos,
)
from fototrip.cache import BuildCache
from fototrip.images import THUMB_DIR, WEB_DIR, Derivatives, build_derivatives
from fototrip.localtime import Localizer
from fototrip.manifest import assign_ids, build_manifest
from fototrip.metadata import read_photo
from fototrip.models import Photo, SkipPhoto, SkipReason
from fototrip.places import Geocoder, PlaceCache, fetch_address
from fototrip.scan import find_photos
from fototrip.site import TripConfig, render_site

CACHE_FILENAME = ".fototrip-cache.json"

# Deliberately NOT inside the output folder: the lookups are rate-limited to
# one per second, so they must survive `rm -rf site`, and the file is a build
# artifact that has no business being published with the site.
DEFAULT_PLACES_CACHE = Path.home() / ".cache" / "fototrip" / "places.json"


@dataclass
class BuildReport:
    seen: int = 0
    included: int = 0
    days: int = 0
    cached: int = 0
    written: int = 0
    skipped: Counter[SkipReason] = field(default_factory=Counter)
    places_looked_up: int = 0
    places_cached: int = 0
    places_unnamed: int = 0

    def render(self) -> str:
        lines = [
            f"{self.seen} files seen",
            (
                f"{self.included} photo{'s' if self.included != 1 else ''} included "
                f"across {self.days} day{'s' if self.days != 1 else ''}"
            ),
            f"derivatives: {self.written} written, {self.cached} cached",
        ]
        if self.places_looked_up or self.places_cached or self.places_unnamed:
            line = f"places: {self.places_looked_up} looked up, {self.places_cached} from cache"
            if self.places_unnamed:
                line += f", {self.places_unnamed} without a name"
            lines.append(line)
        if self.skipped:
            lines.append(f"{sum(self.skipped.values())} skipped:")
            for reason, count in self.skipped.most_common():
                lines.append(f"  {count:>5}  {reason}")
        return "\n".join(lines)


def _resolve_places(photos: list[Photo], cache_path: Path, report: BuildReport) -> list[Photo]:
    """Attach a readable place name to each photo, cached across runs.

    Runs in the parent process, ahead of the derivative pool: the lookups are
    rate-limited to one per second, so they must not be multiplied by the
    number of workers. Photos at the same rounded coordinate share one lookup,
    which on a real trip collapses ~950 photos into ~130 requests.

    Never fatal. A build without network produces a site without place names.
    """
    geocoder = Geocoder(PlaceCache(cache_path), fetch=fetch_address)
    with click.progressbar(photos, label="places") as progress:
        resolved = [
            photo.evolve(place=geocoder.label_for(photo.lat, photo.lon)) for photo in progress
        ]

    geocoder.cache.save()
    report.places_looked_up = geocoder.stats.looked_up
    report.places_cached = geocoder.stats.cached
    report.places_unnamed = geocoder.stats.unnamed + geocoder.stats.failed
    return resolved


def _derive_one(photo: Photo, *, out_dir: Path, thumb_px: int, web_px: int):
    """Build one photo's derivatives. Runs in a worker process.

    Returns `(photo, None)` instead of raising when the source can no longer be
    read here: a file that Photos deleted or is still writing between the scan
    and this stage must not bring down the rest of the build.
    """
    try:
        derivatives = build_derivatives(
            photo.source, photo.photo_id, out_dir, thumb_px=thumb_px, web_px=web_px
        )
    except Exception:  # noqa: BLE001 -- deliberately broad, see comment below
        # Deliberately broad: this worker's only contract is that no single file
        # can take the whole build down, and a heterogeneous multi-thousand-photo
        # export can throw things an enumerated tuple will not anticipate (seen
        # so far: OSError, UnidentifiedImageError, SyntaxError, DecompressionBombError,
        # struct.error from malformed EXIF). A systematic bug still surfaces loudly
        # -- every photo ends up skipped as "unreadable or truncated image" and the
        # build exits non-zero if nothing could be included -- so this does not
        # hide it, it just stops one bad file from hiding every other good one.
        return photo, None
    return photo, derivatives


@click.group()
def main() -> None:
    """Build static websites from folders of geotagged trip photos."""


@main.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("-o", "--out", "out_dir", type=click.Path(path_type=Path), default=Path("site"))
@click.option("--title", default=None, help="Overrides trip.toml and the folder name.")
@click.option("--subtitle", default=None)
@click.option("--thumb-px", default=96, show_default=True)
@click.option("--web-px", default=1600, show_default=True)
@click.option(
    "--geocode/--no-geocode",
    default=True,
    show_default=True,
    help="Look up a readable place name per location (OpenStreetMap, cached).",
)
@click.option(
    "--places-cache",
    "places_cache",
    type=click.Path(path_type=Path),
    default=None,
    help=f"Where to cache place names. [default: {DEFAULT_PLACES_CACHE}]",
)
def build(folder, out_dir, title, subtitle, thumb_px, web_px, geocode, places_cache) -> None:
    """Build the site for FOLDER."""
    report = BuildReport()
    candidates = find_photos(folder)
    report.seen = len(candidates)

    localizer = Localizer()
    photos = []
    for path in candidates:
        try:
            photos.append(localizer.localize(read_photo(path)))
        except SkipPhoto as skip:
            report.skipped[skip.reason] += 1

    if not photos:
        click.echo(report.render())
        raise click.ClickException(f"no photos with usable GPS and timestamps in {folder}")

    if geocode:
        photos = _resolve_places(photos, places_cache or DEFAULT_PLACES_CACHE, report)

    photos = assign_ids(photos)
    cache = BuildCache(out_dir / CACHE_FILENAME, root=folder, thumb_px=thumb_px, web_px=web_px)

    fresh, stale = [], []
    for photo in photos:
        thumb_rel = f"{THUMB_DIR}/{photo.photo_id}.jpg"
        web_rel = f"{WEB_DIR}/{photo.photo_id}.jpg"
        if cache.is_fresh(photo.source, [out_dir / thumb_rel, out_dir / web_rel]):
            fresh.append((photo, thumb_rel, web_rel))
        else:
            stale.append(photo)

    entries = []
    for photo, thumb_rel, web_rel in fresh:
        try:
            # Pillow reads only the JPEG header here, so this stays cheap.
            with Image.open(out_dir / web_rel) as existing:
                width, height = existing.size
        except Exception:  # noqa: BLE001 -- deliberately broad, see comment below
            # Deliberately broad, for the same reason as _derive_one's catch: the
            # cache said this was fresh, but the file itself is broken (clobbered
            # out-of-band, truncated, or anything else Pillow can throw on a bad
            # read). Rebuild it like any other stale photo instead of failing the
            # whole command.
            stale.append(photo)
            continue
        entries.append((photo, Derivatives(thumb_rel, web_rel, width, height)))
    report.cached = len(entries)

    try:
        if stale:
            worker = functools.partial(
                _derive_one, out_dir=out_dir, thumb_px=thumb_px, web_px=web_px
            )
            with (
                ProcessPoolExecutor() as pool,
                click.progressbar(length=len(stale), label="derivatives") as progress,
            ):
                for photo, derivatives in pool.map(worker, stale, chunksize=8):
                    if derivatives is None:
                        # Deleted, rewritten, or otherwise unreadable between the scan
                        # and this stage. Not fatal: skip it, and leave the cache
                        # untouched so the next run retries it.
                        report.skipped[SkipReason.UNREADABLE] += 1
                    else:
                        entries.append((photo, derivatives))
                        cache.record(photo.source)
                        report.written += 1
                    progress.update(1)
    finally:
        # Save on the way out even on Ctrl-C or any other interruption: the
        # derivatives already written to disk should not have to be redone
        # just because the cache record of them was lost.
        cache.save()

    manifest = build_manifest(entries)
    report.included = len(manifest["photos"])
    report.days = len(manifest["days"])

    if not manifest["photos"]:
        click.echo(report.render())
        raise click.ClickException("no photos could be included in the build")

    render_site(manifest, TripConfig.load(folder, title=title, subtitle=subtitle), out_dir)

    click.echo(report.render())
    click.echo(f"\nsite written to {out_dir}")


@main.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("-p", "--port", default=8000, show_default=True)
def serve(folder, port) -> None:
    """Serve FOLDER for local preview."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(folder))
    with socketserver.TCPServer(("127.0.0.1", port), handler) as httpd:
        click.echo(f"serving {folder} at http://127.0.0.1:{port}/  (ctrl-c to stop)")
        httpd.serve_forever()


@main.command("export-album")
@click.argument("album")
@click.option(
    "-o",
    "--out",
    "destination",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Trip folder to fill.",
)
@click.option(
    "--replace",
    is_flag=True,
    default=False,
    help="Empty the folder first. Without this, a non-empty folder is refused.",
)
@click.option(
    "--expect",
    "in_album",
    type=int,
    default=0,
    help="How many photos the album holds. Enables the free-space check and "
    "names the album's size in the report.",
)
@click.option("--jpeg-quality", type=click.FloatRange(0, 1), default=0.9, show_default=True)
@click.option(
    "--osxphotos",
    default=_default_osxphotos(),
    show_default=True,
    help="Path to osxphotos.",
)
def export_album_command(album, destination, replace, in_album, jpeg_quality, osxphotos) -> None:
    """Fill a trip folder from the Photos.app album ALBUM."""
    if not in_album:
        click.echo(
            "No --expect given, so the free-space check is off beyond an absolute "
            "floor. Pass --expect with the album's photo count to enable it. The "
            "export is still verified against the run report either way.\n"
        )
    try:
        require_tools(osxphotos)
        report = export_album(
            album,
            destination,
            in_album=in_album,
            replace=replace,
            runner=run_osxphotos,
            jpeg_quality=jpeg_quality,
            osxphotos=osxphotos,
        )
    except ExportRefused as refused:
        raise click.ClickException(refused.message) from refused

    click.echo(report.render())
    click.echo(f"\n{destination} is ready to build")
