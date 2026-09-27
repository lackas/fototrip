"""Skip work for photos whose derivatives are already current.

Standalone by design: only stdlib imports, so this module can be reasoned
about (and tested) without pulling in the rest of the package.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


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
                # Entries from a pre-fix version of this class were keyed on
                # the absolute source path. Loading one of those and writing
                # it straight back out would keep the exact leak this class
                # exists to close, indefinitely, across every rebuild. Drop
                # anything that isn't a plainly safe relative key instead --
                # cheap to degrade to a rebuild, cheap to get wrong the other
                # way.
                self._entries = {
                    k: v for k, v in loaded.items() if isinstance(v, list) and self._is_safe_key(k)
                }
        except (OSError, ValueError):
            self._entries = {}

    @staticmethod
    def _is_safe_key(key: str) -> bool:
        """A key must be a relative path with no leading slash and no '..'
        segment -- anything else is either an absolute path (this version's
        own `_key()` never produces one) or otherwise not something that was
        written by this version, and must not be trusted to stay private."""
        if not key or key.startswith(("/", "~")):
            return False
        return ".." not in PurePosixPath(key).parts

    def _key(self, source: Path) -> str:
        """Source path relative to `root`, forward-slashed so the same trip
        keys identically regardless of platform.

        Falls back to a stable hash of the resolved absolute path on the
        rare source that isn't actually under root (e.g. symlinked in from
        elsewhere): the hash must never be the path itself, or it would leak
        exactly like the bug this class exists to fix, straight into the
        published cache file. It has to stay stable across runs -- otherwise
        such a source could never be cached -- which a hash of the resolved
        path gives for free.
        """
        resolved = source.resolve()
        try:
            return resolved.relative_to(self.root.resolve()).as_posix()
        except ValueError:
            digest = hashlib.sha256(str(resolved).encode()).hexdigest()
            return f"external/{digest}"

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
