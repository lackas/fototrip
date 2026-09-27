"""Skip work for photos whose derivatives are already current."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0


class BuildCache:
    """Freshness by source size and mtime, plus existence of the outputs.

    Size and mtime are both in the key because Photos writes a file
    incrementally: a truncated JPEG seen on one run must be reprocessed on the
    next, and its mtime alone may not have moved far enough to notice.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.stats = CacheStats()
        self._entries: dict[str, list[float]] = {}
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict):
                self._entries = {k: v for k, v in loaded.items() if isinstance(v, list)}
        except (OSError, ValueError):
            self._entries = {}

    @staticmethod
    def _signature(source: Path) -> list[float]:
        info = source.stat()
        return [info.st_size, info.st_mtime]

    def is_fresh(self, source: Path, outputs: list[Path]) -> bool:
        key = str(source)
        try:
            current = self._signature(source)
        except OSError:
            self.stats.misses += 1
            return False
        fresh = self._entries.get(key) == current and all(o.exists() for o in outputs)
        if fresh:
            self.stats.hits += 1
        else:
            self.stats.misses += 1
        return fresh

    def record(self, source: Path) -> None:
        self._entries[str(source)] = self._signature(source)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._entries))
