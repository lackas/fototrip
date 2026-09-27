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

from fototrip.cache import BuildCache
from fototrip.images import Derivatives, build_derivatives
from fototrip.localtime import Localizer
from fototrip.manifest import assign_ids, build_manifest
from fototrip.metadata import read_photo
from fototrip.models import Photo, SkipPhoto, SkipReason
from fototrip.scan import find_photos
from fototrip.site import TripConfig, render_site

CACHE_FILENAME = ".fototrip-cache.json"


@dataclass
class BuildReport:
    seen: int = 0
    included: int = 0
    days: int = 0
    cached: int = 0
    written: int = 0
    skipped: Counter[SkipReason] = field(default_factory=Counter)

    def render(self) -> str:
        lines = [
            f"{self.seen} files seen",
            (
                f"{self.included} photo{'s' if self.included != 1 else ''} included "
                f"across {self.days} day{'s' if self.days != 1 else ''}"
            ),
            f"derivatives: {self.written} written, {self.cached} cached",
        ]
        if self.skipped:
            lines.append(f"{sum(self.skipped.values())} skipped:")
            for reason, count in self.skipped.most_common():
                lines.append(f"  {count:>5}  {reason}")
        return "\n".join(lines)


def _derive_one(photo: Photo, *, out_dir: Path, thumb_px: int, web_px: int):
    """Build one photo's derivatives. Runs in a worker process."""
    return photo, build_derivatives(
        photo.source, photo.photo_id, out_dir, thumb_px=thumb_px, web_px=web_px
    )


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
def build(folder, out_dir, title, subtitle, thumb_px, web_px) -> None:
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

    photos = assign_ids(photos)
    cache = BuildCache(out_dir / CACHE_FILENAME)

    fresh, stale = [], []
    for photo in photos:
        thumb_rel = f"thumb/{photo.photo_id}.jpg"
        web_rel = f"web/{photo.photo_id}.jpg"
        if cache.is_fresh(photo.source, [out_dir / thumb_rel, out_dir / web_rel]):
            fresh.append((photo, thumb_rel, web_rel))
        else:
            stale.append(photo)

    entries = []
    for photo, thumb_rel, web_rel in fresh:
        # Pillow reads only the JPEG header here, so this stays cheap.
        with Image.open(out_dir / web_rel) as existing:
            width, height = existing.size
        entries.append((photo, Derivatives(thumb_rel, web_rel, width, height)))
    report.cached = len(fresh)

    if stale:
        worker = functools.partial(_derive_one, out_dir=out_dir, thumb_px=thumb_px, web_px=web_px)
        with (
            ProcessPoolExecutor() as pool,
            click.progressbar(length=len(stale), label="derivatives") as progress,
        ):
            for photo, derivatives in pool.map(worker, stale, chunksize=8):
                entries.append((photo, derivatives))
                cache.record(photo.source)
                report.written += 1
                progress.update(1)
    cache.save()

    manifest = build_manifest(entries)
    report.included = len(manifest["photos"])
    report.days = len(manifest["days"])
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
