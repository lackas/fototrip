"""Fill a trip folder from a Photos.app album.

Standalone by design: only stdlib imports, so this module can be reasoned
about (and tested) without pulling in the rest of the package. The subprocess
call is injected, so no test needs a Photos library or a real export.

The Photos library is only ever read. Nothing here writes to it.
"""

from collections import Counter
from dataclasses import dataclass, field


def _human_bytes(count: int) -> str:
    """Bytes as a short decimal string: 4_900_000_000 -> '4.9 GB'."""
    value = float(count)
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            return f"{value:.1f} {unit}" if unit not in ("B", "kB") else f"{value:.0f} {unit}"
        value /= 1000
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
