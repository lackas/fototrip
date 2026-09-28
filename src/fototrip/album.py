"""Fill a trip folder from a Photos.app album.

Standalone by design: only stdlib imports, so this module can be reasoned
about (and tested) without pulling in the rest of the package. The subprocess
call is injected, so no test needs a Photos library or a real export.

The Photos library is only ever read. Nothing here writes to it.
"""

import csv
import os
import shutil
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


def _human_bytes(count: int) -> str:
    """Bytes as a short decimal string: 4_900_000_000 -> '4.9 GB'.

    Promotion to the next unit happens when the rounded value at display
    precision would be 1000 or more, not on the raw value. This ensures
    999_999 bytes becomes '1.0 MB' (not '1000 kB') and similarly for every
    unit boundary. TB is the final unit.
    """
    value = float(count)

    # Bytes stay whole; no decimal places
    if value < 1000:
        return f"{value:.0f} B"

    # kB and above get one decimal place
    for unit in ("kB", "MB", "GB", "TB"):
        value /= 1000
        # Round at display precision to check promotion threshold
        rounded = round(value, 1)
        if rounded < 1000 or unit == "TB":
            return f"{rounded:.1f} {unit}"

    # Should never reach here, but fallback to TB
    return f"{value:.1f} TB"


@dataclass
class ExportReport:
    album: str
    in_album: int = 0
    exported: int = 0
    downloaded: int = 0
    bytes_written: int = 0
    failed: Counter[str] = field(default_factory=Counter)

    def render(self) -> str:
        lines = []
        if self.in_album:
            lines.append(f'{self.in_album} photos in album "{self.album}"')
        exported = f"{self.exported} exported"
        if self.downloaded:
            exported += f", {self.downloaded} of them downloaded from iCloud"
        lines.append(exported)
        if self.failed:
            lines.append(f"{sum(self.failed.values())} skipped:")
            for reason, count in self.failed.most_common():
                lines.append(f"  {count:>5}  {reason}")
        if self.bytes_written:
            lines.append(f"{_human_bytes(self.bytes_written)} written")
        return "\n".join(lines)


# Everything the export needs, and nothing that writes back to the library.
# Built as a list, never a shell string: an album name is user input and must
# stay one argument no matter what it contains.
def build_command(
    album: str,
    destination: Path,
    report_path: Path,
    *,
    jpeg_quality: float = 0.9,
    osxphotos: str = "osxphotos",
) -> list[str]:
    """The `osxphotos export` command line for one album."""
    return [
        osxphotos,
        "export",
        str(destination),
        "--album",
        album,
        "--only-photos",
        "--skip-live",
        "--convert-to-jpeg",
        "--jpeg-quality",
        str(jpeg_quality),
        "--exiftool",
        "--download-missing",
        "--report",
        str(report_path),
    ]


def _is_true(value: str | None) -> bool:
    return str(value).strip().lower() == "true"


def read_osxphotos_report(path: Path, report: ExportReport) -> None:
    """Fill `report`'s counts from an osxphotos CSV run report.

    Deliberately forgiving: a missing, unreadable or differently-shaped report
    leaves the counts untouched rather than raising. osxphotos may change its
    columns between versions, and the file count in `export_album` is what
    actually gates the swap -- this only makes the summary richer.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return

    try:
        rows = list(csv.DictReader(text.splitlines()))
    except csv.Error:
        return

    for row in rows:
        if "exported" not in row:
            return
        error = (row.get("error") or "").strip()
        if _is_true(row.get("exported")):
            report.exported += 1
            if _is_true(row.get("downloaded")):
                report.downloaded += 1
        elif error:
            report.failed[error] += 1
        else:
            report.failed["export failed"] += 1


# Rough per-photo estimate for the space precheck. The Photos library records
# no byte count for shared-album assets, so this cannot be exact; it exists to
# catch "this will obviously not fit", not to predict the final size. Measured
# against a real album: 2563 photos, mostly ~2048px, came to about 2.7 GB.
MEGABYTES_PER_PHOTO = 1.5

#: The precheck demands this much more than the estimate before starting.
SPACE_MARGIN = 1.5

IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})


class ExportRefused(Exception):
    """The export did not happen, and the target was not touched."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _free_space(path: Path) -> int:
    probe = path
    while not probe.exists():
        probe = probe.parent
    return shutil.disk_usage(probe).free


def _image_files(folder: Path) -> list[Path]:
    return [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]


def export_album(
    album: str,
    destination: Path,
    *,
    in_album: int,
    replace: bool = False,
    runner=None,
    free_space=_free_space,
    jpeg_quality: float = 0.9,
    osxphotos: str = "osxphotos",
) -> ExportReport:
    """Fill `destination` with `album`'s photos, replacing it only on success.

    Raises ExportRefused, without touching `destination`, for every reason the
    export should not proceed or its result should not be trusted.
    """
    if runner is None:  # pragma: no cover - the real runner lives in Task 5
        raise ValueError("export_album needs a runner")

    destination = Path(destination)
    existing = sorted(destination.iterdir()) if destination.is_dir() else []
    if existing and not replace:
        raise ExportRefused(
            f"{destination} already holds {len(existing)} entries. "
            "Pass --replace to empty it and fill it from the album."
        )

    # Replacing the directory the process is standing in leaves it with no cwd.
    if destination.is_dir() and destination.resolve() in (Path.cwd(), *Path.cwd().parents):
        raise ExportRefused(
            f"{destination} is the current working directory (or contains it). "
            "Run this from somewhere else."
        )

    parent = destination.parent
    if not parent.is_dir():
        raise ExportRefused(f"{parent} does not exist.")
    if not os.access(parent, os.W_OK):
        raise ExportRefused(f"{parent} is not writable, so the export cannot be staged there.")

    needed = int(in_album * MEGABYTES_PER_PHOTO * 1_000_000 * SPACE_MARGIN)
    available = free_space(parent)
    if available < needed:
        raise ExportRefused(
            f"Not enough space: about {_human_bytes(needed)} needed for {in_album} photos, "
            f"{_human_bytes(available)} free on {parent}."
        )

    incoming = parent / f"{destination.name}.incoming"
    shutil.rmtree(incoming, ignore_errors=True)

    report = ExportReport(album=album, in_album=in_album)
    report_path = incoming.parent / f"{destination.name}.report.csv"
    exit_code = runner(
        build_command(album, incoming, report_path, jpeg_quality=jpeg_quality, osxphotos=osxphotos)
    )

    if exit_code != 0:
        raise ExportRefused(
            f"osxphotos exited with status {exit_code}. {destination} was not touched; "
            f"the partial export is in {incoming}."
        )

    read_osxphotos_report(report_path, report)
    written = _image_files(incoming) if incoming.is_dir() else []
    if not written:
        raise ExportRefused(
            f'The export produced no photos. Is "{album}" the exact album name? '
            f"{destination} was not touched."
        )
    if len(written) < report.exported:
        raise ExportRefused(
            f"The export reported {report.exported} photos but wrote fewer ({len(written)}). "
            f"{destination} was not touched; the partial export is in {incoming}."
        )

    report.bytes_written = sum(p.stat().st_size for p in written)

    # The one destructive step, made interruptible. Both moves are atomic
    # renames, so an interruption leaves either the complete old folder or the
    # complete new one -- never a missing trip folder. `.previous` IS the old
    # folder, renamed rather than copied, so peak disk usage is unchanged.
    previous = parent / f"{destination.name}.previous"
    if destination.is_dir():
        shutil.rmtree(previous, ignore_errors=True)  # a leftover from a crashed run
        destination.rename(previous)
    incoming.rename(destination)
    shutil.rmtree(previous, ignore_errors=True)
    report_path.unlink(missing_ok=True)
    return report
