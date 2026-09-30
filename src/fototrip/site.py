"""Render the static site: page shell, manifest, and vendored assets."""

import json
import shutil
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
)


@dataclass(frozen=True, slots=True)
class TripConfig:
    title: str
    subtitle: str = ""
    tile_url: str = OSM_TILE_URL
    tile_attribution: str = OSM_ATTRIBUTION

    @classmethod
    def load(cls, folder: Path, **overrides) -> "TripConfig":
        """Read trip.toml if present; keyword overrides win over the file."""
        values: dict = {"title": folder.name}
        toml_path = folder / "trip.toml"
        if toml_path.exists():
            allowed = {f for f in cls.__dataclass_fields__}
            values.update(
                {
                    k: v
                    for k, v in tomllib.loads(toml_path.read_text(encoding="utf-8")).items()
                    if k in allowed
                }
            )
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)


def _package_dir(name: str) -> Path:
    return Path(str(files("fototrip") / name))


def render_site(manifest: dict, config: TripConfig, out_dir: Path) -> None:
    """Write index.html, photos.json and every static asset into `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(_package_dir("templates")),
        # "index.html.j2" ends in ".j2", so that is the entry actually matching this
        # template's filename and turning autoescaping on; "html" never matches it.
        autoescape=select_autoescape(["html", "j2"]),
    )
    html = env.get_template("index.html.j2").render(
        title=config.title,
        subtitle=config.subtitle,
        tile_attribution=config.tile_attribution,
    )
    (out_dir / "index.html").write_text(html, encoding="utf-8")

    # The trip's name and its tile provider travel in the manifest rather than in
    # the page: the name so an overview over several trips can read it without
    # parsing HTML, the tiles so the page needs no inline script to hand them to
    # app.js -- which is what would force `script-src 'unsafe-inline'` on whatever
    # serves this. A copy, because the caller's dict is not ours to grow.
    payload = {
        "title": config.title,
        "subtitle": config.subtitle,
        "tiles": {"url": config.tile_url, "attribution": config.tile_attribution},
        **manifest,
    }
    (out_dir / "photos.json").write_text(
        json.dumps(payload, separators=(",", ":")), encoding="utf-8"
    )

    assets = _package_dir("assets")
    for name in ("app.js", "app.css"):
        shutil.copyfile(assets / name, out_dir / name)
    shutil.rmtree(out_dir / "vendor", ignore_errors=True)
    shutil.copytree(assets / "vendor", out_dir / "vendor")
