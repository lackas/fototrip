"""Fill a trip folder from a Photos.app album.

Standalone by design: only stdlib imports, so this module can be reasoned
about (and tested) without pulling in the rest of the package. The subprocess
call is injected, so no test needs a Photos library or a real export.

The Photos library is only ever read. Nothing here writes to it.
"""

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
