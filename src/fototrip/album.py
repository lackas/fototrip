"""Fill a trip folder from a Photos.app album.

Standalone by design: only stdlib imports, so this module can be reasoned
about (and tested) without pulling in the rest of the package. The subprocess
call is injected, so no test needs a Photos library or a real export.

The Photos library is only ever read. Nothing here writes to it.
"""

import csv
import os
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Rough per-photo estimate for the space precheck. The Photos library records
# no byte count for shared-album assets, so this cannot be exact; it exists to
# catch "this will obviously not fit", not to predict the final size. Measured
# against a real album: 2563 photos, mostly ~2048px, came to about 2.7 GB.
MEGABYTES_PER_PHOTO = 1.5

#: The precheck demands this much more than the estimate before starting.
SPACE_MARGIN = 1.5

#: Refused below this much free space whatever the album size, so the check in
#: the spec ("stops rather than filling the volume") holds even without
#: --expect. It catches "this will obviously not fit", nothing finer.
MINIMUM_FREE_BYTES = 2_000_000_000

# What --convert-to-jpeg is expected to leave behind. A file the export produced
# in some other format is counted by the run report but not here, which fails
# toward a refusal rather than toward a bad swap.
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})


#: What osxphotos writes for a true cell. Its CSV writer emits 1/0 and its JSON
#: writer emits true/false; see _is_true.
_TRUE_VALUES = frozenset({"1", "true", "yes"})


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


@dataclass
class ExportReport:
    album: str
    in_album: int = 0
    exported: int = 0
    bytes_written: int = 0
    failed: Counter[str] = field(default_factory=Counter)

    def render(self) -> str:
        lines = []
        if self.in_album:
            lines.append(f'{self.in_album} photos in album "{self.album}"')
        lines.append(f"{self.exported} exported")
        if self.failed:
            lines.append(f"{sum(self.failed.values())} skipped:")
            for reason, count in self.failed.most_common():
                lines.append(f"  {count:>5}  {reason}")
        # Exported plus skipped should equal the album's size. Report a
        # disagreement rather than refuse on it: a legitimate run can be short
        # for reasons nothing here can distinguish, and the whole point of the
        # feature is that "not exported" must not look like "not taken".
        if self.in_album:
            unaccounted = self.in_album - self.exported - sum(self.failed.values())
            if unaccounted > 0:
                lines.append(f"{unaccounted} not accounted for by the run report")
            elif unaccounted < 0:
                lines.append(f"{-unaccounted} more files than the album holds -- duplicates?")
        if self.bytes_written:
            lines.append(f"{_human_bytes(self.bytes_written)} written")
        return "\n".join(lines)


def build_command(
    album: str,
    destination: Path,
    report_path: Path,
    *,
    jpeg_quality: float = 0.9,
    osxphotos: str = "osxphotos",
) -> list[str]:
    """The `osxphotos export` command line for one album.

    Everything the export needs, and nothing that writes back to the library.
    Built as a list, never a shell string: an album name is user input and must
    stay one argument no matter what it contains. The four --skip flags are what
    make one album photo exactly one file: without them an edited photo, a burst
    or a RAW+JPEG pair each arrive several times, and every duplicate becomes
    another pin on the same spot at the same second.
    """
    return [
        osxphotos,
        "export",
        str(destination),
        "--album",
        album,
        "--only-photos",
        "--skip-live",
        "--skip-original-if-edited",
        "--skip-bursts",
        "--skip-raw",
        "--convert-to-jpeg",
        "--jpeg-quality",
        str(jpeg_quality),
        "--exiftool",
        "--download-missing",
        "--report",
        str(report_path),
    ]


def _is_true(value: str | None) -> bool:
    """osxphotos' CSV writer emits 1/0; its JSON writer emits true/false.

    Verified against osxphotos 0.77.2: ExportReportWriterCSV calls
    prepare_export_results_for_writing WITHOUT bool_values=True, so the CSV
    carries integers. Accepting both costs nothing and survives either.
    """
    return str(value).strip().lower() in _TRUE_VALUES


def read_osxphotos_report(path: Path, report: ExportReport) -> None:
    """Fill `report`'s counts from an osxphotos CSV run report.

    Forgiving about a missing or unreadable file, because a report that cannot
    be read is not by itself proof that the export failed -- but NOT harmless:
    `export_album` refuses to swap when this leaves the counts empty, because
    the truncation check is the only thing standing between a short export and
    the user's trip folder.
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
        elif error:
            report.failed[error] += 1
        else:
            report.failed["export failed"] += 1


class ExportRefused(Exception):
    """The export did not finish usefully, and the target was not touched.

    A partial export may well exist, and several raise sites say where it is.
    What all of them guarantee is the second half: `destination` is as it was.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _free_space(path: Path) -> int:
    probe = path
    while not probe.exists():
        probe = probe.parent
    return shutil.disk_usage(probe).free


_JPEG_MAGIC = b"\xff\xd8\xff"


def _normalise_extensions(folder: Path) -> int:
    """Rename files whose bytes are JPEG but whose name says otherwise.

    An iCloud Shared Album hands out JPEG bytes under the original HEIC name --
    1170 of one real album's 2563 photos -- so --convert-to-jpeg has nothing to
    convert and keeps the name. Left alone those files are not counted as images
    by the swap gate, and the trip folder would claim a format it does not hold.

    Content decides, never the extension: a genuine HEIC is left exactly as it
    is, so it still fails the count and still refuses the swap, which is what
    the spec asks for.

    Hidden files and dot-directories are skipped, mirroring `_image_files`:
    renaming one could never help the count, and `.osxphotos_export.db` belongs
    to osxphotos, not to us.
    """
    renamed = 0
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() in {".jpg", ".jpeg"}:
            continue
        if path.name.startswith("."):
            continue
        if any(part.startswith(".") for part in path.relative_to(folder).parts[:-1]):
            continue
        try:
            with path.open("rb") as handle:
                if handle.read(len(_JPEG_MAGIC)) != _JPEG_MAGIC:
                    continue
        except OSError:
            continue
        target = path.with_suffix(".jpeg")
        counter = 1
        while target.exists():
            target = path.with_name(f"{path.stem}-{counter}.jpeg")
            counter += 1
        path.rename(target)
        renamed += 1
    return renamed


def _image_files(folder: Path) -> list[Path]:
    """Every file `find_photos` would pick up, and nothing else.

    The exclusions repeat `scan.find_photos` deliberately -- hidden files,
    AppleDouble sidecars and dot-directories carry image extensions but no image
    data. This module imports nothing from the package, so the rule is stated
    twice; it must agree with `src/fototrip/scan.py`, because counting a file the
    build will not include biases the swap gate toward accepting.
    """
    found = []
    for path in folder.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if path.name.startswith("."):
            continue
        if any(part.startswith(".") for part in path.relative_to(folder).parts[:-1]):
            continue
        found.append(path)
    return found


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
    if runner is None:  # pragma: no cover - a programming error, not a user path
        raise ValueError("export_album needs a runner")

    destination = Path(destination)
    # Tested before exists(), which follows the link. Renaming the link would
    # replace it with a real folder on the parent's volume and leave `.previous`
    # dangling; a plain file passes every is_dir() guard below and then dies on
    # the final rename with a bare NotADirectoryError.
    if destination.is_symlink():
        raise ExportRefused(
            f"{destination} is a symlink. Point --out at the real folder: replacing a "
            "symlink would put the photos on the wrong volume."
        )
    if destination.exists() and not destination.is_dir():
        raise ExportRefused(f"{destination} is not a directory.")

    existing = sorted(destination.iterdir()) if destination.is_dir() else []
    if existing and not replace:
        named = ", ".join(p.name for p in existing[:2])
        if len(existing) > 2:
            named += ", ..."
        raise ExportRefused(
            f"{destination} already holds {len(existing)} entries ({named}). "
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

    previous = parent / f"{destination.name}.previous"
    if previous.exists():
        raise ExportRefused(
            f"{previous} is in the way. It may be the old trip folder left by an "
            "interrupted run -- check what is in it before you move or delete it, "
            "then try again."
        )

    needed = max(
        int(in_album * MEGABYTES_PER_PHOTO * 1_000_000 * SPACE_MARGIN),
        MINIMUM_FREE_BYTES,
    )
    available = free_space(parent)
    if available < needed:
        # `needed` has two sources now: the estimate from --expect, and the floor
        # that applies without it. Naming the album's size when nothing counted it
        # produced "needed for 0 photos", which is the one sentence a user reads.
        if in_album:
            detail = f"about {_human_bytes(needed)} needed for {in_album} photos"
        else:
            detail = f"at least {_human_bytes(needed)} needed before an export can start"
        raise ExportRefused(
            f"Not enough space: {detail}, {_human_bytes(available)} free on {parent}."
        )

    incoming = parent / f"{destination.name}.incoming"
    # A suppressed failure here would leave another album's files beside the new
    # export, and extras only make the truncation check easier to satisfy.
    # `exists()` is False for a dangling symlink and rmtree refuses a symlink, so
    # a link is refused rather than followed -- it may point at someone's folder.
    if incoming.is_symlink():
        raise ExportRefused(
            f"The staging folder {incoming} is a symlink. Move or delete it, then try again."
        )
    if incoming.exists():
        try:
            shutil.rmtree(incoming)
        except OSError as error:
            raise ExportRefused(
                f"Could not clear the staging folder {incoming}: {error}. "
                "Move or delete it, then try again."
            ) from error

    # osxphotos declares its DEST argument `exists=True` and refuses a directory
    # that is not already there, so creating it is the caller's obligation.
    try:
        incoming.mkdir(parents=True)
    except OSError as error:
        raise ExportRefused(f"Could not create the staging folder {incoming}: {error}.") from error

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

    # Before anything is counted: a shared album's JPEG-bytes-under-a-HEIC-name
    # files are invisible to _image_files, which would refuse a perfect export.
    if incoming.is_dir():
        _normalise_extensions(incoming)

    read_osxphotos_report(report_path, report)
    written = _image_files(incoming) if incoming.is_dir() else []
    if not written:
        raise ExportRefused(
            f'The export produced no photos. Is "{album}" the exact album name? '
            f"{destination} was not touched."
        )
    if report.exported == 0 and not report.failed:
        raise ExportRefused(
            f"{len(written)} photos were written but {report_path} could not be read, "
            "so the export cannot be checked for truncation. "
            f"{destination} was not touched; the export is in {incoming}. "
            "An osxphotos version with different report columns would do this."
        )
    if len(written) < report.exported:
        raise ExportRefused(
            f"The export reported {report.exported} photos but wrote fewer ({len(written)}). "
            f"{destination} was not touched; the partial export is in {incoming}."
        )

    report.bytes_written = sum(p.stat().st_size for p in written)

    # The one destructive step. What it guarantees is that the photos are never
    # destroyed: both moves are renames, and the old folder is deleted only once
    # the new one is already in place. It is NOT atomic -- between the two renames
    # there is no trip folder at all, and a SIGKILL there leaves the photos at
    # `<folder>.previous`, which the next run refuses rather than deletes. An
    # atomic swap would need renamex_np(RENAME_SWAP), which the stdlib does not
    # expose. `.previous` IS the old folder, renamed rather than copied, so peak
    # disk usage is unchanged. Only a folder THIS run created is ever deleted, and
    # never with errors suppressed: a failed cleanup must be visible rather than
    # leave a silent duplicate of the whole folder.
    renamed_aside = False
    if destination.is_dir():
        destination.rename(previous)
        renamed_aside = True
    try:
        incoming.rename(destination)
    except OSError as error:
        if renamed_aside:
            try:
                previous.rename(destination)  # put it back exactly as it was
            except OSError:
                raise ExportRefused(
                    f"Could not move the export into place ({error}), and could not put "
                    f"the old folder back either. Nothing was deleted: the old folder is "
                    f"at {previous} and the export is in {incoming}."
                ) from error
        raise ExportRefused(
            f"Could not move the export into place: {error}. "
            f"{destination} is as it was; the export is in {incoming}."
        ) from error
    if renamed_aside:
        shutil.rmtree(previous)
    report_path.unlink(missing_ok=True)
    return report


def _default_osxphotos() -> str:
    """osxphotos as installed beside the running interpreter, else on PATH.

    `pip install -e '.[album]'` puts it in fototrip's own venv, but invoking
    `<venv>/bin/fototrip` does not put `<venv>/bin` on PATH, so a bare
    "osxphotos" is not found even though it is installed and working.
    """
    beside = Path(sys.executable).parent / "osxphotos"
    return str(beside) if beside.is_file() else "osxphotos"


def require_tools(osxphotos: str = "osxphotos") -> None:
    """Check both external tools up front, so a missing one is an instruction."""
    if shutil.which(osxphotos) is None:
        raise ExportRefused(
            f"{osxphotos} not found. Install it with:\n"
            f"    ~/src/venv/fototrip/bin/pip install -e '.[album]'"
        )
    if shutil.which("exiftool") is None:
        raise ExportRefused(
            "exiftool not found; it is what writes the library's coordinates into the\n"
            "exported files. Install it with:\n"
            "    brew install exiftool"
        )


def run_osxphotos(command: list[str]) -> int:
    """Run the export, letting its progress reach the terminal. Returns the exit status."""
    return subprocess.run(command, check=False).returncode
