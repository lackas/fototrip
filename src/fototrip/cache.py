"""Skip work for photos whose derivatives are already current.

Standalone by design: only stdlib imports, so this module can be reasoned
about (and tested) without pulling in the rest of the package.
"""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0


class BuildCache:
    """Freshness by source size and mtime plus the derivative settings that
    produced them, plus existence of the outputs.

    Size and mtime are both in the key because Photos writes a file
    incrementally: a truncated JPEG seen on one run must be reprocessed on the
    next, and its mtime alone may not have moved far enough to notice.
    `thumb_px`/`web_px` are in the key too, so a re-run with different sizes
    invalidates exactly the entries that need it instead of reporting a stale
    derivative as cached.

    Entries are keyed on the source path *relative to `root`* (normally the
    trip folder), not the absolute path: the cache file is published inside
    the site's output folder, so an absolute key would leak the machine's
    home directory and folder layout, and would also make the same trip built
    from a relative path one day and an absolute path the next look like an
    entirely different set of files.
    """

    def __init__(self, path: Path, root: Path, *, thumb_px: int, web_px: int) -> None:
        self.path = path
        self.root = root
        self.thumb_px = thumb_px
        self.web_px = web_px
        self.stats = CacheStats()
        self._entries: dict[str, list[float]] = {}
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, dict):
                self._entries = {k: v for k, v in loaded.items() if isinstance(v, list)}
        except (OSError, ValueError):
            self._entries = {}

    def _key(self, source: Path) -> str:
        """Source path relative to `root`, forward-slashed so the same trip
        keys identically regardless of platform. Falls back to the resolved
        absolute path on the rare source that isn't actually under root."""
        try:
            return source.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return source.resolve().as_posix()

    def _signature(self, source: Path) -> list[float]:
        info = source.stat()
        return [info.st_size, info.st_mtime, self.thumb_px, self.web_px]

    def is_fresh(self, source: Path, outputs: list[Path]) -> bool:
        try:
            current = self._signature(source)
        except OSError:
            self.stats.misses += 1
            return False
        fresh = self._entries.get(self._key(source)) == current and all(o.exists() for o in outputs)
        if fresh:
            self.stats.hits += 1
        else:
            self.stats.misses += 1
        return fresh

    def record(self, source: Path) -> None:
        self._entries[self._key(source)] = self._signature(source)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._entries))
